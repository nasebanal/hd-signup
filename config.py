import os

import keymaster

# Class for storing specific configuration parameters.

class Config():
  is_dev = False
  is_prod = True
  def __init__(self):
    try:
      if not Config.is_dev:
        Config.is_dev = os.environ['SERVER_SOFTWARE'].startswith('Dev')
    except KeyError:
      pass
    Config.is_prod = not Config.is_dev
    if Config.is_dev:
      self.SPREEDLY_ACCOUNT = 'hackerdojotest'
      self.SPREEDLY_APIKEY = keymaster.get('spreedly:hackerdojotest')
      self.PLAN_IDS = {'full': '1957'}
    else:
      self.SPREEDLY_ACCOUNT = 'hackerdojo'
      self.SPREEDLY_APIKEY = keymaster.get('spreedly:hackerdojo')
      self.PLAN_IDS = {'full': '1987', 'hardship': '2537',
          'supporter': '1988', 'family': '3659',
          'worktrade': '6608', 'comped': '15451',
          'threecomp': '18158', 'yearly':'18552',
          'fiveyear': '18853', 'thielcomp': '19616'}
