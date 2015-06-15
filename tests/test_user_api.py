""" Tests for the user API. """


# We need our external modules.
import appengine_config

import json
import unittest
import urllib

import webtest

from google.appengine.ext import db
from google.appengine.ext import testbed

from keymaster import Keymaster
from membership import Membership
from plans import Plan
import user_api


""" Common superclass for all API tests. """
class ApiTest(unittest.TestCase):
  def setUp(self):
    # Set up testing for application.
    self.test_app = webtest.TestApp(user_api.app)

    # Set up datastore for testing.
    self.testbed = testbed.Testbed()
    self.testbed.activate()
    self.testbed.init_datastore_v3_stub()

    # Create a new plan for testing.
    Plan.all_plans = []
    self.test_plan = Plan("test", 1, 100, "A test plan.", signin_limit=10)

    # Add a user to the datastore.
    self.user = Membership(first_name="Daniel", last_name="Petti",
        email="djpetti@gmail.com", plan="test", username="daniel.petti",
        status="active")
    self.user.put()

  def tearDown(self):
    self.testbed.deactivate()


""" Tests that UserHandler works properly. """
class UserHandlerTest(ApiTest):
  """ Tests that a valid request to get a user works. """
  def test_valid_user_request(self):
    query = urllib.urlencode({"username": "daniel.petti",
        "properties[]": ["first_name", "last_name"]}, True)
    response = self.test_app.get("/api/v1/user?" + query)
    result = json.loads(response.body)

    self.assertEqual(200, response.status_int)
    self.assertEqual(result["first_name"], "Daniel")
    self.assertEqual(result["last_name"], "Petti")
    self.assertEqual(2, len(result.keys()))

  """ Tests that a malformed request throws a 400 error. """
  def test_bad_request(self):
    query = urllib.urlencode({"foo": "blah"})
    response = self.test_app.get("/api/v1/user?" + query, expect_errors=True)
    result = json.loads(response.body)

    self.assertEqual(400, response.status_int)
    self.assertEqual("InvalidParametersException", result["type"])

  """ Tests that it fails when we give it a nonexistent username. """
  def test_bad_username(self):
    query = urllib.urlencode({"username": "bad.name",
        "properties[]": ["first_name", "last_name"]}, True)
    response = self.test_app.get("/api/v1/user?" + query, expect_errors=True)
    result = json.loads(response.body)

    self.assertEqual(422, response.status_int)
    self.assertEqual("InvalidParametersException", result["type"])
    self.assertIn("username", result["message"])

  """ Tests that it fails when we give it bad parameters. """
  def test_bad_parameters(self):
    query = urllib.urlencode({"username": "daniel.petti",
        "properties[]": ["bad_property"]}, True)
    response = self.test_app.get("/api/v1/user?" + query, expect_errors=True)
    result = json.loads(response.body)

    self.assertEqual(422, response.status_int)
    self.assertEqual("InvalidParametersException", result["type"])
    self.assertIn("bad_property", result["message"])

  """ Tests that it functions properly if you give it a single property. """
  def test_singleton_property(self):
    query = urllib.urlencode({"username": "daniel.petti",
        "properties": "first_name"})
    response = self.test_app.get("/api/v1/user?" + query)
    result = json.loads(response.body)

    self.assertEqual(200, response.status_int)
    self.assertEqual("Daniel", result["first_name"])


""" Tests that the signin handler works properly. """
class SigninHandlerTest(ApiTest):
  def setUp(self):
    super(SigninHandlerTest, self).setUp()

    # Reset user signins.
    self.user.signins = 0
    self.user.put()

  """ Tests that signing in a normal user works properly. """
  def test_signin(self):
    params = {"email": "djpetti@gmail.com"}
    response = self.test_app.post("/api/v1/signin", params)
    result = json.loads(response.body)

    self.assertEqual(9, result["visits_remaining"])

    # Check that our user signing in got recorded.
    user = Membership.get_by_email("djpetti@gmail.com")
    self.assertEqual(1, user.signins)

  """ Tests that it gives us an error if we give it a bad email. """
  def test_bad_email(self):
    params = {"email": "bad_email@gmail.com"}
    response = self.test_app.post("/api/v1/signin", params, expect_errors=True)
    result = json.loads(response.body)

    self.assertEqual(422, response.status_int)
    self.assertIn("Could not find", result["message"])

  """ Tests that it works properly on a plan with no signin limit. """
  def test_unlimited_signins(self):
    self.test_plan.signin_limit = None

    params = {"email": "djpetti@gmail.com"}
    response = self.test_app.post("/api/v1/signin", params)
    result = json.loads(response.body)

    self.assertEqual(None, result["visits_remaining"])

  """ Tests that it doesn't work with a suspended user. """
  def test_suspended_user(self):
    user = Membership.get_by_email("djpetti@gmail.com")
    user.status = "suspended"
    user.put()

    params = {"email": "djpetti@gmail.com"}
    response = self.test_app.post("/api/v1/signin", params, expect_errors=True)
    result = json.loads(response.body)

    self.assertEqual(422, response.status_int)
    self.assertIn("Could not find", result["message"])

  """ Tests that it properly suspends a user when they run out of visits. """
  def test_user_suspending(self):
    user = Membership.get_by_email("djpetti@gmail.com")
    # The next one should suspend us.
    user.signins = 9
    user.put()

    params = {"email": "djpetti@gmail.com"}
    response = self.test_app.post("/api/v1/signin", params)
    result = json.loads(response.body)

    self.assertEqual(200, response.status_int)
    self.assertEqual(0, result["visits_remaining"])

    user = Membership.get_by_email("djpetti@gmail.com")
    self.assertEqual(10, user.signins)
    self.assertEqual("no_visits", user.status)


