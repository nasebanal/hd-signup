""" These pages provide a simple way to authenticate with new-style accounts.
Usage: Direct a user to the /login page with a redirect URL, it will redirect
after the user has successfully authenticated. To check whether the user has
authenticated, use the /validate_token API endpoint. """


from urlparse import urlparse
import cPickle as pickle
import json
import logging
import urllib

from google.appengine.api import mail, memcache

from webapp2_extras import auth

from config import Config
from project_handler import ProjectHandler
from membership import Membership, UserToken
from user_api import ApiHandlerBase


""" Handles creating a login page and logging a user in. """
class LoginHandler(ProjectHandler):
  """ Parameters:
  app_id: The Appengine ID of the application making the request. If this is not
  included with a url parameter, it will be assumed that the current app is
  making the request and no token will be included in the redirect request.
  Otherwise, a token will be included that will allow the app specified to
  confirm that the logged in user is still logged in using /validate_token.
  url: A URL to send the user to after they have successfully logged in.
  Defaults to the home page.
  """
  def get(self):
    response = self.render("templates/login.html")
    self.response.out.write(response)

  def post(self):
    email = self.request.get("email")
    password = self.request.get("password")
    return_url = self.request.get("url", "/")
    app_id = self.request.get("app_id")

    # Rate limit requests.
    key = "rate_limit.%s" % (email)
    if memcache.get(key):
      # Too many requests, deny it.
      logging.warning("Rate limiting login for %s." % (email))
      self.abort(429)
      return
    # Write to the memcache with an expiration time of one second. That way, if
    # we see it still there again, we know we should limit the client.
    memcache.set(key, True, time=1)

    # Check the password.
    try:
      # If we are getting a request from outside the domain, we shouldn't bother
      # saving a cookie on this one.
      remember = not app_id
      user_info = \
          self.auth.get_user_by_password(email, password, remember=remember)
      user = Membership.get_by_hash(user_info["hash"])

    except auth.InvalidAuthIdError as e:
      logging.warning("Unknown user: %s." % (email))
      self.__show_error()
      return
    except auth.InvalidPasswordError as e:
      logging.warning("Invalid password for user %s." % (email))
      self.__show_error()
      return

    # Check that the user can log in.
    if not user.status:
      self.__show_error("You have not finished signing up.", keep_email=False)
      return
    elif user.status == "suspended":
      link = "/reactivate"
      self.__show_error(
          message="You are suspended. <a href=\"%s\">Click here</a>" \
                  " to reactivate." % (link), keep_email=False)
      return

    # Check whether we should include a token.
    if app_id:
      logging.debug("Got request from %s, adding token." % (app_id))

      # Generate a new token that we can use to verify that this user is logged
      # in.
      token = UserToken(user.get_id(), app_id)
      token.save()
      query_str = urllib.urlencode({"token": token.token})
      return_url = "%s?%s" % (return_url, query_str)

    self.redirect(str(return_url))

  """ Shows the page with an error message if the login failed.
  message: Optional means to explicitly specify the message to show.
  keep_email: Whether to keep the email showing. """
  def __show_error(self, message=None, keep_email=True):
    email = self.request.get("email")
    return_url = self.request.get("return_url")

    show_email = ""
    forgot_password=False
    if not message:
      message = "Invalid login."
      forgot_password=True
    if keep_email:
      show_email = email

    response = self.render("templates/login.html", return_url=return_url,
                           message=message, email=show_email,
                           forgot_password=forgot_password)

    self.response.set_status(401)
    self.response.out.write(response)


""" Handles logging a user out. """
class LogoutHandler(ApiHandlerBase, ProjectHandler):
  """ Request Parameters:
  url: A URL to send the user to after they have been logged out. Defaults to
  the home page.
  If we are logging a user out from an external domain, then we also need the
  following parameters: (This condition is detected by whether the app_id
  parameter is present.)
  app_id: The App ID of the app we are logging the user out from.
  user: The unique ID of the user to log out.
  token: The token corresponding for this user. """
  def get(self):
    return_url = self.request.get("url", "/")
    app_id = self.request.get("app_id")

    if not app_id:
      self.auth.unset_session()
    else:
      # If we are from another domain, we actually want to delete a different
      # token.
      user, token = self._get_parameters("user", "token")
      key = "%s.%s.%s" % (user, app_id, token)
      logging.debug("Deleting token: %s" % (key))
      memcache.delete(key)

    self.redirect(str(return_url))


