""" Contains handlers that are run periodically as cron jobs. """


import datetime
import json
import logging

from google.appengine.api import urlfetch
from google.appengine.api import datastore
from google.appengine.ext import db

import webapp2

from config import Config
from membership import Membership
from project_handler import ProjectHandler
import subscriber_api


""" Superclass for all cron jobs. """
class CronHandlerBase(ProjectHandler):
  """ A function meant to be used as a decorator. It ensures that a cron job
  is making the request before running the function.
  function: The function that we are decorating.
  Returns: A wrapped version of the function that interrupts the flow if it
           finds a problem. """
  @classmethod
  def cron_only(cls, function):
    """ Wrapper function to return. """
    def wrapper(self, *args, **kwargs):
      cron = self.request.headers.get("X-Appengine-Cron", None)

      # If we're on the dev app, we don't want to run cron jobs at all.
      conf = Config()
      if (cron and conf.is_dev):
        logging.info("Not running cron job on dev app.")
        return

      # If we're not on production, don't deny any requests.
      if not conf.is_prod:
        logging.info("Non-production environment, servicing all requests.")

      elif not cron:
        logging.warning("Not running '%s' for non-cron job." % \
            (function.__name__))
        self.response.out.write("Only cron jobs can do that.")
        self.set_status(403)
        return

      return function(self, *args, **kwargs)

    return wrapper

  """ A function meant to be used as a decorator. It stops this from running
  on the dev app if it is being run from a cron job.
  function: The function we are decorating.
  Returns: A wrapped version of the function that interrupts the flow if it
  finds a problem. """
  @classmethod
  def no_dev(cls, function):
    """ Wrapper function to return. """
    def wrapper(self, *args, **kwargs):
      cron = self.request.headers.get("X-Appengine-Cron", None)

      # If we're on the dev app, we don't want to run cron jobs at all.
      conf = Config()
      if (cron and conf.is_dev):
        logging.info("Not running cron job on dev app.")
        return

      return function(self, *args, **kwargs)

    return wrapper


""" Periodically refreshes the list of cached domain users. """
class CacheUsersHandler(CronHandlerBase):
  @CronHandlerBase.cron_only
  def get(self):
    self.fetch_usernames(use_cache=False)


""" Datastore model to keep track of DataSync information. """
class SyncRunInfo(db.Model):
  run_times = db.IntegerProperty(default = 0)
  # The most recent cursor.
  cursor = db.StringProperty();
  # The last time we ran this successfully.
  last_run = db.DateTimeProperty()


""" Handler for syncing data between dev and production apps. """
class DataSyncHandler(CronHandlerBase):
  dev_url = "http://signup-dev.appspot.com/cron/datasync"
  time_format = "%Y %B %d %H %M %S"
  # The size of a batch for __batch_loop.
  batch_size = 10

  @CronHandlerBase.cron_only
  @CronHandlerBase.no_dev
  def get(self):
    # If we're production, send out new models.
    run_info = SyncRunInfo.all().get()
    if not run_info:
      run_info = SyncRunInfo()
      run_info.put()

    if run_info.run_times == 0:
      # This is the first run. Sync everything.
      logging.info("First run, syncing everything...")
      self.__batch_loop(run_info.cursor)
    else:
      # Check for entries that changed since we last ran this.
      last_run = run_info.last_run
      logging.info("Last successful run: " + str(last_run))
      self.__batch_loop(run_info.cursor, "updated >", last_run)

    # Update the number of times we've run this.
    run_info = SyncRunInfo().all().get()
    run_info.run_times = run_info.run_times + 1
    # Clear the cursor property if we synced successfully.
    run_info.cursor = None
    logging.info("Ran sync %d time(s)." % (run_info.run_times))
    # Update the time of the last successful run.
    run_info.last_run = datetime.datetime.now()
    run_info.put()

  """ Gets the requested member information from the datastore and sends it.
  cursor: Specifies a cursor to start fetching data at.
  Additional arguments can be specified which will be used as a filter for the
  datastore query. """
  def __batch_loop(self, cursor = None, *args, **kwargs):
    cursor = cursor
    while True:
      if (args == () and kwargs == {}):
        query = Membership.all()
      else:
        query = Membership.all().filter(*args, **kwargs)
      query.with_cursor(start_cursor = cursor)
      members = query.fetch(self.batch_size)

      if len(members) == 0:
        break
      for member in members:
        member = self.__strip_sensitive(member)
        self.__post_member(member)

      cursor = query.cursor()
      run_info = SyncRunInfo.all().get()
      run_info.cursor = cursor
      run_info.put()

  """ Posts member data to dev application.
  member: The member whose data we are posting. """
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
      raise RuntimeError("POST failed. Check your quotas.")

  """ Removes sensitive data from membership instances.
  member: The member which we are removing sensitive information from. """
  def __strip_sensitive(self, member):
    member.spreedly_token = None
    member.password = None
    member.hash = None
    return member

  def post(self):
    if Config().is_dev:
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
      match = Membership.all().filter("email =", member.email).get()
      if match:
        # Replace the old one.
        logging.debug("Found entry with same username. Replacing...")
        db.delete(match)

      member.put()
      logging.debug("Put entry in datastore.")


""" Handles resetting signin count at the start of every month. """
class ResetSigninHandler(CronHandlerBase):
  @CronHandlerBase.cron_only
  @CronHandlerBase.no_dev
  def get(self):
    query = db.GqlQuery("SELECT * FROM Membership WHERE signins != 0")

    member_writes = []
    for member in query.run():
      member.signins = 0
      if member.status == "no_visits":
        logging.info("Restoring user that ran out of visits: %s" % \
                     (member.username))
        subscriber_api.restore(member.username)
        member.status = "active"

      member_future = db.put_async(member)
      member_writes.append(member_future)

    logging.debug("Waiting for writes to complete...")
    for async_write in member_writes:
      async_write.get_result()


""" Notifies and removes users who never finished signing up. """
class CleanupHandler(CronHandlerBase):
  @CronHandlerBase.cron_only
  @CronHandlerBase.no_dev
  def get(self):
    countdown = 0
    for membership in Membership.all().filter("status =", None):
      if (datetime.datetime.now().date() - membership.created.date()).days > 1:
        countdown += 90
        self.response.out.write("bye %s " % (membership.email))
        taskqueue.add(url="/tasks/clean_row", params={"user": membership.key().id()}, countdown=countdown)


""" Sends an email to suspended users who never unsubscribed. """
class AreYouStillThereHandler(CronHandlerBase):
  @CronHandlerBase.cron_only
  @CronHandlerBase.no_dev
  def get(self):
    countdown = 0
    for membership in Membership.all().filter("status =", "suspended"):
      if (not membership.unsubscribe_reason and membership.spreedly_token \
          and "Deleted" not in membership.last_name and \
          membership.extra_dnd != True):
        # One e-mail every 90 seconds = 960 e-mails a day.
        countdown += 90
        self.response.out.write("Are you still there %s ?<br/>" % \
                                (membership.email))
        taskqueue.add(url="/tasks/areyoustillthere_mail",
            params={"user": membership.key().id()}, countdown=countdown)


app = webapp2.WSGIApplication([
    ("/cron/datasync", DataSyncHandler),
    ("/cron/reset_signins", ResetSigninHandler),
    ("/cron/cache_users", CacheUsersHandler),
    ("/cron/cleanup", CleanupHandler),
    ("/cron/areyoustillthere", AreYouStillThereHandler)],
    debug=True)
