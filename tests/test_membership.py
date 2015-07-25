""" Tests for membership.py. """


# We need our external modules.
import appengine_config

from google.appengine.ext import testbed

from webapp2_extras import auth, security

import datetime
import unittest

import membership


""" A base test class that sets everything up correctly. """
class BaseTest(unittest.TestCase):
  def setUp(self):
    # Set up datastore for testing.
    self.testbed = testbed.Testbed()
    self.testbed.activate()
    self.testbed.init_datastore_v3_stub()
    self.testbed.init_memcache_stub()

  def tearDown(self):
    self.testbed.deactivate()


""" Tests that the user token handler class works. """
class UserTokenTest(BaseTest):
  """ Tests that we can generate a user token. """
  def test_token_generation(self):
    user = 1337
    subject = "auth"

    token = membership.UserToken(user, subject)

    self.assertEqual(str(user), token.user)
    self.assertEqual(subject, token.subject)
    self.assertEqual("%d.%s.%s" % (user, subject, token.token), token.key)
    # The token is a random string.
    print "Random token: %s" % (token.token)

    # Specify the token instead.
    token_string = "atoken"

    token = membership.UserToken(user, subject, token=token_string)

    self.assertEqual(token_string, token.token)

  """ Tests that we can save and delete the token to/from memcache. """
  def test_memcache(self):
    user = 1337
    subject = "auth"

    token = membership.UserToken(user, subject)
    token.save()

    # Now we should be able to get the token using its key.
    new_token = membership.UserToken.verify(user, subject, token.token)
    self.assertEqual(token.user, new_token.user)
    self.assertEqual(token.subject, new_token.subject)
    self.assertEqual(token.key, new_token.key)
    self.assertEqual(token.token, new_token.token)

""" Tests that the Membership class works. """
class MembershipTest(BaseTest):
  def setUp(self):
    super(MembershipTest, self).setUp()

    self.user = membership.Membership(email="testy.testerson@gmail.com",
                                      first_name="Testy", last_name="Testerson")
    self.user.put()
    self.user_id = self.user.key().id()

  """ Tests that the auth token methods work properly. """
  def test_auth_token(self):
    # Make a new token for the user.
    token = membership.Membership.create_auth_token(self.user_id)

    # Now we should be able to retreive the user by the token.
    user, timestamp = membership.Membership.get_by_auth_token(
        self.user_id, token)
    self.assertEqual(self.user.properties(), user.properties())
    self.assertLess(timestamp, datetime.datetime.now())

    # Delete the token.
    membership.Membership.delete_auth_token(self.user_id, token)

    # Now it shouldn't work.
    user, timestamp = membership.Membership.get_by_auth_token(
        self.user_id, token)
    self.assertEqual(None, user)
    self.assertEqual(None, timestamp)

  """ Tests that the password verification works correctly. """
  def test_password_auth(self):
    # Give the user a password.
    password = "notasecret"
    password_hash = security.generate_password_hash(password)
    self.user.password_hash = password_hash
    self.user.put()

    # Now, we should be able to authenticate with that password.
    user = membership.Membership.get_by_auth_password(self.user.email, password)
    self.assertEqual(self.user.properties(), user.properties())

    # Try with the wrong password.
    with self.assertRaises(auth.InvalidPasswordError):
      membership.Membership.get_by_auth_password(self.user.email, "badpassword")

    # Try with the wrong email altogether.
    with self.assertRaises(auth.InvalidAuthIdError):
      membership.Membership.get_by_auth_password("bademail", password)
