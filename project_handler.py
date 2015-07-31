import json
import logging
import os
import urllib

import jinja2

from google.appengine.api import memcache

from webapp2_extras import auth, security, sessions
import webapp2

from config import Config
import keymaster


JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)), autoescape=True)


""" A generic superclass for all handlers. """
class ProjectHandler(webapp2.RequestHandler):
  # A user to use for simulating logins during unit testing.
  simulated_user = None

  """ Checks if the current user is an admin and displays an error message if
  they aren't. Also prompts them to log in if they are not. This is meant to be
  used as a decorator.
  function: The function we are decorating.
  Returns: A wrapped version of the function that performs the check and
  interrupts the flow if anything goes wrong. """
  @classmethod
  def admin_only(cls, function):
    """ The wrapper function that does the actual check. """
    def wrapper(self, *args, **kwargs):
      user = self.current_user()
      if not user:
        # They need to log in.
        self.redirect(self.create_login_url(self.request.uri))
        return

      if not user["is_admin"]:
        # They are not an admin.
        error_page = self.render("templates/error.html", internal=False,
            message="Admin access is required. <a href=%s>Try Again</a>" % \
                (self.create_logout_url(self.request.uri)))
        self.response.out.write(error_page)
        self.response.set_status(401)
        return

      return function(self, *args, **kwargs)

    return wrapper

  """ Decorator that ensures that a user is logged in. If they aren't logged
  in, it redirects to the login page and forces them to.
  function: The function we are decorating.
  Returns: A wrapped version of the function. """
  @classmethod
  def login_required(cls, function):
    """ The wrapper function that does that actual check. """
    def wrapper(self, *args, **kwargs):
      user = self.current_user()
      if not user:
        # They need to log in.
        self.redirect(self.create_login_url(self.request.uri))
        return

      return function(self, *args, **kwargs)

    return wrapper

  """ Simulate a logged in user for unit testing.
  user: The user object to use. None indicates that we want there to be no
  logged in user. """
  @classmethod
  def simulate_logged_in_user(cls, user):
    if not Config().is_testing:
      raise ValueError("Can't simulate login when not unit testing.")

    cls.simulated_user = user

  """ Checks if a current user is logged in.
  Returns: A dict with information about the current logged in user,
  or None. """
  def current_user(self):
    simulated_user = ProjectHandler.simulated_user

    if not Config().is_testing:
      auth = self.auth
      user = auth.get_user_by_session()
    else:
      # Use the simulated user.
      logging.debug("Using simulated user: %s" % (simulated_user))

      if not simulated_user:
        user = None
      else:
        user = {}
        for attribute in \
            self.app.config["webapp2_extras.auth"]["user_attributes"]:
          user[attribute] = getattr(simulated_user, attribute)

    if user:
      logging.debug("Current logged in user: %s" % (user["email"]))
    else:
      logging.debug("No logged in user.")

    return user

  """ Equivalent to the create_login_url function from the GAE users package,
  but for our custom account system.
  return_url: The url to return to after we have logged in. """
  def create_login_url(self, return_url):
    query_str = urllib.urlencode({"url": return_url})
    url = "/login?" + query_str
    return url

  """ Equivalent to the create_logout_url function from the GAE users package,
  but for our custom account system.
  return_url: The url to return to after we have logged out. """
  def create_logout_url(self, return_url):
    query_str = urllib.urlencode({"url": return_url})
    url = "/logout?" + query_str
    return url

  """ Render out templates with the proper information.
  path: Path to the template file.
  values: Values to fill in the template with.
  These values can also be passed in as individual keyword arguments. """
  def render(self, path, values={}, **kwargs):
    conf = Config()
    template_vars = {"is_prod": conf.is_prod, "org_name": conf.ORG_NAME,
        "analytics_id": conf.GOOGLE_ANALYTICS_ID, "domain": conf.APPS_DOMAIN}
    # Add the request object if we have one.
    try:
      template_vars["request"] = self.request
    except AttributeError:
      pass

    template_vars.update(values)
    template_vars.update(kwargs)

    if conf.is_dev:
        template_vars["dev_message"] = "You are using the dev version of \
            Signup."

    template = JINJA_ENVIRONMENT.get_template(path)
    return template.render(template_vars)

  """ Shortcut to access the auth instance as a property. """
  @webapp2.cached_property
  def auth(self):
    return auth.get_auth()

  """ Shortcut to access a subset of the user attributes that are stored in the
  session. The list of attributes to store in the session is specified in the
  webapp2 configuration.
  Returns: A dictionary with some user information. """
  @webapp2.cached_property
  def user_info(self):
    return self.auth.get_user_by_session()

  """ Access the current logged in user. Unlike user_info, it fetches
  information from the datastore.
  Returns: An instance of the underlying Membership model. """
  @webapp2.cached_property
  def user(self):
    user = self.user_info
    if not user:
      return None

    return self.user_model.get_by_id(user["user_id"])

  """ Returns the implementation of the user model. This is set in the webapp2
  configuration. """
  @webapp2.cached_property
  def user_model(self):
    return self.auth.store.user_model

  """ Shortcut to access the current session. """
  @webapp2.cached_property
  def session(self):
    return self.session_store.get_session()

  """ Custom dispatcher so that webapp2 sessions work properly. """
  def dispatch(self):
    # Get a session store for this request.
    self.session_store = sessions.get_store(request=self.request)

    try:
      # Dispatch the request.
      webapp2.RequestHandler.dispatch(self)
    finally:
      # Save all sessions.
      self.session_store.save_sessions(self.response)


""" Generic superclass for all webapp2 applications. """
class BaseApp(webapp2.WSGIApplication):
  def __init__(self, *args, **kwargs):
    super(BaseApp, self).__init__(*args, **kwargs)

    # If we're unit testing, use the same one every time for consistent results.
    if Config().is_testing:
      secret = "notasecret"

    else:
      # Check that we have a secret key for generating tokens.
      try:
        secret = keymaster.get("token_secret")
      except keymaster.KeymasterError:
        logging.warning("Found no token secret, generating one.")
        secret = security.generate_random_string(entropy=128)
        keymaster.Keymaster.encrypt("token_secret", secret)

    # Configure webapp2.
    my_config = {
      "webapp2_extras.auth": {
        "user_model": "membership.Membership",
        "user_attributes": ["first_name", "last_name", "email", "hash",
                            "is_admin"]
      },
      "webapp2_extras.sessions": {
        "secret_key": secret
      }
    }
    self.config = webapp2.Config(my_config)
