""" Tests for main.py. """


# We need our external modules.
import appengine_config

import hashlib
import re
import unittest
import urllib

import webtest

from google.appengine.api import memcache
from google.appengine.ext import db
from google.appengine.ext import testbed

from config import Config
from keymaster import Keymaster
from membership import Membership
from project_handler import ProjectHandler
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
    self.testbed.init_taskqueue_stub()

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
    self.assertNotEqual(None, user.hash)

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


""" AccountHandler is complicated enough that we split the testing accross two
cases. This is a base class that both inherit from. """
class AccountHandlerBase(BaseTest):
  # Parameters that we use for testing post requests.
  _TEST_PARAMS = {"username": "testy.testerson",
                  "password": "notasecret",
                  "password_confirm": "notasecret",
                  "plan": "newfull"}

  def setUp(self):
    super(AccountHandlerBase, self).setUp()

    # Start by putting a user in the datastore.
    user = Membership(first_name="Testy", last_name="Testerson",
                      email="ttesterson@gmail.com", plan=None,
                      status=None, hash="anunlikelyhash")
    user.put()

    self.user_hash = user.hash

    # Clear fake usernames between tests.
    ProjectHandler.clear_usernames()


""" Tests that AccountHandler works. """
class AccountHandlerTest(AccountHandlerBase):
  """ Tests that the get request works. """
  def test_get(self):
    query = urllib.urlencode({"plan": "newhive"})
    response = self.test_app.get("/account/%s?%s" % (self.user_hash, query))
    self.assertEqual(200, response.status_int)
    # Our username should be templated in.
    self.assertIn("testy.testerson", response.body)

    user = Membership.get_by_hash(self.user_hash)
    self.assertEqual("newhive", user.plan)

  """ Tests that it does the right thing when we give it a bad hash. """
  def test_bad_hash(self):
    response = self.test_app.get("/account/" + "notahash", expect_errors=True)
    self.assertEqual(422, response.status_int)

  """ Tests that it handles a duplicate username properly. """
  def test_duplicate_usernames(self):
    ProjectHandler.add_username("testy.testerson")

    # It should use the first part of our email.
    response = self.test_app.get("/account/" + self.user_hash)
    self.assertEqual(200, response.status_int)
    self.assertIn("ttesterson", response.body)


    ProjectHandler.add_username("ttesterson")

    # Now it should add a "1" to the end.
    response = self.test_app.get("/account/" + self.user_hash)
    self.assertEqual(200, response.status_int)
    self.assertIn("ttesterson1", response.body)

    ProjectHandler.add_username("ttesterson1")

    # And we can just keep on counting...
    response = self.test_app.get("/account/" + self.user_hash)
    self.assertEqual(200, response.status_int)
    self.assertIn("ttesterson2", response.body)

  """ Tests that a post request works correctly. """
  def test_post(self):
    query = urllib.urlencode(self._TEST_PARAMS)
    response = self.test_app.post("/account/" + self.user_hash, query)
    self.assertEqual(302, response.status_int)

    user = Membership.get_by_hash(self.user_hash)

    # We should be redirected to a personal spreedly page.
    self.assertIn("spreedly.com", response.location)
    self.assertIn(Config().PLAN_IDS["newfull"], response.location)
    self.assertIn(str(user.key().id()), response.location)
    self.assertIn("testy.testerson", response.location)

    # It should have put stuff in the memcache.
    key = hashlib.sha1(self.user_hash + Config().SPREEDLY_APIKEY).hexdigest()
    user_data = memcache.get(key)
    self.assertEqual("testy.testerson:notasecret", user_data)

  """ Tests that it fails if the required fields are invalid. """
  def test_requirements(self):
    # Giving it passwords that don't match should be a problem.
    params = self._TEST_PARAMS.copy()
    params["password"] = "notasecret"
    params["password_confirm"] = "stillnotasecret"
    query = urllib.urlencode(params)
    response = self.test_app.post("/account/" + self.user_hash, query,
                                  expect_errors=True)

    self.assertEqual(422, response.status_int)
    self.assertIn("do not match", response.body)

    # Giving it a password that is too short should also be a problem.
    params = self._TEST_PARAMS.copy()
    params["password"] = "daniel"
    params["password_confirm"] = "daniel"
    query = urllib.urlencode(params)
    response = self.test_app.post("/account/" + self.user_hash, query,
                                  expect_errors=True)

    self.assertEqual(422, response.status_int)
    self.assertIn("at least 8 characters", response.body)

    user = Membership.get_by_hash(self.user_hash)
    user.username = "testy.testerson"
    user.put()

    # If there is already a username associated with this user, we should fail
    # as well.
    query = urllib.urlencode(self._TEST_PARAMS)
    response = self.test_app.post("/account/" + self.user_hash, query,
                                  expect_errors=True)

    self.assertEqual(422, response.status_int)
    self.assertIn("already have an account", response.body)

  """ Checks that it redirects correctly if we the user is already active. """
  def test_already_active(self):
    user = Membership.get_by_hash(self.user_hash)
    user.status = "active"
    user.put()

    query = urllib.urlencode(self._TEST_PARAMS)
    response = self.test_app.post("/account/" + self.user_hash, query)

    self.assertEqual(302, response.status_int)
    self.assertIn("success", response.location)
    self.assertIn(self.user_hash, response.location)


