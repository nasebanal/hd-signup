""" Tests for the login functionality. """

# We need our externals.
import appengine_config

import cPickle as pickle
import unittest
import urllib

from google.appengine.ext import testbed

import webtest

from membership import Membership
import login
import main


""" A base test class that sets everything up correctly. """
class BaseTest(unittest.TestCase):
  def setUp(self):
    # Set up testing for application.
    self.test_app = webtest.TestApp(main.app)

    # Set up datastore for testing.
    self.testbed = testbed.Testbed()
    self.testbed.activate()
    self.testbed.init_datastore_v3_stub()
    self.testbed.init_memcache_stub()
    self.testbed.init_mail_stub()

  def tearDown(self):
    self.testbed.deactivate()


""" Tests that LoginHandler works. """
class LoginHandlerTest(BaseTest):
  def setUp(self):
    super(LoginHandlerTest, self).setUp()

    # Make a user to test logging in.
    self.member = Membership.create_user("testy.testerson@gmail.com", "notasecret",
                                    first_name="Testy", last_name="Testerson",
                                    hash="notahash", status="active")

    # Testing parameters for logging in.
    self.params = {"email": self.member.email, "password": "notasecret"}

  """ Tests that we can log in successfully. """
  def test_login(self):
    response = self.test_app.post("/login", self.params)
    self.assertEqual(302, response.status_int)
    # Without a return URL, we should have redirected to the main page.
    self.assertEqual("http://localhost/", response.location)

  """ Tests that we can give it a return URL and it will send us there. """
  def test_return_url(self):
    query_str = urllib.urlencode({"url": "http://www.google.com"})
    response = self.test_app.get("/login?" + query_str)
    self.assertEqual(200, response.status_int)
    self.assertIn("http://www.google.com", response.body)

    params = self.params.copy()
    params["url"] = "http://www.google.com"
    response = self.test_app.post("/login", params)
    self.assertEqual(302, response.status_int)
    self.assertEqual("http://www.google.com", response.location)

  """ Tests that it responds properly when we give it a bad email. """
  def test_bad_email(self):
    params = self.params.copy()
    params["email"] = "bademail@gmail.com"
    response = self.test_app.post("/login", params, expect_errors=True)
    self.assertEqual(401, response.status_int)

    self.assertIn("not found", response.body)

  """ Tests that it responds properly when we give it a bad password. """
  def test_bad_password(self):
    params = self.params.copy()
    params["password"] = "badpassword"
    response = self.test_app.post("/login", params, expect_errors=True)
    self.assertEqual(401, response.status_int)

    self.assertIn("is incorrect", response.body)

  """ Tests that it doesn't let the user log in if they are suspended or have no
  status. """
  def test_bad_status(self):
    self.member.status = None
    self.member.put()

    response = self.test_app.post("/login", self.params, expect_errors=True)
    self.assertEqual(401, response.status_int)
    self.assertIn("not finished", response.body)

    self.member.status = "suspended"
    self.member.put()

    response = self.test_app.post("/login", self.params, expect_errors=True)
    self.assertEqual(401, response.status_int)
    self.assertIn("reactivate", response.body)


""" Tests that LogoutHandler works. """
class LogoutHandlerTest(BaseTest):
  """ Tests that we can logout without it blowing up. """
  def test_get(self):
    response = self.test_app.get("/logout")
    self.assertEqual(302, response.status_int)
    # Without a return URL, we should have redirected to the main page.
    self.assertEqual("http://localhost/", response.location)

  """ Tests that we can give it a return URL and it will send us there. """
  def test_return_url(self):
    query_str = urllib.urlencode({"url": "http://www.google.com"})
    response = self.test_app.get("/logout?" + query_str)
    self.assertEqual(302, response.status_int)
    self.assertEqual("http://www.google.com", response.location)

