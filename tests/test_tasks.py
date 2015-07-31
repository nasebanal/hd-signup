""" Tests for tasks.py """


# We need our external modules.
import appengine_config

import unittest

from google.appengine.ext import testbed
from google.appengine.ext import db

import webtest

from membership import Membership
import tasks


""" A base test class that sets everything up correctly. """
class BaseTest(unittest.TestCase):
  def setUp(self):
    # Set up testing for application.
    self.test_app = webtest.TestApp(tasks.app)

    # Set up datastore for testing.
    self.testbed = testbed.Testbed()
    self.testbed.activate()
    self.testbed.init_datastore_v3_stub()
    self.testbed.init_taskqueue_stub()
    self.testbed.init_mail_stub()
    self.testbed.init_memcache_stub()

    # Add a user to the datastore.
    self.user = Membership(first_name="Testy", last_name="Testerson",
                      email="ttesterson@gmail.com", hash="notahash",
                      spreedly_token="notatoken", username="testy.testerson",
                      password="notasecret")
    self.user.put()

    self.mail_stub = self.testbed.get_stub(testbed.MAIL_SERVICE_NAME)

  def tearDown(self):
    self.testbed.deactivate()


""" Tests that CleanupTask functions properly. """
class CleanupTaskTest(BaseTest):
  def setUp(self):
    super(CleanupTaskTest, self).setUp()

    self.user_id = self.user.key().id()
    self.params = {"user": str(self.user_id)}

  """ Tests that it works under normal conditions. """
  def test_cleanup(self):
    response = self.test_app.post("/tasks/clean_row", self.params)
    self.assertEqual(200, response.status_int)

    # Make sure the user is gone.
    user = Membership.get_by_id(self.user_id)
    self.assertEqual(None, user)

    # Make sure our email got sent and looks correct.
    messages = self.mail_stub.get_sent_messages(to=self.user.email)
    self.assertEqual(1, len(messages))
    body = str(messages[0].body)
    self.assertIn(self.user.full_name(), body)

  """ Tests that it deals properly with a nonexistent user. """
  def test_bad_user_id(self):
    params = {"user": "1337"}
    response = self.test_app.post("/tasks/clean_row", params)
    # The status should still be okay, because we don't want it to retry in this
    # case.
    self.assertEqual(200, response.status_int)

    # The user should still be there.
    user = Membership.get_by_id(self.user_id)
    self.assertNotEqual(None, user)

    # No email should have gotten sent.
    messages = self.mail_stub.get_sent_messages(to=self.user.email)
    self.assertEqual(0, len(messages))
