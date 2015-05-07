import logging
import urllib

from config import Config
from membership import Membership
from project_handler import ProjectHandler


""" Handles allowing the user to select a plan. """
class SelectPlanHandler(ProjectHandler):
  """ hash: The hash of the member we are selecting a plan for. """
  def get(self, member_hash):
    # Urls to send people to when they click plans.
    base_url = "/account/%s" % (member_hash)
    full_url = "%s?%s" % (base_url, urllib.urlencode({"plan": "newfull"}))
    premium_url = "%s?%s" % (base_url, urllib.urlencode({"plan": "newhive"}))
    lite_url = "%s?%s" % (base_url, urllib.urlencode({"plan": "lite"}))
    yearly_url = "%s?%s" % (base_url, urllib.urlencode({"plan": "newyearly"}))

    self.response.out.write(self.render("templates/select_plan.html",
                            full_url=full_url, premium_url=premium_url,
                            lite_url=lite_url, yearly_url=yearly_url,
                            lite_visits=Config().LITE_VISITS))
