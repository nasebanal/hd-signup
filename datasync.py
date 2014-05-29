# Accepts non-critical data from main signup application.

import datetime
import json
import logging

from google.appengine.api import urlfetch
from google.appengine.ext import db
from google.appengine.ext import webapp

from config import Config
from membership import Membership

class DataSyncHandler(webapp.RequestHandler):
  dev_url = "http://signup-dev.appspot.com/_datasync"
  cron_interval = 60
  time_format = "%Y %B %d %H %M %S"

  def get(self):
    if not Config.is_dev:
      # If we're production, send out new models.
      if ("X-Appengine-Cron" in self.request.headers.keys()) and \
          (self.request.headers["X-Appengine-Cron"]):
        # Only do this if a cron job told us to.
        # Check for entries that changed since we last ran this.
        last_run = datetime.datetime.now()
        last_run -= datetime.timedelta(minutes = self.cron_interval)
        members = Membership.all().filter("updated >", last_run)
        for member in members:
          member = self.__strip_sensitive(member)
          self.__post_member(member)
      else:
        self.response.out.write("<h4>Only cron jobs can do that!</h4>")

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
