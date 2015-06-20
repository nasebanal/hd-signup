""" Special REST API for securely transfering user data between applications.
"""


import datetime
import hashlib
import json
import logging

from google.appengine.ext import db

import webapp2

import pytz

from config import Config
from membership import Membership
import keymaster
import plans
import subscriber_api


""" Increments the number of signins for a user. Also suspends the user if they
are out of visits.
user: The user to increment signins for.
Returns: The number of visits remaining for a user. """
def _increment_signins(user):
  # Time-dependent checks don't play well with unit tests...
  if not Config().is_testing:
    # The weekends and after-hours don't count.
    timezone = pytz.timezone("America/Los_Angeles")
    now = datetime.datetime.now(timezone)
    day = now.weekday()
    if day in (5, 6):
      logging.info("Not incrementing singin counter because it is a weekend.")
      return plans.Plan.signins_remaining(user)
    hour = now.hour
    logging.debug("Hour: %d" % (hour))
    if (hour < Config().DOJO_HOURS[0] or hour > Config().DOJO_HOURS[1]):
      logging.info("Not incrementing signin counter because it is after-hours.")
      return plans.Plan.signins_remaining(user)

  # Increment signins.
  user.signins += 1

  remaining = plans.Plan.signins_remaining(user)
  logging.info("Visits remaining for %s: %s" % \
              (user.username, str(remaining)))

  if remaining == 0:
    # No more visits left. Suspend the user.
    user.status = "no_visits"
    subscriber_api.suspend(user.username)

  user.put()
  return remaining


""" Generic superclass for all API Handlers. """
class ApiHandlerBase(webapp2.RequestHandler):
  # Apps that can use this API.
  _AUTHORIZED_APPS = ("hd-events", "hd-signin-hrd")

  """ A function meant to be used as a decorator. It ensures that an authorized
  app is making the request before running the function.
  function: The function that we are decorating.
  Returns: A wrapped version of the function that interrupts the flow if it
           finds a problem. """
  @classmethod
  def restricted(cls, function):
    """ Wrapper function to return. """
    def wrapper(self, *args, **kwargs):
      app_id = self.request.headers.get("X-Appengine-Inbound-Appid", None)
      logging.debug("Got request from app: %s" % (app_id))

      # If we're not on production, don't deny any requests.
      conf = Config()
      if not conf.is_prod:
        logging.info("Non-production environment, servicing all requests.")

      elif app_id not in self._AUTHORIZED_APPS:
        logging.warning("Not running '%s' for unauthorized app '%s'." % \
            (function.__name__, app_id))
        self._rest_error("Unauthorized", "Only select apps can do that.", 403)
        return

      function(self, *args, **kwargs)

    return wrapper

  """ Writes a specific error and aborts the request.
  error_type: The type of error.
  message: The error message.
  status: HTTP status to return. """
  def _rest_error(self, error_type, message, status):
    message = {"type": error_type + "Exception", "message": message}
    message = json.dumps(message)
    logging.error("Rest API error: %s" % (message))

    self.response.clear()
    self.response.out.write(message)
    self.response.set_status(status)

  """ Gets parameters from the request, and raises an error if any are missing.
  *args: Parameters to get.
  Returns: A list of parameter values, in the order specified.
  """
  def _get_parameters(self, *args):
    values = []
    for arg in args:
      value = self.request.get(arg)

      if not value:
        # Try getting the list version of the argument.
        value = self.request.get_all(arg + "[]")

        if not value:
          message = "Expected argument '%s'." % (arg)
          self._rest_error("InvalidParameters", message, 400)
          # So unpacking doesn't fail annoyingly...
          if len(args) == 1:
            return None
          return [None] * len(args)

      values.append(value)

    # If it is a singleton, it is easier not to return it as a list, because
    # then the syntax can just stay the same as if we were unpacking multiple
    # values.
    if len(values) == 1:
      return values[0]
    return values


