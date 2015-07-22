""" These pages provide a simple way to authenticate with new-style accounts.
Usage: Direct a user to the /login page with a redirect URL, it will redirect
after the user has successfully authenticated. To check whether the user has
authenticated, use the /validate_token API endpoint. """


import logging

from webapp2_extras import auth

from project_handler import ProjectHandler


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
      self.auth.get_user_by_password(email, password, remember=True)
      self.redirect(return_url)
      return
    except auth.InvalidAuthIdError as e:
      logging.warning("Unknown user: %s. (%s)" % (email, e))
      self.__show_error(True, False)
    except auth.InvalidPasswordError as e:
      logging.warning("Invalid password for user %s. (%s)" % (email, e))
      self.__show_error(False, True)

  """ Shows the page with an error message if the login failed.
  bad_email: True if the email was incorrect.
  bad_password: True if the password was incorrect. """
  def __show_error(self, bad_email, bad_password):
    email = self.request.get("email")
    return_url = self.request.get("return_url")

    if (not bad_email and bad_password):
      # If the email was okay, keep it there.
      response = self.render("templates/login.html", return_url=return_url,
                             email=email, message="Password is incorrect.")
    elif (bad_email):
      response = self.render("templates/login.html", return_url=return_url,
                             message="Email not found.")

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
    self.redirect(return_url)
