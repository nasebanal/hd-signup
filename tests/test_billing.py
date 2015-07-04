""" Tests for billing.py. """


# We need our external modules.
import appengine_config

import unittest

from google.appengine.api import users
from google.appengine.ext import testbed

import webtest

from membership import Membership
import billing
import plans


""" A base test class that sets everything up correctly. """
class BaseTest(unittest.TestCase):
  def setUp(self):
    # Set up testing for application.
    self.test_app = webtest.TestApp(billing.app)

    # Set up datastore for testing.
    self.testbed = testbed.Testbed()
    self.testbed.activate()
    self.testbed.init_datastore_v3_stub()
    self.testbed.init_user_stub()

    # Make some testing plans.
    self.test_plan = plans.Plan("test", 0, 150, "This is a test plan.")
    self.test_plan_legacy = plans.Plan("test_legacy", 1, 100,
                                       "This is a test plan.",
                                       legacy=self.test_plan)

    # Make a test user.
    self.user = Membership(email="testy.testerson@gmail.com",
                           first_name="Testy", last_name="Testerson",
                           username="testy.testerson",
                           spreedly_token="notatoken", plan="test")
    self.user.put()

    # Simulate the user login.
    self.testbed.setup_env(user_email=self.user.email, user_is_admin="0",
                           overwrite=True)

  def tearDown(self):
    self.testbed.deactivate()


""" Tests for BillingHandler. """
class BillingHandlerTest(BaseTest):
  """ Tests that it works properly for a normal user. """
  def test_spreedly_redirect(self):
    response = self.test_app.get("/my_billing")
    self.assertEqual(302, response.status_int)

    self.assertEqual(self.user.spreedly_url(), response.location)

  """ Tests that it forces the user to be logged in. """
  def test_login(self):
    # Simulate no logged in user.
    self.testbed.setup_env(user_email="", overwrite=True)

    response = self.test_app.get("/my_billing")
    self.assertEqual(302, response.status_int)

    self.assertIn("/accounts/Login", response.location)

  """ Tests that it shows the legacy plan warning. """
  def test_legacy_warning(self):
    # Put the user on a legacy plan.
    self.user.plan = "test_legacy"
    self.user.put()

    response = self.test_app.get("/my_billing")
    self.assertEqual(200, response.status_int)

    self.assertIn("currently on a legacy", response.body)
    self.assertIn(str(self.test_plan.price_per_month), response.body)
    self.assertIn(str(self.test_plan_legacy.price_per_month), response.body)
