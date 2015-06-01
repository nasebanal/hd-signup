""" Tests for the plans manager. """


import datetime
import unittest

from google.appengine.ext import testbed

from config import Config
from membership import Membership
from plans import Plan


""" Test case for the Plan class """
class PlanTests(unittest.TestCase):
  """ Set up for every test. """
  def setUp(self):
    # Create and activate testbed instance.
    self.testbed = testbed.Testbed()
    self.testbed.activate()
    self.testbed.init_datastore_v3_stub()

    # Clear all the real plans.
    Plan.all_plans = []
    Plan.legacy_pairs.clear()

    # Make some test plans.
    self.plan1 = Plan("plan1", 1, 25, "Test plan 1")
    self.plan2 = Plan("plan2", 2, 50, "Test plan 2",
                      selectable=False)
    self.plan3 = Plan("plan3", 3, 100, "Test plan 3",
                      full=True)
    self.plan4 = Plan("plan4", 4, 75, "Test plan 4",
                      legacy=self.plan1)

  """ Cleanup for every test. """
  def tearDown(self):
    self.testbed.deactivate()

  """ Tests that we can get a list of plans to display on the plan selection
  page. """
  def test_selection_page(self):
    active, hidden = Plan.get_plans_to_show()
    self.assertEqual([self.plan1], active)
    self.assertEqual([self.plan3], hidden)

  """ Tests that setting a member limit works. """
  def test_member_limit(self):
    self.plan1.member_limit = 2

    # Put some people in the datastore.
    user1 = Membership(first_name="Testy1", last_name="Testerson",
                       email="ttesterson1@gmail.com", plan="plan1")
    user2 = Membership(first_name="Testy2", last_name="Testerson",
                       email="ttesterson2@gmail.com", plan="plan1")

    # The plan should not be full initially.
    self.assertFalse(self.plan1.is_full())

    # Adding one user should still not make it full.
    user1.put()
    self.assertFalse(self.plan1.is_full())

    # Adding the other user should make it full.
    user2.put()
    self.assertTrue(self.plan1.is_full())

  """ Tests that the signin limiting works correctly. """
  def test_signin_limit(self):
    self.plan1.signin_limit = 2
    user = Membership(first_name="Testy", last_name="Testerson",
                      email="ttesterson@gmail.com", plan="plan1")
    user.put()

    # We should have all 2 signins left.
    self.assertEqual(2, Plan.signins_remaining(user))

    # Signin once.
    user.signins = 1
    user.put()
    self.assertEqual(1, Plan.signins_remaining(user))

    # Signin again.
    user.signins = 2
    user.put()
    self.assertEqual(0, Plan.signins_remaining(user))

    # Should never be less than zero.
    user.signins = 3
    user.put()
    self.assertEqual(0, Plan.signins_remaining(user))

    # Give ourselves unlimited signins!
    self.plan1.signin_limit = None
    self.assertEqual(None, Plan.signins_remaining(user))

  """ Tests that it correctly detects when we can and can't put people on
  various plans. """
  def test_can_subscribe(self):
    self.assertTrue(Plan.can_subscribe("plan1"))
    self.assertTrue(Plan.can_subscribe("plan2"))
    self.assertFalse(Plan.can_subscribe("plan3"))
    self.assertFalse(Plan.can_subscribe("plan4"))

  """ Tests that it correctly counts members from normal plans and their legacy
  versions together. """
  def test_legacy_pairing(self):
    self.plan1.member_limit = 2

    user1 = Membership(first_name="Testy1", last_name="Testerson",
                       email="ttesterson1@gmail.com", plan="plan1")
    user1.put()
    user2 = Membership(first_name="Testy2", last_name="Testerson",
                       email="ttesterson2@gmail.com", plan="plan4")
    user2.put()

    self.assertTrue(self.plan1.is_full())

  """ Tests that it correctly fails to include members who have been suspended
  for too long when it checks if a plan is full. """
  def test_ignore_long_suspensions(self):
    # Ensure that we have a known value for when we start ignoring plans.
    conf = Config()
    conf.PLAN_USER_IGNORE_THRESHOLD = 30

    self.plan1.member_limit = 1

    user = Membership(first_name="Testy", last_name="Testerson",
                      email="ttesterson@gmail.com", plan="plan1",
                      status="active")
    user.put()

    # Initially, the plan should be full, for every status.
    self.assertTrue(self.plan1.is_full())
    user.status = "suspended"
    user.put()
    self.assertTrue(self.plan1.is_full())
    user.status = None
    user.put()
    self.assertTrue(self.plan1.is_full())

    # If we mess with the updated time, it should be ignored when the plan is
    # not active.
    user.updated = datetime.datetime.now() - datetime.timedelta(days=31)

    user.status = "active"
    user.put(skip_time_update=True)
    self.assertTrue(self.plan1.is_full())
    user.status = "suspended"
    user.put(skip_time_update=True)
    self.assertFalse(self.plan1.is_full())
    user.status = None
    user.put(skip_time_update=True)
    self.assertFalse(self.plan1.is_full())

  """ Tests that plan aliases work as expected. """
  def test_aliases(self):
    self.plan1.aliases = ["alias"]

    plan1 = Plan.get_by_name("alias")
    self.assertEqual(self.plan1, plan1)