""" Tests that we can reset our password successfully. """
class ForgottenPasswordHandlerTest(BaseTest):
  def setUp(self):
    super(ForgottenPasswordHandlerTest, self).setUp()

    self.mail_stub = self.testbed.get_stub(testbed.MAIL_SERVICE_NAME)
    # Make a user to test with.
    self.member = Membership.create_user("testy.testerson@gmail.com",
        "notasecret", first_name="Testy", last_name="Testerson",
        hash="notahash")

    # Default parameters for test request.
    self.params = {"email": self.member.email}

  """ Tests that we can request a password reset. """
  def test_post(self):
    response = self.test_app.post("/forgot_password", self.params)
    self.assertEqual(200, response.status_int)

    # Check that the user has a token.
    member = Membership.get_by_id(self.member.key().id())
    self.assertNotEqual(None, member.password_reset_token)

    # Check that we got an email with the link.
    messages = self.mail_stub.get_sent_messages(to=member.email)
    self.assertEqual(1, len(messages))
    body = str(messages[0].body)
    token = pickle.loads(str(member.password_reset_token)).token
    self.assertIn(token, body)
    self.assertIn(str(member.hash), body)

  """ Tests that it uses the same token if we tell it to reset the password
  multiple times. """
  def test_reused_token(self):
    response = self.test_app.post("/forgot_password", self.params)
    self.assertEqual(200, response.status_int)

    member = Membership.get_by_id(self.member.key().id())
    token = pickle.loads(str(member.password_reset_token)).token

    response = self.test_app.post("/forgot_password", self.params)
    self.assertEqual(200, response.status_int)

    member = Membership.get_by_id(self.member.key().id())
    new_token = pickle.loads(str(member.password_reset_token)).token

    self.assertEqual(token, new_token)


class PasswordResetHandlerTest(BaseTest):
  def setUp(self):
    super(PasswordResetHandlerTest, self).setUp()

    # Make a user to test with.
    self.member = Membership.create_user("testy.testerson@gmail.com",
        "notasecret", first_name="Testy", last_name="Testerson",
        hash="notahash")
    self.token = self.member.create_password_reset_token()

    params = {"user": self.member.hash, "token": self.token}
    self.query_str = urllib.urlencode(params)
    self.params = {"password": "notasecret", "verify": "notasecret"}

  """ Tests that we can get to the reset page with a valid link. """
  def test_get(self):
    response = self.test_app.get("/reset_password?" + self.query_str)
    self.assertEqual(200, response.status_int)
    self.assertIn("your password", response.body)

  """ Tests that we can actually reset our password. """
  def test_post(self):
    response = self.test_app.post("/reset_password?" + self.query_str,
                                  self.params)
    self.assertEqual(200, response.status_int)

    self.assertIn("password has been reset", response.body)

    # The password should be changed now.
    member = Membership.get_by_auth_password(self.member.email,
                                             self.params["password"])
    self.assertEqual(self.member.key().id(), member.key().id())

    # The password reset token should be gone.
    self.assertEqual(None, member.password_reset_token)

  """ Tests that it shows an error if it gets an invalid link. """
  def test_errors(self):
    # Try with no parameters.
    response = self.test_app.get("/reset_password", expect_errors=True)
    self.assertEqual(400, response.status_int)

    # Try with a bad user.
    query_str = urllib.urlencode({"user": "baduser", "token": self.token})
    response = self.test_app.get("/reset_password?" + query_str,
                                 expect_errors=True)
    self.assertEqual(422, response.status_int)

    # Try with a bad token.
    query_str = urllib.urlencode({"user": self.member.hash,
                                  "token": "badtoken"})
    response = self.test_app.get("/reset_password?" + query_str,
                                 expect_errors=True)
    self.assertEqual(422, response.status_int)

  """ Tests that it shows an error if it gets a post request with an invalid
  token. """
  def test_post_invalid_token(self):
    query_str = urllib.urlencode({"user": self.member.hash,
                                  "token": "badtoken"})
    response = self.test_app.post("/reset_password?" + query_str, self.params,
                                  expect_errors=True)
    self.assertEqual(401, response.status_int)
