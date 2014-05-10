from google.appengine.ext import db
from config import Config

import keymaster


# A class for managing HackerDojo members.
class Membership(db.Model):
    hash = db.StringProperty()
    first_name = db.StringProperty(required=True)
    last_name = db.StringProperty(required=True)
    email = db.StringProperty(required=True)
    twitter = db.StringProperty(required=False)
    plan  = db.StringProperty(required=True)
    status  = db.StringProperty() # None, active, suspended
    referuserid = db.StringProperty()
    referrer  = db.StringProperty()
    username = db.StringProperty()
    rfid_tag = db.StringProperty()
    extra_599main = db.StringProperty()
    extra_dnd = db.BooleanProperty(default=False)
    auto_signin = db.StringProperty()
    unsubscribe_reason = db.TextProperty()
    hardship_comment = db.TextProperty()
    
    spreedly_token = db.StringProperty()
    
    created = db.DateTimeProperty(auto_now_add=True)
    updated = db.DateTimeProperty(auto_now=True)

    def __init__(self):
      self.config = Config()
    
    def icon(self):
        return str("http://www.gravatar.com/avatar/" + hashlib.md5(self.email.lower()).hexdigest())

    def full_name(self):
        return str('%s %s' % (self.first_name, self.last_name))
    
    def spreedly_url(self):
        return str("https://spreedly.com/%s/subscriber_accounts/%s" % \
            (self.config.SPREEDLY_ACCOUNT, self.spreedly_token))

    def spreedly_admin_url(self):
        return str("https://spreedly.com/%s/subscribers/%s" % \
            (self.config.SPREEDLY_ACCOUNT, self.key().id()))

    def subscribe_url(self):
        try:
            url = "https://spreedly.com/%s/subscribers/%i/%s/subscribe/%s" % \
                (self.config.SPREEDLY_ACCOUNT, self.key().id(),
                self.spreedly_token, self.config.PLAN_IDS[self.plan])
        except KeyError:
            url = "https://spreedly.com/%s/subscribers/%i/%s/subscribe/%s" % \
                (self.config.SPREEDLY_ACCOUNT, self.key().id(),
                self.spreedly_token, self.config.PLAN_IDS["full"])
        return str(url)

    def force_full_subscribe_url(self):
        url = "https://spreedly.com/%s/subscribers/%i/%s/subscribe/%s" % \
            (self.config.SPREEDLY_ACCOUNT, self.key().id(),
            self.spreedly_token, self.config.PLAN_IDS["full"])          
        return str(url)

    def unsubscribe_url(self):
        return "http://signup.hackerdojo.com/unsubscribe/%i" % (self.key().id())
    
    @classmethod
    def get_by_email(cls, email):
        return cls.all().filter('email =', email).get()
    
    @classmethod
    def get_by_hash(cls, hash):
        return cls.all().filter('hash =', hash).get()
