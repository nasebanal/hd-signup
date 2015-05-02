""" Tests for the user API. """


# We need our external modules.
import appengine_config

import unittest

import webtest

from google.appengine.ext import db
from google.appengine.ext import testbed

from membership import Membership
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

  def tearDown(self):
    self.testbed.deactivate()


""" Tests that MainHandler works. """
class MainHandlerTest(BaseTest):
  # Parameters we use for a test user.
  _TEST_PARAMS = {"first_name": "Testy", "last_name": "Testerson",
                  "twitter": "ttesterson", "email": "testy.testerson@gmail.com",
                  "referrer": "My mom"}


  """ Tests that a get request works without error. """
  def test_get(self):
    response = self.test_app.get("/")

    self.assertIn("Member Signup", response.body)
    # Plan input element, should default to choose.
    self.assertIn("choose", response.body)

  """ Tests that a post request works as expected. """
  def test_post(self):
    response = self.test_app.post("/", self._TEST_PARAMS)
    self.assertEqual(302, response.status_int)

    # It should have put an entry in the datastore.
    user = Membership.get_by_email("testy.testerson@gmail.com")
    self.assertNotEqual(None, user)
    self.assertEqual("Testy", user.first_name)
    self.assertEqual("Testerson", user.last_name)
    self.assertEqual("ttesterson", user.twitter)
    self.assertEqual("My mom", user.referrer)

  """ Tests that post fails when we miss a required field but not when we miss a
  non-required one. """
  def test_requirements(self):
    params = self._TEST_PARAMS.copy()

    # Required fields.
    del params["first_name"]
    response = self.test_app.post("/", params, expect_errors=True)
    self.assertEqual(400, response.status_int)
    self.assertIn("name and email", response.body)

    params["first_name"] = "Testy"
    del params["last_name"]
    response = self.test_app.post("/", params, expect_errors=True)
    self.assertEqual(400, response.status_int)
    self.assertIn("name and email", response.body)

    params["last_name"] = "Testerson"
    del params["email"]
    response = self.test_app.post("/", params, expect_errors=True)
    self.assertEqual(400, response.status_int)
    self.assertIn("name and email", response.body)

    params["email"] = "testy.testerson@gmail.com"

    # Optional fields.
    del params["twitter"]
    response = self.test_app.post("/", params)
    self.assertEqual(302, response.status_int)

    params["twitter"] = "ttesterson"
    del params["referrer"]
    response = self.test_app.post("/", params)
    self.assertEqual(302, response.status_int)

  """ Tests that it handles finding an already existing member correctly. """
  def test_already_existing(self):
    # Make a user in the datastore with the same email, but a different name so
    # we can see whether it overrides.
    existing_user = Membership(first_name="Michael", last_name="Scarn",
                               email=self._TEST_PARAMS["email"],
                               status="active")
    existing_user.put()

    # Because the user is active, it should prohibit us from overriding.
    response = self.test_app.post("/", self._TEST_PARAMS, expect_errors=True)
    self.assertEqual(422, response.status_int)
    self.assertIn("already exists", response.body)

    # User should stay the same.
    user = Membership.get_by_email(self._TEST_PARAMS["email"])
    self.assertEqual("Michael", user.first_name)
    self.assertEqual("Scarn", user.last_name)

    existing_user.status = "suspended"
    existing_user.put()

    # Even though the user is suspended, it should still prohibit us from
    # overriding.
    response = self.test_app.post("/", self._TEST_PARAMS, expect_errors=True)
    self.assertEqual(422, response.status_int)
    self.assertIn("suspended", response.body)

    # User should stay the same.
    user = Membership.get_by_email(self._TEST_PARAMS["email"])
    self.assertEqual("Michael", user.first_name)
    self.assertEqual("Scarn", user.last_name)

    existing_user.status = None
    existing_user.put()

    # Now the user should get silently overriden.
    response = self.test_app.post("/", self._TEST_PARAMS)
    self.assertEqual(302, response.status_int)

    # User should not stay the same.
    user = Membership.get_by_email(self._TEST_PARAMS["email"])
    self.assertEqual(self._TEST_PARAMS["first_name"], user.first_name)
    self.assertEqual(self._TEST_PARAMS["last_name"], user.last_name)

  """ Tests that it passes the plan parameter through when there is one. """
  def test_pass_plan(self):
    # If we have no plan, it should send us to the plan selection page.
    params = self._TEST_PARAMS.copy()
    params["plan"] = "choose"
    response = self.test_app.post("/", params)
    self.assertEqual(302, response.status_int)
    self.assertIn("plan/", response.location)

    # If we have a plan, it should skip the plan selection.
    params["plan"] = "newhive"
    response = self.test_app.post("/", params)
    self.assertEqual(302, response.status_int)
    self.assertIn("account/", response.location)
    self.assertIn("plan=newhive", response.location)
