import cPickle as pickle
import datetime
import hashlib
import logging
import urllib

from google.appengine.api import memcache
from google.appengine.ext import db

from webapp2_extras import auth, security

from passlib.hash import pbkdf2_sha256

from config import Config
import plans


""" Stores a validation token for users. This class is loosely based on the
equivalently-named one found here:
http://webapp-improved.appspot.com/_modules/webapp2_extras/appengine/
    auth/models.html """
class UserToken:
  """ Creates a new token for the given user.
  user: User unique ID.
  subject: The subject of the key, e.g. 'auth'.
  token: An optional existing token may be provided. If not, a random token will
  be generated.
  expires: How long before the token expires, in seconds. It defaults to one
  day. """
  def __init__(self, user, subject, token=None, expires=60 * 60 * 24):
    self.user = str(user)
    self.subject = subject
    if token:
      self.token = token
    else:
      self.token = security.generate_random_string(entropy=128)
    self.key = "%s.%s.%s" % (self.user, self.subject, self.token)

  """ Saves the current token to memcache. """
  def save(self):
    # Update the timestamp, because it was modified.
    self.timestamp = datetime.datetime.now()
    memcache.set(self.key, self)

  """ Deletes the current token from memcache. """
  def delete(self):
    memcache.delete(self.key)

  """ Verifies a user token.
  user: User unique ID.
  subject: The subject of the key, e.g. 'auth'.
  token: The token needing verification.
  Returns: A UserToken instance containing the token, or None if the token does
  not exist. """
  @classmethod
  def verify(cls, user, subject, token):
    key = "%s.%s.%s" % (user, subject, token)
    return memcache.get(key)


""" Hashes a password using the pbkdf2 algorithm.
password: The password to hash.
Returns: The hashed password. """
def _hash_password(password):
  # If we are unit testing, decrease the number of rounds so that the tests run
  # fast.
  rounds = 29000
  if Config().is_testing:
    rounds = 10

  return pbkdf2_sha256.encrypt(password, rounds=rounds)


