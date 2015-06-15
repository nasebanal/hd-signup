import logging
import urllib

from config import Config
from membership import Membership
from project_handler import ProjectHandler
import plans


""" Handles allowing the user to select a plan. """
class SelectPlanHandler(ProjectHandler):
  """ member_hash: The hash of the member we are selecting a plan for. """
  def get(self, member_hash):
    # Get the plans to show.
    selectable, unavailable = plans.Plan.get_plans_to_show()

    # Put the urls to send people to when they select a plan in there also, in a
    # form that is easy for jinja to understand.
    base_url = "/account/%s" % (member_hash)
    selectable_paired = []
    for plan in selectable:
      item = {}
      item["url"] = "%s?%s" % (base_url, urllib.urlencode({"plan": plan.name}))
      item["plan"] = plan

      selectable_paired.append(item)

    self.response.out.write(self.render("templates/select_plan.html",
                            selectable=selectable_paired,
                            unavailable=unavailable))


""" Allows the user to change their plan. """
class ChangePlanHandler(ProjectHandler):
  """ member_hash: The hash of the member we are selecting a plan for. """
  def get(self, member_hash):
    member = Membership.get_by_hash(member_hash)
    if not member:
      # This member doesn't exist.
      logging.error("No member with hash '%s'." % (member_hash))
      error = self.render("templates/error.html",
                          message="No member with this hash.")
      self.response.out.write(error)
      self.response.set_status(422)
      return
    if not member.spreedly_token:
      # This member hasn't signed up for an account initially.
      logging.warning("%s must have a plan before we can change it." %
                      (member.email))
      error = self.render("templates/error.html",
                  message="You are not currently signed up for any plan.")
      self.response.out.write(error)
      self.response.set_status(422)
      return

    # Get the plans to show.
    selectable, unavailable = plans.Plan.get_plans_to_show()

    # Put the urls to send people to when they select a plan in there also, in a
    # form that is easy for jinja to understand.
    selectable_paired = []
    for plan in selectable:
      item = {}
      item["url"] = member.subscribe_url(plan=plan.name)
      item["plan"] = plan

      selectable_paired.append(item)

    self.response.out.write(self.render("templates/select_plan.html",
                            selectable=selectable_paired,
                            unavailable=unavailable))
