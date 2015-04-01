import logging
import os

from google.appengine.api.app_identity import get_application_id

import keymaster

# Class for storing specific configuration parameters.

class Config():
  is_dev = False
  is_prod = True

  def __init__(self):
    try:
      # Check if we are running on the local dev server.
      Config.is_dev = os.environ['SERVER_SOFTWARE'].startswith('Dev')
    except KeyError:
      pass
    if not Config.is_dev:
      # Check if we are running the dev application.
      Config.is_dev = "-dev" in get_application_id()
    Config.is_prod = not Config.is_dev

    self.PLAN_IDS = {'full': '1987', 'hardship': '2537',
        'supporter': '1988', 'family': '3659',
        'worktrade': '6608', 'comped': '15451',
        'threecomp': '18158', 'yearly':'18552',
        'fiveyear': '18853', 'thielcomp': '19616',
        # This is the new full membership at $195.
        'newfull': '25716'}

    if Config.is_dev:
      self.SPREEDLY_ACCOUNT = 'hackerdojotest'
      self.SPREEDLY_APIKEY = keymaster.get('spreedly:hackerdojotest')

      logging.info("Is dev server.")
    else:
      self.SPREEDLY_ACCOUNT = 'hackerdojo'
      self.SPREEDLY_APIKEY = keymaster.get('spreedly:hackerdojo')

      logging.info("Is production server.")
