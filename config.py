# Class for storing specific configuration parameters.

class Config():
    def __init__(self):
        try:
            self.is_dev = os.environ['SERVER_SOFTWARE'].startswith('Dev')
        except:
            self.is_dev = False  
        self.is_prod = not self.is_dev
        if self.is_dev:
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

