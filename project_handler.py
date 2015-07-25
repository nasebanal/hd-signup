import json
import logging
import os

from google.appengine.api import memcache, urlfetch, users

import jinja2

from webapp2_extras import auth, security, sessions
import webapp2

from config import Config
import keymaster


JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)), autoescape=True)


""" A generic superclass for all handlers. """
class ProjectHandler(webapp2.RequestHandler):
  # Usernames to return for testing purposes.
  testing_usernames = []

  """ Allows the user to set which usernames it returns in testing mode. If
  someone tries to run this on a production app, it throws an exception.
  username: The username to add. """
  @classmethod
  def add_username(cls, username):
    if Config().is_prod:
      logging.critical("Can't fake usernames on a production app.")
      raise ValueError("Can't fake usernames on a production app.")

    ProjectHandler.testing_usernames.append(username)

  """ Clears all the fake usernames. """
  @classmethod
  def clear_usernames(cls):
    if Config().is_prod:
      logging.critical("Can't clear fake usernames on a production app.")
      raise ValueError("Can't clear fake usernames on a production app.")

    ProjectHandler.testing_usernames = []

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
      user = users.get_current_user()
      if not user:
        # They need to log in.
        self.redirect(users.create_login_url(self.request.uri))
        return

      logging.debug("Logged in user: %s" % (user.email()))

      if not users.is_current_user_admin():
        # They are not an admin.
        error_page = self.render("templates/error.html", internal=False,
            message="Admin access is required. <a href=%s>Try Again</a>" % \
                (users.create_logout_url(self.request.uri)))
        self.response.out.write(error_page)
        self.response.set_status(401)
        return

      return function(self, *args, **kwargs)

    return wrapper

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

  """ Fetches all the usernames in the datastore.
  use_cache: Whether or not to use a cached version of the usernames.
  Returns: A list of the usernames, or None upon failure. """
  def fetch_usernames(self, use_cache=True):
    conf = Config()

    if conf.is_testing:
      logging.info("Using fake usernames: %s" % (self.testing_usernames))
      return self.testing_usernames

    usernames = memcache.get("usernames")
    if usernames and use_cache:
      return usernames
    else:
      resp = urlfetch.fetch("http://%s/users" % conf.DOMAIN_HOST, deadline=10,
                            follow_redirects=False)
      if resp.status_code == 200:
          usernames = [m.lower() for m in json.loads(resp.content)]
          if not memcache.set("usernames", usernames, 60*60*24):
              logging.error("Memcache set failed.")
          return usernames
      else:
        logging.critical("Failed to fetch list of users. (%d)" %
            (resp.status_code))

      # Render error page.
      error_page = self.render("templates/error.html",
          message="/users returned non-OK status.",
          internal=True)
      self.response.out.write(error_page)
      return None

  """ Marks the cached list of usernames as stale. """
  def invalidate_cached_usernames(self):
    # It doesn't throw an exception if the item does not exist.
    logging.debug("Cached usernames are now stale.")
    memcache.delete("usernames")

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
        "user_attributes": ["first_name", "last_name", "email", "hash"]
      },
      "webapp2_extras.sessions": {
        "secret_key": secret
      }
    }
    self.config = webapp2.Config(my_config)
