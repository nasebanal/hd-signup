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


""" Tests that CreateUserTask works correctly. """
class CreateUserTaskTest(BaseTest):
  def setUp(self):
    super(CreateUserTaskTest, self).setUp()

    self.user_hash = self.user.hash
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