""" Handler for getting data for a particular user. """
class UserHandler(ApiHandlerBase):
  """ Properties for this request:
  username: The username for which we are getting data.
  properties: a x-www-form-urlencoded formatted list of property names we want
  for this user. I like it this way because we don't need to send really
  sensitive data unless someone requests it explicitly.
  Returns: A json-encoded dictionary of each property and its value for the
  user. """
  @ApiHandlerBase.restricted
  def get(self):
    username, properties = self._get_parameters("username", "properties")
    if type(properties) is unicode:
      # A singleton property.
      properties = [properties]

    if not username:
      return
    logging.info("Fetching properties for user '%s'." % (username))

    # Get the user data.
    users_query = db.GqlQuery( \
        "SELECT * FROM Membership WHERE username = :1", username)
    if users_query.count(limit=2) > 1:
      logging.critical("Found duplicate username. (That shouldn't happen.)")
      self._rest_error("Internal", "Multiple entries with this username?!", 500)

    found_user = users_query.get()
    if not found_user:
      logging.error("Found no users with username '%s'." % (username))
      self._rest_error("InvalidParameters",
          "Found no user with that username", 422)
      return

    all_properties = {}
    # Get the actual value of all the properties.
    for key in found_user.properties().keys():
      all_properties[key] = getattr(found_user, key)

    use_properties = {}
    for prop in properties:
      if prop not in all_properties.keys():
        logging.error("User has no property '%s'." % (prop))
        self._rest_error("InvalidParameters", "User has no property '%s'." % \
                         (prop), 422)
        return

      use_properties[prop] = all_properties[prop]

    response = json.dumps(use_properties)
    logging.debug("Writing response: %s." % (response))
    self.response.out.write(response)


""" Handles user signin events. """
class SigninHandler(ApiHandlerBase):
  """ Called when a particular user signs in using their email.
  Properties for this request:
  email: The email of the user.
  Response: Has a 'visits_remaining' parameter that indicates how many visits
  this user has remaining. It could also be None, which indicates that there are
  no limitations on number of visits for this user. """
  @ApiHandlerBase.restricted
  def post(self):
    email = self._get_parameters("email")
    if not email:
      return

    # Get information on the user from the datastore.
    if "@hackerdojo.com" in email:
      user = Membership.get_by_username(email.replace("@hackerdojo.com", ""))
    else:
      user = Membership.get_by_email(email)

    if (not user or user.status not in ("active", "no_visits")):
      self._rest_error("InvalidEmail",
          "Could not find an active user with email '%s'." % (email), 422)
      return

    remaining = _increment_signins(user)

    response = json.dumps({"visits_remaining": remaining})
    self.response.out.write(response)

""" Handles RFID tag events. """
class RfidHandler(ApiHandlerBase):
  """ Signs in people using their RFID tag.
  Properties for this request:
  id: The number on the RFID tag.
  Response: A json object with some information about the user signed in. It
  also has a visits_remaining parameter that is the same as for
  SigninHandler.post. """
  @ApiHandlerBase.restricted
  def post(self):
    rfid = self._get_parameters("id")
    if not rfid:
      return

    # Sign in a member.
    member = db.GqlQuery("SELECT * FROM Membership WHERE rfid_tag = :1" \
                          " AND status IN ('active', 'no_visits')", rfid).get()
    if not member:
      self._rest_error("InvalidKey",
                        "This key does not exist, or is suspended.", 422)
      return

    # Record the signin.
    remaining = _increment_signins(member)

    email = "%s.%s@%s" % (member.first_name, member.last_name,
                          Config().APPS_DOMAIN)
    email = email.lower()
    gravatar_url = "http://www.gravatar.com/avatar/" + \
                    hashlib.md5(email).hexdigest()
    name = "%s %s" % (member.first_name, member.last_name)
    response = {"gravatar": gravatar_url, "auto_signin": member.auto_signin,
                "name": name, "username": member.username,
                "email": member.email, "visits_remaining": remaining}
    self.response.out.write(json.dumps(response))


""" Handles requests from maglock system. """
class MaglockHandler(ApiHandlerBase):
  """ Handler for getting a list of people who can unlock maglocks.
  key: The key for the maglock that authenticates this request.
  Response: A json object containing a list of users. Each element contains a
  username and a corresponding RFID key. """
  def get(self, key):
    logging.debug("Getting list of users for maglock.")

    # The maglock is requesting a list of users.
    if key != keymaster.get("maglock:key"):
      self._rest_error("Unauthorized", "Invalid maglock key.", 401)
      return

    # Our key is valid. Give it the list.
    query = db.GqlQuery("SELECT * FROM Membership WHERE rfid_tag != NULL" \
                        " AND status = 'active'")

    response = []
    for member in query.run():
      response.append({"rfid_tag": member.rfid_tag,
                        "username": member.username})
    self.response.out.write(json.dumps(response))


app = webapp2.WSGIApplication([
    ("/api/v1/user", UserHandler),
    ("/api/v1/signin", SigninHandler),
    ("/api/v1/rfid", RfidHandler),
    ("/api/v1/maglock/(.+)", MaglockHandler)],
    debug=True)
