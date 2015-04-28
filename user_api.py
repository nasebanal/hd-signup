""" Special REST API for securely transfering user data between applications.
"""


import json
import logging

from google.appengine.ext import db

import webapp2

from config import Config


""" Generic superclass for all API Handlers. """
class ApiHandlerBase(webapp2.RequestHandler):
  # Apps that can use this API.
  _AUTHORIZED_APPS = ("hd-events", "hd-signin")

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
          return [None] * len(args)

      values.append(value)

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


app = webapp2.WSGIApplication([
    ("/api/v1/user", UserHandler)],
    debug=True)