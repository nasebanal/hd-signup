import datetime
import hashlib

from google.appengine.ext import db
from config import Config
import plans

# A class for managing HackerDojo members.
class Membership(db.Model):
  hash = db.StringProperty()
  first_name = db.StringProperty(required=True)
  last_name = db.StringProperty(required=True)
  email = db.StringProperty(required=True)
  twitter = db.StringProperty(required=False)
  plan  = db.StringProperty(required=False)
  status  = db.StringProperty() # None, active, suspended
  referuserid = db.StringProperty()
  referrer  = db.StringProperty()
  username = db.StringProperty()
  password = db.StringProperty(default=None)
  rfid_tag = db.StringProperty()
  extra_599main = db.StringProperty()
  extra_dnd = db.BooleanProperty(default=False)
  auto_signin = db.StringProperty()
  unsubscribe_reason = db.TextProperty()
  hardship_comment = db.TextProperty()

  spreedly_token = db.StringProperty()
  parking_pass = db.StringProperty()

  created = db.DateTimeProperty(auto_now_add=True)
  updated = db.DateTimeProperty()

  # Whether we've created a google apps user yet.
  domain_user = db.BooleanProperty(default=False)

  # How many times the user has signed in this month.
  signins = db.IntegerProperty(default=0)

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
    return str('%s %s' % (self.first_name, self.last_name))

  def spreedly_url(self):
    config = Config()
    return str("https://spreedly.com/%s/subscriber_accounts/%s" % \
        (config.SPREEDLY_ACCOUNT, self.spreedly_token))

  def spreedly_admin_url(self):
    config = Config()
    return str("https://spreedly.com/%s/subscribers/%s" % \
        (config.SPREEDLY_ACCOUNT, self.key().id()))

  def subscribe_url(self):
    config = Config()
    try:
      url = "https://spreedly.com/%s/subscribers/%i/%s/subscribe/%s" % \
          (config.SPREEDLY_ACCOUNT, self.key().id(),
          self.spreedly_token, plans.Plan.get_by_name(self.plan).plan_id)
    except KeyError:
      url = "https://spreedly.com/%s/subscribers/%i/%s/subscribe/%s" % \
          (config.SPREEDLY_ACCOUNT, self.key().id(),
          self.spreedly_token, plans.newfull.plan_id)
    return str(url)

  def force_full_subscribe_url(self):
    config = Config()
    url = "https://spreedly.com/%s/subscribers/%i/%s/subscribe/%s" % \
        (config.SPREEDLY_ACCOUNT, self.key().id(),
        self.spreedly_token, plans.newfull.plan_id)
    return str(url)

  def unsubscribe_url(self):
    return "http://signup.hackerdojo.com/unsubscribe/%i" % (self.key().id())

  @classmethod
  def get_by_email(cls, email):
    return cls.all().filter('email =', email).get()

  @classmethod
  def get_by_hash(cls, hash):
    return cls.all().filter('hash =', hash).get()

  @classmethod
  def get_by_username(cls, username):
    return cls.all().filter('username =', username).get()