""" A special test case for testing the giftcard stuff. """
class GiftCodeTest(AccountHandlerBase):
  def setUp(self):
    super(GiftCodeTest, self).setUp()

    # Create the a keymaster key for a valid code.
    self.code = "eulalie"
    Keymaster.encrypt("code:hash", self.code)

  """ Tests that if we give it a correct code, it gives us a discount, and that
  if we give it twice, it doesn't. """
  def test_discount(self):
    # A unique number on all the giftcards.
    serial = "1678"
    # A "correct" hash, based on what the actual code does.
    correct_hash = hashlib.sha1(serial + self.code).hexdigest()
    correct_hash = re.sub("[a-f]", "", correct_hash)[:8]
    gift_code = "1337" + serial + correct_hash
    print "Using test gift code: %s" % (gift_code)

    # Now try using this code.
    user = Membership.get_by_hash(self.user_hash)
    user.referrer = gift_code
    user.put()

    response = self.test_app.post("/account/" + self.user_hash,
                                  self._TEST_PARAMS)
    self.assertEqual(302, response.status_int)

    # We should have a record of the used code.
    codes = main.UsedCode.all().run()
    for code in codes:
      # We should only have one code in there.
      self.assertEqual(gift_code, code.code)
      self.assertEqual("ttesterson@gmail.com", code.email)
      self.assertEqual("OK", code.extra)

    # Try to use the same code again.
    response = self.test_app.post("/account/" + self.user_hash,
                                  self._TEST_PARAMS, expect_errors=True)
    self.assertEqual(422, response.status_int)
    self.assertIn("already been used", response.body)

    # Now we should have individual records of the same code being used twice.
    codes = main.UsedCode.all().run()
    # Turn the iterator into a list.
    codes = [code for code in codes]

    self.assertEqual(gift_code, codes[0].code)
    self.assertEqual(gift_code, codes[1].code)
    self.assertEqual("ttesterson@gmail.com", codes[0].email)
    self.assertEqual("ttesterson@gmail.com", codes[1].email)
    if codes[0].extra == "OK":
      # The other one should be the duplicate.
      self.assertEqual("2nd+ attempt", codes[1].extra)
    elif codes[0].extra == "2nd+ attempt":
      # The other one should be the good one.
      self.assertEqual("OK", codes[1].extra)
    else:
      fail("Got unexpected extra '%s'." % (codes[0].extra))

  """ Tests that it fails when we give it a code that is the wrong length. """
  def test_bad_length_code(self):
    code = "133712345"

    user = Membership.get_by_hash(self.user_hash)
    user.referrer = code
    user.put()

    response = self.test_app.post("/account/" + self.user_hash,
                                  self._TEST_PARAMS, expect_errors=True)
    self.assertEqual(422, response.status_int)
    self.assertIn("must be 16 digits", response.body)

  """ Tests that it fails when we give it a code that is invalid. """
  def test_invalid_code(self):
    code = "1337424242424242"

    user = Membership.get_by_hash(self.user_hash)
    user.referrer = code
    user.put()

    response = self.test_app.post("/account/" + self.user_hash,
                                  self._TEST_PARAMS, expect_errors=True)
    self.assertEqual(422, response.status_int)
    self.assertIn("code was invalid", response.body)
