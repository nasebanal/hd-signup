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
from plans import Plan
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
    self.testbed.init_mail_stub()

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

  """ Tests that it behaves correctly when someone gives it a bad plan. """
  def test_bad_plan(self):
    # If we give it a nonexistent plan, it should ignore it.
    query = urllib.urlencode({"plan": "badplan"})
    response = self.test_app.get("/?" + query)
    self.assertEqual(200, response.status_int)
    self.assertIn("value=choose", response.body)

    # If we give it a plan that is not available, it should show us an error.
    unavailable_plan = Plan("test_plan", 1, 100, "A test plan.",
                            admin_only=True)
    query = urllib.urlencode({"plan": unavailable_plan.name})
    response = self.test_app.get("/?" + query, expect_errors=True)
    self.assertEqual(422, response.status_int)
    self.assertIn(unavailable_plan.name, response.body)
    self.assertIn("is not available", response.body)


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

    # The account information should be in the datastore.
    user = Membership.get_by_hash(self.user_hash)
    self.assertEqual("testy.testerson", user.username)
    self.assertEqual("notasecret", user.password)

    # We shouldn't have a domain account yet.
    self.assertFalse(user.domain_user)

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

    user = Membership.get_by_hash(self.user_hash)
    user.username = None
    user.put()

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


""" Tests that CreateUserTask works correctly. """
class CreateUserTaskTest(BaseTest):
  def setUp(self):
    super(CreateUserTaskTest, self).setUp()

    # Add a user to the datastore.
    user = Membership(first_name="Testy", last_name="Testerson",
                      email="ttesterson@gmail.com", hash="notahash",
                      spreedly_token="notatoken", username="testy.testerson",
                      password="notasecret")
    user.put()

    self.mail_stub = self.testbed.get_stub(testbed.MAIL_SERVICE_NAME)
    self.user_hash = user.hash
    self.params = {"hash": self.user_hash, "username": "testy.testerson",
                   "password": "notasecret"}

  """ Tests that it works under normal conditions. """
  def test_create_user(self):
    response = self.test_app.post("/tasks/create_user", self.params)
    self.assertEqual(200, response.status_int)

    # Check that it's sending the right parameters to the domain app.
    self.assertIn("username=testy.testerson", response.body)
    self.assertIn("password=notasecret", response.body)
    self.assertIn("first_name=Testy", response.body)
    self.assertIn("last_name=Testerson", response.body)

    user = Membership.get_by_hash(self.user_hash)
    # Check that the user ended up with a username.
    self.assertEqual("testy.testerson", user.username)
    # Check that domain_user got set.
    self.assertTrue(user.domain_user)
    # Check that the password got cleared.
    self.assertEqual(None, user.password)

    # Check that it sent the right email.
    messages = self.mail_stub.get_sent_messages(to="ttesterson@gmail.com")
    self.assertEqual(1, len(messages))

    # It should give the user this data.
    body = str(messages[0].body)
    self.assertIn(user.username, body)

  """ Tests that it retries if the user has no spreedly token. """
  def test_retry_no_token(self):
    # Make a user with no token.
    user = Membership.get_by_hash(self.user_hash)
    user.spreedly_token=None
    user.put()

    # Try to create an account for this user.
    response = self.test_app.post("/tasks/create_user", self.params)
    self.assertEqual(200, response.status_int)

    # We should have a new task now.
    taskqueue_stub = self.testbed.get_stub(testbed.TASKQUEUE_SERVICE_NAME)
    tasks = taskqueue_stub.GetTasks("default")
    self.assertEqual(1, len(tasks))

    # The user shouldn't have a domain account yet.
    user = Membership.get_by_hash(self.user_hash)
    self.assertFalse(user.domain_user)

  """ Tests that it fails when it gets a bad hash or when the account is already
  created. """
  def test_trivial_failures(self):
    # Give it a bad hash.
    bad_params = {"hash": "badhash"}

    response = self.test_app.post("/tasks/create_user", bad_params,
                                  expect_errors=True)
    self.assertEqual(422, response.status_int)

    # Give it a user with a username already.
    user = Membership.get_by_hash(self.user_hash)
    user.username = "testy.testerson"
    user.put()

    response = self.test_app.post("/tasks/create_user", self.params)
    # This should be okay, because we don't want PinPayments to think it needs
    # to retry the call.
    self.assertEqual(200, response.status_int)


""" Tests that the plan selector page works. """
class PlanSelectionTest(BaseTest):
  def setUp(self):
    super(PlanSelectionTest, self).setUp()

    # Clear all the real plans.
    Plan.all_plans = []

    # Make a couple of plans to test with.
    self.plan1 = Plan("plan1", 1, 101, "", human_name="First Plan")
    self.plan2 = Plan("plan2", 2, 102, "", human_name="Second Plan")
    self.plan3 = Plan("plan3", 3, 103, "", selectable=False,
                      human_name="Third Plan")
    # Will always be full.
    self.plan4 = Plan("plan4", 4, 104, "", member_limit=0,
                      human_name="Fourth Plan")

  """ Tests that the plans end up getting shown correctly. """
  def test_plan_page(self):
    response = self.test_app.get("/plan/notahash")
    self.assertEqual(200, response.status_int)

    # It should show the human name, and the link.
    self.assertIn(self.plan1.human_name, response.body)
    self.assertIn(self.plan1.name, response.body)
    self.assertIn(self.plan2.human_name, response.body)
    self.assertIn(self.plan2.name, response.body)
    # Not selectable, so it shouldn't be in there at all.
    self.assertNotIn(self.plan3.human_name, response.body)
    self.assertNotIn(self.plan3.name, response.body)
    # Unavailable, so the name should be there, but the link should not.
    self.assertIn(self.plan4.human_name, response.body)
    self.assertNotIn(self.plan4.name, response.body)

    # It should also show the price.
    self.assertIn("$%d" % (self.plan1.price_per_month), response.body)
    self.assertIn("$%d" % (self.plan2.price_per_month), response.body)
    self.assertNotIn("$%d" % (self.plan3.price_per_month), response.body)
    self.assertIn("$%d" % (self.plan4.price_per_month), response.body)
