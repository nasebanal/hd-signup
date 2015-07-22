""" Tests for the login functionality. """

# We need our externals.
import appengine_config

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

  def tearDown(self):
    self.testbed.deactivate()


""" Tests that LoginHandler works. """
class LoginHandlerTest(BaseTest):
  def setUp(self):
    super(LoginHandlerTest, self).setUp()

    # Make a user to test logging in.
    member = Membership.create_user("testy.testerson@gmail.com", "notasecret",
                                    first_name="Testy", last_name="Testerson")

    # Testing parameters for logging in.
    self.params = {"email": member.email, "password": "notasecret"}

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
