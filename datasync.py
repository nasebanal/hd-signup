# Accepts non-critical data from main signup application.

import datetime
import json
import logging

from google.appengine.api import urlfetch
from google.appengine.ext import db
from google.appengine.ext import webapp

from config import Config
from membership import Membership

# Datastore model to keep track of DataSync information.
class SyncRunInfo(db.Model):
  run_times = db.IntegerProperty(default = 0)

# Handler for syncing data between dev and production apps.
class DataSyncHandler(webapp.RequestHandler):
  dev_url = "http://signup-dev.appspot.com/_datasync"
  cron_interval = 60
  time_format = "%Y %B %d %H %M %S"

  def get(self):
    config = Config()
    if not config.is_dev:
      # If we're production, send out new models.
      if ("X-Appengine-Cron" in self.request.headers.keys()) and \
          (self.request.headers["X-Appengine-Cron"]):
        # Only do this if a cron job told us to.
        run_info = SyncRunInfo.all().get()
        if not run_info:
          run_info = SyncRunInfo()
          run_info.put()
        if run_info.run_times == 0:
          # This is the first run. Sync everything.
          logging.info("First run, syncing everything...")
          members = Membership.all()
        else:
          # Check for entries that changed since we last ran this.
          last_run = datetime.datetime.now()
          last_run -= datetime.timedelta(minutes = self.cron_interval)
          members = Membership.all().filter("updated >", last_run)
        
        # Update the number of times we've ran this.
        run_info.run_times = run_info.run_times + 1
        logging.info("Ran sync %d times." % (run_info.run_times))
        run_info.put()

        for member in members:
          member = self.__strip_sensitive(member)
          self.__post_member(member)
      else:
        self.response.out.write("<h4>Only cron jobs can do that!</h4>")
        logging.info("Got GET request from non-cron job.")

  # Posts member data to dev application.
  def __post_member(self, member):
    data = db.to_dict(member)
    # Convert datetimes to strings.
    for key in data.keys():
      if hasattr(data[key], "strftime"):
        data[key] = data[key].strftime(self.time_format)
    data = json.dumps(data)
    
    logging.debug("Posting entry: " + data)
    response = urlfetch.fetch(url = self.dev_url, payload = data,
        method = urlfetch.POST,
        headers = {"Content-Type": "application/json"})
    if response.status_code != 200:
      logging.error("POST received status code %d!" % (response.status_code))

  # Removes sensitive data from membership instances.
  def __strip_sensitive(self, member):
    member.spreedly_token = None
    return member
  
  def post(self):
    if Config.is_dev:
      # Only allow this if it's the dev server.
      entry = self.request.body
      logging.debug("Got new entry: " + entry)
      entry = json.loads(entry)
      # Change formatted date back into datetime.
      for key in entry.keys():
        if type(getattr(Membership, key)) == db.DateTimeProperty:
          entry[key] = datetime.datetime.strptime(entry[key], self.time_format)
      # entry should have everything nicely in a dict...
      member = Membership(**entry)

      # Is this an update or a new model?
      match = Membership.all().filter("username =", member.username).get()
      if match:
        # Replace the old one.
        logging.debug("Found entry with same username. Replacing...")
        db.delete(match)

      member.put()
      logging.debug("Put entry in datastore.")

app = webapp.WSGIApplication([
    ("/_datasync", DataSyncHandler),
    ], debug = True)
