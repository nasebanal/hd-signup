""" Manages different plans. """


import datetime
import logging

from google.appengine.ext import db

from config import Config
from membership import Membership


""" Represents a single subscription plan. """
class Plan:
  # A list of all the plans that have been created.
  all_plans = []
  # A list of pairs of plans and their legacy plans.
  legacy_pairs = set()

  def __init__(self, name, plan_id, price_per_month, description,
               human_name=None, signin_limit=None, member_limit=None,
               legacy=None, selectable=True, full=False, admin_only=False,
               desk=False):
    """ The name of the plan in PinPayments. """
    self.name = name
    """ The user-facing name of this plan. """
    if human_name:
      self.human_name = human_name
    else:
      self.human_name = self.name.capitalize()
    """ The ID of the plan in PinPayments. """
    self.plan_id = str(plan_id)
    """ A description of the plan. """
    self.description = description

    """ None if this is not a legacy plan, otherwise the non-legacy version of
    the plan. """
    self.legacy = legacy
    if self.legacy:
      self.legacy_pairs.add((self, self.legacy))
    """ Whether this plan is available for general selection. """
    self.selectable = False if self.legacy else selectable
    """ Whether this plan is currently full. """
    self.full = full
    """ Whether only an admin can put people on this plan. """
    self.admin_only = True if self.legacy else admin_only

    """ The monthly price of this plan. """
    self.price_per_month = price_per_month
    """ Whether this plan comes with a private desk. """
    self.desk = desk
    """ Maximum number of times these people can sign in per month. """
    self.signin_limit = signin_limit
    """ Maximum number of people that can be on this plan at once. """
    self.member_limit = member_limit

    Plan.all_plans.append(self)

  """ Updates the availability status of plans by looking in the datastore. """
  def __update_availability(self):
    # There's no limit, so there's not point in doing this.
    if self.member_limit == None:
      return

    # If this plan has a legacy version or is a legacy version of another plan,
    # we combine the members on both versions.
    counterpart = self.get_legacy_pair()
    if counterpart:
      logging.debug("Including members from legacy pair '%s'." % \
                    (counterpart.name))
      query_plan = "plan in ('%s', '%s')" % (self.name, counterpart.name)
    else:
      query_plan = "plan = '%s'" % (self.name)

    last_month = datetime.datetime.now() - \
        datetime.timedelta(days=Config().PLAN_USER_IGNORE_THRESHOLD)
    # We don't have an OR operator, so do two separate queries for suspended
    # (or members who haven't yet created their accounts), and non-suspended
    # members.
    suspended_query = db.GqlQuery("SELECT * FROM Membership WHERE %s AND " \
        " status in ('suspended', NULL) AND updated >" \
        " DATETIME(%d, %d, %d, %d, %d, %d)" % \
        (query_plan, last_month.year, last_month.month, last_month.day,
         last_month.hour, last_month.minute, last_month.second))
    active_query = db.GqlQuery("SELECT * FROM Membership WHERE %s" \
        " AND status = 'active'" % (query_plan))
    suspended_members = suspended_query.count()
    active_members = active_query.count()
    logging.debug("Found %d suspended members on plan %s." % \
        (suspended_members, self.name))
    logging.debug("Found %d active members on plan %s." % \
        (active_members, self.name))
    num_members = active_members + suspended_members

    if num_members >= self.member_limit:
      # This plan is full.
      self.full = True
    else:
      # This plan has space.
      self.full = False

  """ Returns the plan that is either the legacy or non-legacy version of this
  one. If that plan does not exist, it returns None. """
  def get_legacy_pair(self):
    for pair in self.legacy_pairs:
      # See if we are part of the pair.
      plan1, plan2 = pair
      if plan1 == self:
        return plan2
      if plan2 == self:
        return plan1

    return None

  """ Gets a plan object based on the name of the plan.
  name: The name of the plan.
  Returns: The plan object corresponding to the plan. """
  @classmethod
  def get_by_name(cls, name):
    for plan in cls.all_plans:
      if plan.name == name:
        return plan

    logging.error("Could not find plan '%s'." % (name))
    raise ValueError("Could not find that plan.")

  """ Get a list of the plans to show on the selection page.
  Returns: A tuple. The first item is a list of the plans to show as selectable,
  the second is a list of the plans to show as unavailable. """
  @classmethod
  def get_plans_to_show(cls):
    selectable = []
    unavailable = []

    for plan in cls.all_plans:
      plan.__update_availability()

      if plan.selectable:
        if not plan.full:
          selectable.append(plan)
        else:
          unavailable.append(plan)

    return (selectable, unavailable)

  """ Figures out how many more signins a user has.
  email: The email of the user to check.
  Returns: The number of visits remaining, on None if this user has unlimmited
  visits. """
  @classmethod
  def signins_remaining(cls, email):
    user = Membership.get_by_email(email)
    if not user:
      logging.error("Cannot find user with email '%s'." % (email))
      raise ValueError("Could not find that user.")

    plan = cls.get_by_name(user.plan)

    try:
      if plan.signin_limit == None:
        # Unlimited signins.
        return None
      remaining = max(0, plan.signin_limit - user.signins)
    except AttributeError:
      # Model hasn't been updated to include this attribute. This can only
      # happen if the user hasn't signed in yet, so we should let them.
      return plan.signin_limit

    return remaining

  """ Checks if the plan is full.
  Returns: True if the plan is full, False otherwise. """
  def is_full(self):
    self.__update_availability()
    return self.full

  """ Checks whether a user requesting this plan at the beginning of the signup
  process should be allowed to use it.
  name: The name of the plan being requested.
  Returns: True if they can use the plan, False if they can't, None if no such
  plan exists. """
  @classmethod
  def can_subscribe(cls, name):
    try:
      plan = cls.get_by_name(name)
    except ValueError:
      # The plan doesn't exist. We shouldn't use it.
      return None

    if plan.is_full():
      logging.warning("Can't use plan '%s' because it's full." % (name))
      return False
    if plan.admin_only:
      logging.warning("Only an admin can put someone on plan '%s'." % (name))
      return False

    return True


