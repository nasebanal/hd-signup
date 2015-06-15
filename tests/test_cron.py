""" Tests for cron jobs. """

# We need our external modules.
import appengine_config

import unittest

import webtest

from google.appengine.ext import testbed

from membership import Membership
import cron


""" Tests for the signin reset cron job. """
class ResetSigninHandlerTest(unittest.TestCase):
  def setUp(self):
    # Set up testing application.
    self.test_app = webtest.TestApp(cron.app)

    # Set up datastore for testing.
    self.testbed = testbed.Testbed()
    self.testbed.activate()
    self.testbed.init_datastore_v3_stub()

    # Add a user to the datastore.
    self.user = Membership(first_name="Testy", last_name="Testerson",
                           email="ttesterson@gmail.com")
    self.user.put()

  """ Tests that the cron job restores users properly. """
  def test_user_restore(self):
    self.user.signins = 10
    self.user.status = "no_visits"
    self.user.put()

    response = self.test_app.get("/cron/reset_signins")
    self.assertEqual(200, response.status_int)

    user = Membership.get_by_email("ttesterson@gmail.com")
    self.assertEqual(0, user.signins)
    self.assertEqual("active", user.status)