""" Tests that the RFID handler works properly. """
class RfidHandlerTest(ApiTest):
  def setUp(self):
    super(RfidHandlerTest, self).setUp()

    # Reset user signins.
    self.user.signins = 0
    # Set rfid tag.
    self.user.rfid_tag = "1337"
    self.user.put()

  """ Tests that signing in a normal user with RFID works properly. """
  def test_rfid_signin(self):
    params = {"id": "1337"}
    response = self.test_app.post("/api/v1/rfid", params)
    result = json.loads(response.body)

    self.assertEqual(200, response.status_int)

    self.assertIn("gravatar", result.keys())
    self.assertEqual(9, result["visits_remaining"])
    self.assertEqual(self.user.auto_signin, result["auto_signin"])
    self.assertEqual("%s %s" % (self.user.first_name, self.user.last_name),
                     result["name"])
    self.assertEqual(self.user.username, result["username"])
    self.assertEqual(self.user.email, result["email"])

  """ Tests that it won't sign in a suspended user. """
  def test_suspended_signin(self):
    self.user.status = "suspended"
    self.user.put()

    params = {"id": "1337"}
    response = self.test_app.post("/api/v1/rfid", params, expect_errors=True)

    self.assertEqual(422, response.status_int)

    error = json.loads(response.body)
    self.assertIn("InvalidKey", error["type"])
    self.assertIn("or is suspended", error["message"])

  """ Tests that it won't sign in a nonexistent id. """
  def test_bad_id(self):
    params = {"id": "badid"}
    response = self.test_app.post("/api/v1/rfid", params, expect_errors=True)

    self.assertEqual(422, response.status_int)

    error = json.loads(response.body)
    self.assertIn("InvalidKey", error["type"])
    self.assertIn("or is suspended", error["message"])

  """ Tests that it properly suspends a user when they run out of visits. """
  def test_user_suspending(self):
    user = Membership.get_by_email("djpetti@gmail.com")
    # The next one should suspend us.
    user.signins = 9
    user.rfid_tag = "1337"
    user.put()

    params = {"id": "1337"}
    response = self.test_app.post("/api/v1/rfid", params)
    result = json.loads(response.body)

    self.assertEqual(200, response.status_int)
    self.assertEqual(0, result["visits_remaining"])

    user = Membership.get_by_email("djpetti@gmail.com")
    self.assertEqual(10, user.signins)
    self.assertEqual("no_visits", user.status)


""" Tests that the Maglock handler works properly. """
class MaglockHandlerTest(ApiTest):
  def setUp(self):
    super(MaglockHandlerTest, self).setUp()

    # Reset user signins.
    self.user.signins = 0
    # Set rfid tag.
    self.user.rfid_tag = "1337"
    self.user.put()

    # Add the keymaster key we need.
    Keymaster.encrypt("maglock:key", "notasecret")

  """ Tests that we can get a list under normal circumstances. """
  def test_get_user_list(self):
    response = self.test_app.get("/api/v1/maglock/notasecret")
    self.assertEqual(200, response.status_int)

    users = json.loads(response.body)
    self.assertEqual([{"username": "daniel.petti", "rfid_tag": "1337"}], users)

  """ Tests that giving it a bad key causes an error. """
  def test_bad_key(self):
    response = self.test_app.get("/api/v1/maglock/badkey", expect_errors=True)
    self.assertEqual(401, response.status_int)

    error = json.loads(response.body)
    self.assertEqual("UnauthorizedException", error["type"])

  """ Tests that people who shouldn't get included don't. """
  def test_user_requirements(self):
    # No RFID tag.
    self.user.rfid_tag = None
    self.user.put()

    response = self.test_app.get("/api/v1/maglock/notasecret")
    self.assertEqual(200, response.status_int)
    self.assertEqual([], json.loads(response.body))

    # Not active.
    self.user.rfid_tag = "1337"
    self.user.status = "suspended"
    self.user.put()

    response = self.test_app.get("/api/v1/maglock/notasecret")
    self.assertEqual(200, response.status_int)
    self.assertEqual([], json.loads(response.body))
