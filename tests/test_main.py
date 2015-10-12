""" Tests for main.py. """


# We need our external modules.
import appengine_config

import hashlib
import json
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
    self.assertIn("value=\"choose\"", response.body)

    # If we give it a plan that is not available, it should show us an error.
    unavailable_plan = Plan("test_plan", 1, 100, "A test plan.",
                            admin_only=True)
    query = urllib.urlencode({"plan": unavailable_plan.name})
    response = self.test_app.get("/?" + query, expect_errors=True)
    self.assertEqual(422, response.status_int)
    self.assertIn(unavailable_plan.name, response.body)
    self.assertIn("is not available", response.body)

  """ Tests that the plan gets written through even when we rerender the
  template. """
  def test_pass_plan_on_error(self):
    params = self._TEST_PARAMS.copy()
    params["plan"] = "newfull"

    # Remove required parameters one by one.
    del params["first_name"]
    response = self.test_app.post("/", params, expect_errors=True)
    # Make sure the plan stayed in there.
    self.assertIn("value=\"newfull\"", response.body)
    params["first_name"] = self._TEST_PARAMS["first_name"]

    del params["last_name"]
    response = self.test_app.post("/", params, expect_errors=True)
    self.assertIn("value=\"newfull\"", response.body)
    params["last_name"] = self._TEST_PARAMS["last_name"]

    del params["email"]
    response = self.test_app.post("/", params, expect_errors=True)
    self.assertIn("value=\"newfull\"", response.body)
    params["email"] = self._TEST_PARAMS["email"]

  """ Tests that it takes us directly to PinPayments if we've already set up our
  account. """
  def test_skip_if_account(self):
    plan = Plan("test", 0, 100, "This is a test plan.")

    existing_user = Membership(first_name=self._TEST_PARAMS["first_name"],
                               last_name=self._TEST_PARAMS["last_name"],
                               email=self._TEST_PARAMS["email"],
                               spreedly_token=None,
                               username="testy.testerson",
                               password="notasecret",
                               plan=plan.name)
    existing_user.put()

    response = self.test_app.post("/", self._TEST_PARAMS)
    self.assertEqual(302, response.status_int)

    self.assertIn("subs.pinpayments.com", response.location)
    self.assertIn(plan.plan_id, response.location)
    self.assertIn(existing_user.username, response.location)
    self.assertNotIn(existing_user.password, response.location)


""" AccountHandler is complicated enough that we split the testing accross two
cases. This is a base class that both inherit from. """
class AccountHandlerBase(BaseTest):
  # Parameters that we use for testing post requests.
  _TEST_PARAMS = {"username": "testy.testerson",
                  "password": "notasecret",
                  "password_confirm": "notasecret",
                  "plan": "test"}

  def setUp(self):
    super(AccountHandlerBase, self).setUp()

    # Start by putting a user in the datastore.
    user = Membership(first_name="Testy", last_name="Testerson",
                      email="ttesterson@gmail.com", plan=None,
                      status=None, hash="anunlikelyhash")
    user.put()

    self.user_hash = user.hash

    # Add the plans we need.
    Plan.all_plans = []
    Plan.legacy_pairs = set()
    self.test_plan = Plan("test", 0, 100, "A test plan.")

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
    self.assertIn("subs.pinpayments.com", response.location)
    self.assertIn(self.test_plan.plan_id, response.location)
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
    # The plan should be in there correctly.
    self.assertIn("value=\"test\"", response.body)

    # Giving it a password that is too short should also be a problem.
    params = self._TEST_PARAMS.copy()
    params["password"] = "daniel"
    params["password_confirm"] = "daniel"
    query = urllib.urlencode(params)
    response = self.test_app.post("/account/" + self.user_hash, query,
                                  expect_errors=True)

    self.assertEqual(422, response.status_int)
    self.assertIn("at least 8 characters", response.body)
    self.assertIn("value=\"test\"", response.body)

    user = Membership.get_by_hash(self.user_hash)
    user.domain_user = True
    user.put()

    # If there is already a domain account associated with this user, we should
    # fail as well.
    query = urllib.urlencode(self._TEST_PARAMS)
    response = self.test_app.post("/account/" + self.user_hash, query,
                                  expect_errors=True)

    self.assertEqual(422, response.status_int)
    self.assertIn("already have an account", response.body)
    self.assertIn("value=\"test\"", response.body)

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

  """ Checks that it redirects correctly if the user has already entered their
  account information. """
  def test_already_entered(self):
    user = Membership.get_by_hash(self.user_hash)
    user.username = "testy.testerson"
    user.password = "notasecret"
    user.spreedly_token = None
    user.put()

    response = self.test_app.get("/account/" + self.user_hash,
                                 self._TEST_PARAMS)

    # We should be redirected to a personal spreedly page.
    self.assertEqual(302, response.status_int)
    self.assertIn("subs.pinpayments.com", response.location)
    self.assertIn(self.test_plan.plan_id, response.location)
    self.assertIn(str(user.key().id()), response.location)
    self.assertIn("testy.testerson", response.location)


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


""" Base class for testing plan selection handlers. """
class PlanSelectionTestBase(BaseTest):
  def setUp(self):
    super(PlanSelectionTestBase, self).setUp()

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


""" Tests that the plan selector page works. """
class SelectPlanHandlerTest(PlanSelectionTestBase):
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


