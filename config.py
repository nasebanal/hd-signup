import logging
import os

from google.appengine.api import app_identity

import keymaster


""" Class for storing specific configuration parameters. """
class Config:
  # Mutually exclusive flags that specify whether the application is running on
  # hd-signup-hrd, signup-dev/dev_appserver, or local unit tests.
  is_dev = False
  is_prod = True
  is_testing = False;

  def __init__(self):
    try:
      # Check if we are running on the local dev server.
      software = os.environ["SERVER_SOFTWARE"]
      Config.is_dev = software.startswith("Dev") and "testbed" not in software
    except KeyError:
      pass

    try:
      self.APP_NAME = app_identity.get_application_id()
    except AttributeError:
      # We're calling code outside of GAE, so we must be testing.
      self.APP_NAME = "testbed-test"
    if self.APP_NAME == "testbed-test":
      Config.is_testing = True

    if not Config.is_dev:
      # Check if we are running on the dev application.
      Config.is_dev = "-dev" in self.APP_NAME

    Config.is_prod = not (Config.is_dev or Config.is_testing)

    self.ORG_NAME = "Hacker Dojo"
    self.EMAIL_FROM = "Dojo Signup <no-reply@%s.appspotmail.com>" % \
        self.APP_NAME
    self.EMAIL_FROM_AYST = "Billing System <robot@hackerdojo.com>"
    self.DAYS_FOR_KEY = 0
    self.INTERNAL_DEV_EMAIL = "Internal Dev <internal-dev@hackerdojo.com>"
    self.DOMAIN_HOST = "hd-domain-hrd.appspot.com"
    self.DOMAIN_USER = "api@hackerdojo.com"
    self.SUCCESS_HTML_URL = \
        "http://hackerdojo.pbworks.com/api_v2/op/GetPage/page/\
        SubscriptionSuccess/_type/html"
    self.PAYPAL_EMAIL = "PayPal <paypal@hackerdojo.com>"
    self.APPS_DOMAIN = "hackerdojo.com"
    self.SIGNUP_HELP_EMAIL = "signupops@hackerdojo.com"
    self.TREASURER_EMAIL = "treasurer@hackerdojo.com"
    self.GOOGLE_ANALYTICS_ID = "UA-11332872-2"

    # How many visits per month we allow on the lite membership.
    #TODO(danielp): Figure out the real number here.
    self.LITE_VISITS = 8
    # How many people can have desks in the hive at any one time.
    self.HIVE_MAX_OCCUPANCY = 14
    # How long someone can be suspended in days before we stop counting them
    # when calculating whether their plan is full or not.
    self.PLAN_USER_IGNORE_THRESHOLD = 30

    # Hours that the Dojo is open, in 24-hour time. (start, end)
    self.DOJO_HOURS = (10, 21)

    if Config.is_testing:
      self.SPREEDLY_ACCOUNT = "hackerdojotest"
      # We can't use the datastore.
      self.SPREEDLY_APIKEY = "testapikey"

      logging.debug("Is testing.")
    elif Config.is_dev:
      self.SPREEDLY_ACCOUNT = "hackerdojotest"
      self.SPREEDLY_APIKEY = keymaster.get("spreedly:hackerdojotest")

      logging.debug("Is dev server.")
    else:
      self.SPREEDLY_ACCOUNT = "hackerdojo"
      self.SPREEDLY_APIKEY = keymaster.get("spreedly:hackerdojo")

      logging.debug("Is production server.")