""" A class for managing HackerDojo members. """
class Membership(db.Model):
  hash = db.StringProperty()
  first_name = db.StringProperty(required=True)
  last_name = db.StringProperty(required=True)
  email = db.StringProperty(required=True)
  # The hash of the user's password.
  # TODO(danielp): Make this required after we finish migrating away from domain
  # accounts.
  password_hash = db.StringProperty()
  twitter = db.StringProperty(required=False)
  plan  = db.StringProperty(required=False)
  status  = db.StringProperty() # None, active, suspended
  # Whether the user is an admin.
  is_admin = db.BooleanProperty(default=False)
  referuserid = db.StringProperty()
  referrer  = db.StringProperty()
  rfid_tag = db.StringProperty()
  extra_599main = db.StringProperty()
  extra_dnd = db.BooleanProperty(default=False)
  auto_signin = db.StringProperty()
  unsubscribe_reason = db.TextProperty()
  hardship_comment = db.TextProperty()

  spreedly_token = db.StringProperty()
  parking_pass = db.StringProperty()
  # A token for resetting the user's password.
  password_reset_token = db.StringProperty(multiline=True)

  created = db.DateTimeProperty(auto_now_add=True)
  updated = db.DateTimeProperty()

  # How many times the user has signed in this month.
  signins = db.IntegerProperty(default=0)
  # When the last time they signed in was.
  last_signin = db.DateTimeProperty()

  # The following are legacy parameters.
  # TODO(danielp): Remove these after we complete the migration away from
  # domain accounts.

  # Whether we've created a google apps user yet.
  domain_user = db.BooleanProperty(default=False)
  # The user's domain username.
  username = db.StringProperty()
  # Temporarily stores the user's domain password.
  password = db.StringProperty(default=None)

  """ Override of the default put method which allows us to skip changing the
  updated property for testing purposes.
  skip_time_update: Whether or not to set updated to the current date and time.
  """
  def put(self, *args, **kwargs):
    if not kwargs.pop("skip_time_update", False):
      self.updated = datetime.datetime.now()

    super(Membership, self).put(*args, **kwargs)

  def icon(self):
    return str("http://www.gravatar.com/avatar/" + hashlib.md5(self.email.lower()).hexdigest())

  def full_name(self):
    return '%s %s' % (self.first_name, self.last_name)

  def spreedly_url(self):
    config = Config()
    return str("https://subs.pinpayments.com/%s/subscriber_accounts/%s" % \
        (config.SPREEDLY_ACCOUNT, self.spreedly_token))

  def spreedly_admin_url(self):
    config = Config()
    return str("https://subs.pinpayments.com/%s/subscribers/%s" % \
        (config.SPREEDLY_ACCOUNT, self.key().id()))

  def subscribe_url(self, plan=None):
    config = Config()
    if not plan:
      plan = self.plan
    url = "https://subs.pinpayments.com/%s/subscribers/%i/%s/subscribe/%s" % \
        (config.SPREEDLY_ACCOUNT, self.key().id(),
         self.spreedly_token, plans.Plan.get_by_name(plan).plan_id)
    return str(url)

  """ URL we use to subscribe a person for the first time.
  host: The first part of the return URL, e.g. signup.hackerdojo.com.
  plan: Optionally specifies a different plan to use. """
  def new_subscribe_url(self, host, plan=None):
    config = Config()
    if not plan:
      plan = self.plan

    query_str = urllib.urlencode({"first_name": self.first_name,
                                  "last_name": self.last_name,
                                  "email": self.email,
                                  "return_url": "http://%s/success/%s" % \
                                      (host, self.hash)})
    url = "https://subs.pinpayments.com/%s/subscribers/%i/subscribe/%s/%s?%s" % \
        (config.SPREEDLY_ACCOUNT, self.key().id(),
         plans.Plan.get_by_name(plan).plan_id, self.email, query_str)
    return str(url)

  def force_full_subscribe_url(self):
    config = Config()
    url = "https://subs.pinpayments.com/%s/subscribers/%i/%s/subscribe/%s" % \
        (config.SPREEDLY_ACCOUNT, self.key().id(),
        self.spreedly_token, plans.newfull.plan_id)
    return str(url)

  def unsubscribe_url(self):
    return "http://signup.hackerdojo.com/unsubscribe/%i" % (self.key().id())

  """ Returns this user's unique ID, which can be an integer or string. """
  def get_id(self):
    return self.key().id()

  """ Sets the user's password.
  It does not write to the datastore afterward.
  password: The password which will be hashed and stored. """
  def set_password(self, password):
    logging.debug("Setting password for user %s." % (self.email))

    self.password_hash = _hash_password(password)

  """ Creates a password reset token for the user.
  Returns: The token that was created. """
  def create_password_reset_token(self):
    token = UserToken(self.get_id(), "password_reset")
    logging.debug("Created password reset token for %s." % (self.email))

    token.timestamp = datetime.datetime.now()
    # Store the token in the datastore.
    self.password_reset_token = pickle.dumps(token)
    self.put()

    return token.token

  """ Verifies a password reset token for this user.
  token: The token to verify.
  Returns: True if the token is valid, False otherwise. """
  def verify_password_reset_token(self, token):
    if not self.password_reset_token:
      return False

    good_token = pickle.loads(str(self.password_reset_token))

    if good_token.token != token:
      logging.error("Got bad token: %s for user %s." % (token, self.email))
      return False
    if (datetime.datetime.now() - good_token.timestamp > \
        datetime.timedelta(days=1)):
      # They have one day to use the token.
      logging.error("Expired token %s was used for user %s." % \
                    (token, self.email))
      return False

    return True

  """ Creates a new authorization token for a given user ID.
  user_id: User unique ID.
  Returns: A string with the authorization token. """
  @classmethod
  def create_auth_token(cls, user_id):
    token = UserToken(user_id, "auth")
    token.save()

    return token.token

  """ Deletes a given authorization token.
  user_id: User unique ID.
  token: A string with the authorization token. """
  @classmethod
  def delete_auth_token(cls, user_id, token):
    token = UserToken.verify(user_id, "auth", token)
    if not token:
      logging.warning("Delete: Ignoring bad token for %d." % (user_id))
      return

    token.delete()

  """ Returns a Membership object based on a user ID and token.
  user_id: The unique ID of the requesting user.
  token: The token string to be verified.
  Returns: A tuple (Membership, timestamp), with a Membership object and
  the token timestamp, or (None, None) if both were not found. """
  @classmethod
  def get_by_auth_token(cls, user_id, token):
    # First, check that the token is valid.
    token = UserToken.verify(user_id, "auth", token)
    if not token:
      logging.warning("Bad token, not getting user %d." % (user_id))
      return (None, None)

    user = cls.get_by_id(user_id)
    timestamp = token.timestamp
    return (user, timestamp)

  """ Gets the user with the specified login credentials.
  email: The email of the user.
  password: The password of the user.
  Returns: Membership object if found. """
  @classmethod
  def get_by_auth_password(cls, email, password):
    user = cls.get_by_email(email)
    if not user:
      raise auth.InvalidAuthIdError("No user with email '%s'." % (email))

    try:
      valid = pbkdf2_sha256.verify(password, user.password_hash)
    except TypeError:
      raise auth.InvalidPasswordError("Bad password for user '%s'." % (email))
    if not valid:
      raise auth.InvalidPasswordError("Bad password for user '%s'." % (email))

    return user

  """ Gets the user with the specified email.
  email: Either the normal email, or the hackerdojo.com email of the user.
  Returns: The membership object corresponding to the user, or None if no user
  was found. """
  @classmethod
  def get_by_email(cls, email):
    # TODO(danielp): Remove code for dealing with hackerdojo.com emails after
    # we've finished migrating away from domain accounts.
    if "@hackerdojo.com" in email:
      username = email.split("@")[0]
      return cls.get_by_username(username)

    return cls.all().filter('email =', email).get()

  @classmethod
  def get_by_hash(cls, hash):
    return cls.all().filter('hash =', hash).get()

  # This is a legacy method:
  # TODO(danielp): Remove this after we migrate away from domain accounts.
  @classmethod
  def get_by_username(cls, username):
    return cls.all().filter('username =', username).get()

  """ Creates a new user.
  email: The user's email. This will be used as a unique ID.
  password: The user's raw password. Will be hashed before saving, obviously.
  other_properties: Keyword arguments specifying properties that will be
  forwarded to the Membership constructor. All the other required properties
  should be in here.
  Returns: The created Membership entity. """
  @classmethod
  def create_user(cls, email, password, **other_properties):
    logging.info("Creating user with email '%s', other properties: %s." % \
                 (email, other_properties))

    password_hash = _hash_password(password)
    member = cls(email=email, password_hash=password_hash, **other_properties)
    member.put()

    return member