""" Tests that the plan change page works. """
class ChangePlanHandlerTest(PlanSelectionTestBase):
  def setUp(self):
    super(ChangePlanHandlerTest, self).setUp()

    # Add a user to test with.
    self.user = Membership(first_name="Testy", last_name="Testerson",
                           email="ttesterson@gmail.com", plan="plan1",
                           spreedly_token="notatoken",
                           username="testy.testerson")
    self.user.put()

    # Login our test user.
    self.testbed.init_user_stub()
    self.testbed.setup_env(user_email="ttesterson@gmail.com", overwrite=True)

  """ Tests that the plan selection page looks normal. """
  def __check_page(self):
    response = self.test_app.get("/change_plan")
    self.assertEqual(200, response.status_int)

    # It should show the human name, and the link. (The plan ID should be in the
    # spreedly subscribe url.)
    self.assertIn(self.plan1.human_name, response.body)
    self.assertIn("subscribe/" + self.plan1.plan_id, response.body)
    self.assertIn(self.plan2.human_name, response.body)
    self.assertIn("subscribe/" + self.plan2.plan_id, response.body)
    # Not selectable, so it shouldn't be in there at all.
    self.assertNotIn(self.plan3.human_name, response.body)
    self.assertNotIn("subscribe/" + self.plan3.plan_id, response.body)
    # Unavailable, so the name should be there, but the link should not.
    self.assertIn(self.plan4.human_name, response.body)
    self.assertNotIn("subscribe/" + self.plan4.plan_id, response.body)

    # It should also show the price.
    self.assertIn("$%d" % (self.plan1.price_per_month), response.body)
    self.assertIn("$%d" % (self.plan2.price_per_month), response.body)
    self.assertNotIn("$%d" % (self.plan3.price_per_month), response.body)
    self.assertIn("$%d" % (self.plan4.price_per_month), response.body)

  """ Tests that the plans end up getting shown correctly. """
  def test_plan_page(self):
    self.__check_page()

  """ Tests that it responds properly when the user has no spreedly token. """
  def test_no_spreedly_token(self):
    self.user.spreedly_token = None
    self.user.put()

    response = self.test_app.get("/change_plan", expect_errors=True)
    self.assertEqual(422, response.status_int)
    self.assertIn("any plan", response.body)

  """ Tests that it deals with using the hackerdojo email properly. """
  def test_hackerdojo_email(self):
    self.testbed.setup_env(user_email="testy.testerson@hackerdojo.com",
                           overwrite=True)

    self.__check_page()

  """ Tests that it responds properly when an invalid person logs in. """
  def test_invalid_email(self):
    self.testbed.setup_env(user_email="bad_email@gmail.com", overwrite=True)

    response = self.test_app.get("/change_plan", expect_errors=True)
    self.assertEqual(422, response.status_int)
    self.assertIn("your email", response.body)


""" The ReactivatePlan handler is very closely related to the ChangePlan one,
however, there are some key differences which are worth testing. """
class ReactivatePlanHandlerTest(PlanSelectionTestBase):
  def setUp(self):
    super(ReactivatePlanHandlerTest, self).setUp()

    # Add a user to test with.
    self.user = Membership(first_name="Testy", last_name="Testerson",
                           email="ttesterson@gmail.com", plan="plan1",
                           spreedly_token="notatoken", hash="notahash",
                           username="testy.testerson")
    self.user.put()

  """ Tests that the page works properly when we give it the right things. """
  def test_get(self):
    response = self.test_app.get("/reactivate_plan/%s" % (self.user.hash))
    self.assertEqual(200, response.status_int)

  """ Tests that it fails when we give it a bad hash. """
  def test_bad_hash(self):
    response = self.test_app.get("/reactivate_plan/badhash", expect_errors=True)
    self.assertEqual(422, response.status_int)
    self.assertIn("Invalid reactivation link", response.body)


""" Tests that the MemberListHandler works as expected. All the other list
handlers work in an identical way, in fact, they share almost all their code.
That, combined with the fact that these tests take awhile to run, mean that we
only test the Memberlist version and assume that everything else will work the
same way. """
class MemberListHandlerTest(BaseTest):
  def setUp(self):
    super(MemberListHandlerTest, self).setUp()

    # This handler requires admin access all the time, so give ourselves that
    # right off the bat.
    self.testbed.setup_env(user_email="ttesterson@gmail.com", user_is_admin="1",
                           overwrite=True)

    # Make exactly two pages worth of users.
    for i in range(0, 50):
       email = "ttesterson%d@gmail.com" % (i)
       first_name = "Testy%d" % (i)
       user = Membership.create_user(email, "notasecret",
                                     first_name=first_name,
                                     last_name="Testerson",
                                     status="active")

  """ Tests that a standard request gives us the shell template. """
  def test_get(self):
    response = self.test_app.get("/memberlist")
    self.assertEqual(200, response.status_int)

    # There should be no table in there.
    self.assertNotIn("</table>", response.body)

  """ Tests that we can successfully get a count of all the pages. """
  def test_count(self):
    response = self.test_app.get("/memberlist/total_pages")
    self.assertEqual(200, response.status_int)

    self.assertEqual(2, int(response.body))

  """ Tests that we can fetch pages with cursors. """
  def test_pagination(self):
    # Fetch the initial page.
    query_str = urllib.urlencode({"page": "start"})
    response = self.test_app.get("/memberlist?" + query_str)
    self.assertEqual(200, response.status_int)

    response = json.loads(response.body)
    self.assertIn("nextPage", response.keys())
    self.assertIn("html", response.keys())
    self.assertIn("</table>", response["html"])

    # Fetch the next page.
    query_str = urllib.urlencode({"page": response["nextPage"]})
    new_response = self.test_app.get("/memberlist?" + query_str)
    self.assertEqual(200, new_response.status_int)

    new_response = json.loads(new_response.body)
    self.assertIn("nextPage", new_response.keys())
    self.assertIn("html", new_response.keys())
    self.assertIn("</table>", new_response["html"])

    self.assertNotEqual(response["nextPage"], new_response["nextPage"])
    self.assertNotEqual(response["html"], new_response["html"])
