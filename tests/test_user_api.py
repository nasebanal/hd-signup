""" Tests for the user API. """


# We need our external modules.
import appengine_config

import json
import unittest
import urllib

import webtest

from google.appengine.ext import db
from google.appengine.ext import testbed

from membership import Membership
import user_api


""" Tests that UserHandler works properly. """
class UserHandlerTest(unittest.TestCase):
  def setUp(self):
    # Set up testing for application.
    self.test_app = webtest.TestApp(user_api.app)

    # Set up datastore for testing.
    self.testbed = testbed.Testbed()
    self.testbed.activate()
    self.testbed.init_datastore_v3_stub()

    # Add a user to the datastore.
    user = Membership(first_name="Daniel", last_name="Petti",
        email="djpetti@gmail.com", plan="newfull", username="daniel.petti")
    user.put()

  def tearDown(self):
    self.testbed.deactivate()

  """ Tests that a valid request to get a user works. """
  def test_valid_user_request(self):
    query = urllib.urlencode({"username": "daniel.petti",
        "properties[]": ["first_name", "last_name"]}, True)
    response = self.test_app.get("/api/v1/user?" + query)
    result = json.loads(response.body)

    self.assertEqual("200 OK", response.status)
    self.assertEqual(result["first_name"], "Daniel")
    self.assertEqual(result["last_name"], "Petti")
    self.assertEqual(2, len(result.keys()))

  """ Tests that a malformed request throws a 400 error. """
  def test_bad_request(self):
    query = urllib.urlencode({"foo": "blah"})
    response = self.test_app.get("/api/v1/user?" + query, expect_errors=True)
    result = json.loads(response.body)

    self.assertEqual("400 Bad Request", response.status)
    self.assertEqual("InvalidParametersException", result["type"])

  """ Tests that it fails when we give it a nonexistent username. """
  def test_bad_username(self):
    query = urllib.urlencode({"username": "bad.name",
        "properties[]": ["first_name", "last_name"]}, True)
    response = self.test_app.get("/api/v1/user?" + query, expect_errors=True)
    result = json.loads(response.body)

    self.assertEqual("422 Unprocessable Entity", response.status)
    self.assertEqual("InvalidParametersException", result["type"])
    self.assertIn("username", result["message"])

  """ Tests that it fails when we give it bad parameters. """
  def test_bad_parameters(self):
    query = urllib.urlencode({"username": "daniel.petti",
        "properties[]": ["bad_property"]}, True)
    response = self.test_app.get("/api/v1/user?" + query, expect_errors=True)
    result = json.loads(response.body)

    self.assertEqual("422 Unprocessable Entity", response.status)
    self.assertEqual("InvalidParametersException", result["type"])
    self.assertIn("bad_property", result["message"])
