import logging
import urllib

from google.appengine.api import users

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


""" Base class for changing plans. """
class _PlanChangerBase(ProjectHandler):
  """ Renders a page allowing a user to change their plan.
  Args:
    member: The Membership object representing the user. """
  def _plan_switch_page(self, member):
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


""" Allows the user to change their plan. """
class ChangePlanHandler(_PlanChangerBase):
  def get(self):
    user = users.get_current_user()
    if not user:
      logging.debug("Need to login.")
      self.redirect(users.create_login_url(self.request.uri))
      return

    member = Membership.get_by_email(user.email())

    if not member:
      # This member doesn't exist.
      logging.error("No member with email '%s'." % (user.email()))
      logout_url = users.create_logout_url(self.request.uri)
      error = self.render("templates/error.html",
                          message="No member with your email was found.<br>" \
                          "<a href=%s>Try Again</a>" % (logout_url))
      self.response.out.write(error)
      self.response.set_status(422)
      return

    self._plan_switch_page(member)


""" Allows the user to change their plan when reactivating. """
class ReactivatePlanHandler(_PlanChangerBase):
  """ Args:
    user_hash: The hash of the user we are changing the plan of. """
  def get(self, user_hash):
    member = Membership.get_by_hash(user_hash)

    if not member:
      # Hash is invalid.
      logging.error("Invalid hash '%s'." % (user_hash))
      error = self.render("templates/error.html",
                          message="Invalid reactivation link.")
      self.response.out.write(error)
      self.response.set_status(422)
      return

    self._plan_switch_page(member)