# Plans
newfull = Plan("newfull", 25716, 195, "The standard plan.",
               human_name="Standard")
newstudent = Plan("newstudent", 25967, 60, "A cheap plan for students.",
                  human_name="Student",
                  selectable=False)
newyearly = Plan("newyearly", 25968, 97.5, "Bills every year instead.",
                 human_name="Yearly")
newhive = Plan("newhive", 25790, 325, "You get a private desk too!",
               human_name="Premium", member_limit=Config().HIVE_MAX_OCCUPANCY,
               desk=True)

full = Plan("full", 1987, 125, "The old standard plan.",
            human_name="Old Standard",
            legacy=newfull)
hardship = Plan("hardship", 2537, 50, "Old version of the student plan.",
                human_name="Old Student",
                legacy=newstudent)
supporter = Plan("supporter", 1988, 10, "A monthly donation to the dojo.",
                 human_name="Monthly Donation", signin_limit=0)
family = Plan("family", 3659, 50, "Get a family discount.",
              human_name="Family",
              selectable=False, admin_only=True)
worktrade = Plan("worktrade", 6608, 0, "Free until we cancel it.",
                 human_name="Free Ride",
                 selectable=False, admin_only=True)
comped = Plan("comped", 15451, 0, "One year free.",
              human_name="Free Year",
              selectable=False, admin_only=True)
threecomp = Plan("threecomp", 18158, 0, "Three months free.",
                 human_name="Free Three Months",
                 selectable=False, admin_only=True)
yearly = Plan("yearly", 18552, 125, "Old yearly plan.",
              human_name="Old Yearly",
              legacy=newyearly)
fiveyear = Plan("fiveyear", 18853, 83, "Pay for five years now.",
                human_name="Five Years",
                selectable=False)
hive = Plan("Hive", 19616, 275, "Old premium plan.",
            human_name="Old Premium", member_limit=Config().HIVE_MAX_OCCUPANCY,
            legacy=newhive, desk=True)
lite = Plan("lite", 25791, 125, "A limited but cheaper plan.",
            signin_limit=Config().LITE_VISITS)
