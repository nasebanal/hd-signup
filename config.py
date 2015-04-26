import logging
import os

from google.appengine.api import app_identity

import keymaster


""" Class for storing specific configuration parameters. """
class Config():
  is_dev = False
  is_prod = True
  is_testing = False;

  def __init__(self):
    try:
      # Check if we are running on the local dev server.
      Config.is_dev = os.environ["SERVER_SOFTWARE"].startswith("Dev")
    except KeyError:
      pass

    self.APP_NAME = app_identity.get_application_id()
    if self.APP_NAME == "testbed-test":
      Config.is_testing = True

    if not Config.is_dev:
      # Check if we are running the dev application.
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

    self.PLAN_IDS = {"full": "1987", "hardship": "2537",
        "supporter": "1988", "family": "3659",
        "worktrade": "6608", "comped": "15451",
        "threecomp": "18158", "yearly":"18552",
        "fiveyear": "18853", "hive": "19616",
        # This is the new full membership at $195.
        "newfull": "25716",
        # This is the new hive membership at $325.
        "newhive": "25790",
        # A limited membership with a reduced price.
        "lite": "25791"}

    # How many visits per month we allow on the lite membership.
    #TODO(danielp): Figure out the real number here.
    self.LITE_VISITS = 8

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