""" Handles sending a password reset email. """
class ForgottenPasswordHandler(ProjectHandler):
  """ Parameters:
  email: The email to send the password reset message to. """
  def post(self):
    email = self.request.get("email")
    if not email:
      logging.warning("Password reset without email parameter?")
      return

    member = Membership.get_by_email(email)
    token = member.create_password_reset_token()

    # Create the reset URL.
    url_parts = urlparse(self.request.url)
    query_str = urllib.urlencode({"user": member.hash, "token": token})
    reset_url = "%s://%s/reset_password?%s" % \
        (url_parts.scheme, url_parts.netloc, query_str)
    logging.debug("Created password reset URL %s for user %s." % \
                  (reset_url, member.email))

    # Send the email.
    body = self.render("templates/password_reset_email.txt", member=member,
                       reset_url=reset_url)
    html_body = self.render("templates/password_reset_email.html",
                            member=member, reset_url=reset_url)
    mail.send_mail(sender=Config().EMAIL_FROM, to=member.email,
                   subject="Hacker Dojo Password Reset", body=body,
                   html=html_body)

""" Handles resetting a password. Most people get here by clicking a link in a
password reset email. """
class PasswordResetHandler(ProjectHandler):
  def get(self):
    user_hash = self.request.get("user")
    token = self.request.get("token")

    error_response = self.render("templates/error.html",
        message="Invalid password reset link.")

    if (not user_hash or not token):
      logging.error("Missing hash or token.")
      self.response.out.write(error_response)
      self.response.set_status(400)
      return

    member = Membership.get_by_hash(user_hash)
    if not member:
      logging.error("Could not find member with hash '%s'." % (user_hash))
      self.response.out.write(error_response)
      self.response.set_status(422)
      return

    logging.info("Resetting password for user %s." % (member.email))
    if not member.verify_password_reset_token(token):
      logging.error("Invalid token: %s" % (token))
      self.response.out.write(error_response)
      self.response.set_status(422)
      return

    # Have them type in their new password.
    response = self.render("templates/password_reset.html")
    self.response.out.write(response)

  def post(self):
    password = self.request.get("password")
    user_hash = self.request.get("user")
    token = self.request.get("token")

    # Check that we still have a valid token.
    user = Membership.get_by_hash(user_hash)
    if not user.verify_password_reset_token(token):
      self.abort(401)
      return

    # Change the user's password.
    user.set_password(password)
    logging.info("Reset password for %s." % (user.email))

    # Remove the password reset token.
    user.password_reset_token = None
    user.put()

    response = self.render("templates/password_reset.html", done=True)
    self.response.out.write(response)


""" Checks that an authentication token is valid. This is meant to be used by
other domains who want to authenticate users. The tokens that they should use
are the ones that they receive from /login. """
class ValidateTokenHandler(ApiHandlerBase):
  """ Validates a token.
  Request parameters:
  user: The unique user ID for the user that this token belongs to.
  token: The actual token to validate.
  Response:
  valid: Whether or not the token is valid. """
  @ApiHandlerBase.restricted
  def post(self):
    user_id, token = self._get_parameters("user", "token")
    if not token:
      return

    app_id = self.request.headers.get("X-Appengine-Inbound-Appid", None)

    # Check that the token exists.
    remembered_token = UserToken.verify(user_id, app_id, token)

    if remembered_token:
      # The token was verified sucessfully.
      logging.info("Verified token for user %s from app %s." % \
                   (user_id, app_id))
      response = {"valid": True}
    else:
      # The token is invalid.
      logging.warning("Invalid token: %s.%s.%s." % (user_id, app_id, token))
      response = {"valid": False}

    self.response.out.write(json.dumps(response))
