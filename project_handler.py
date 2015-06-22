import json
import logging
import os

from google.appengine.api import memcache, urlfetch, users

import jinja2

import webapp2

from config import Config


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
