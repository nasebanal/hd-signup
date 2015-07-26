""" These pages provide a simple way to authenticate with new-style accounts.
Usage: Direct a user to the /login page with a redirect URL, it will redirect
after the user has successfully authenticated. To check whether the user has
authenticated, use the /validate_token API endpoint. """


from urlparse import urlparse
import cPickle as pickle
import logging
import urllib

from google.appengine.api import mail

from webapp2_extras import auth

from config import Config
from project_handler import ProjectHandler
from membership import Membership


""" Handles creating a login page and logging a user in. """
class LoginHandler(ProjectHandler):
  """ Parameters:
  url: A URL to send the user to after they have successfully logged in.
  Defaults to the home page. """
  def get(self):
    return_url = self.request.get("url", "/")

    response = self.render("templates/login.html", return_url=return_url)
    self.response.out.write(response)

  def post(self):
    email = self.request.get("email")
    password = self.request.get("password")
    return_url = self.request.get("url", "/")

    # Check the password.
    try:
      user_info = \
          self.auth.get_user_by_password(email, password, remember=True)
      user = Membership.get_by_hash(user_info["hash"])

    except auth.InvalidAuthIdError as e:
      logging.warning("Unknown user: %s." % (email))
      self.__show_error(True, False)
      return
    except auth.InvalidPasswordError as e:
      logging.warning("Invalid password for user %s." % (email))
      self.__show_error(False, True)
      return

    # Check that the user can log in.
    if not user.status:
      self.__show_error(False, False, "You have not finished signing up.")
      return
    elif user.status == "suspended":
      link = "/reactivate"
      self.__show_error(False, False,
          message="You are suspended. <a href=\"%s\">Click here</a>" \
                  " to reactivate." % (link))
      return

    self.redirect(str(return_url))

  """ Shows the page with an error message if the login failed.
  bad_email: True if the email was incorrect.
  bad_password: True if the password was incorrect.
  message: Optional means to explicitly specify the message to show. """
  def __show_error(self, bad_email, bad_password, message=None):
    email = self.request.get("email")
    return_url = self.request.get("return_url")

    show_email = ""
    forgot_password = False
    if (bad_email):
      if not message:
        message = "Email not found."
    elif bad_password:
      # If the email was okay, keep it there.
      if not message:
        message = "Password is incorrect."
      show_email = email
      forgot_password = True

    response = self.render("templates/login.html", return_url=return_url,
                           message=message, email=show_email,
                           forgot_password=forgot_password)

    self.response.set_status(401)
    self.response.out.write(response)


""" Handles logging a user out. """
class LogoutHandler(ProjectHandler):
  """ Parameters:
  url: A URL to send the user to after they have been logged out. Defaults to
  the home page. """
  def get(self):
    return_url = self.request.get("url", "/")

    self.auth.unset_session()
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
    if not member.password_reset_token:
      token = member.create_password_reset_token()
    else:
      logging.info("Using already created password reset token.")
      token = pickle.loads(str(member.password_reset_token)).token

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
