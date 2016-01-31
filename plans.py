""" Manages different plans. """


import datetime
import logging

from google.appengine.ext import db

from config import Config
from project_handler import ProjectHandler
import keymaster
import membership


""" Represents a single subscription plan. """
class Plan:
  # A list of all the plans that have been created.
  all_plans = []
  # A list of pairs of plans and their legacy plans.
  legacy_pairs = set()

  def __init__(self, name, price_per_month, description,
               human_name=None, aliases=[], signin_limit=None,
               member_limit=None, legacy=None, selectable=True, full=False,
               admin_only=False, desk=False, create_events=True):
    """ The name of the plan in PinPayments. """
    self.name = name
    """ The user-facing name of this plan. """
    if human_name:
      self.human_name = human_name
    else:
      self.human_name = self.name.capitalize()
    """ The ID of the plan in PinPayments. """
    if not Config().is_testing:
      self.plan_id = str(keymaster.get("plan.%s" % (self.name,)))
    else:
      # Just use the name as the ID for testing.
      self.plan_id = self.name
    logging.debug("Using plan_id for %s: %s" % (self.name, self.plan_id))
    """ A description of the plan. """
    self.description = description
    """ Any other names that this plan could be referred to by. """
    self.aliases = aliases

    """ None if this is not a legacy plan, otherwise the non-legacy version of
    the plan. """
    self.legacy = legacy
    if self.legacy:
      self.legacy_pairs.add((self, self.legacy))
    """ Whether only an admin can put people on this plan. """
    self.admin_only = True if self.legacy else admin_only
    """ Whether this plan is available for general selection. """
    self.selectable = False if (self.legacy or self.admin_only) else selectable
    """ Whether this plan is currently full. """
    self.full = full
    """ Whether a user on this plan can create new events. """
    self.create_events = create_events

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
    # Do it this way to avoid circular imports.
    Membership = membership.Membership
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
      if (plan.name == name or name in plan.aliases):
        return plan

    raise ValueError("Could not find plan '%s'." % (name))

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
  user: The Membership object representing the user to check.
  Returns: The number of visits remaining, on None if this user has unlimited
  visits. """
  @classmethod
  def signins_remaining(cls, user):
    plan = cls.get_by_name(user.plan)

    if plan.signin_limit == None:
      # Unlimited signins.
      return None
    remaining = max(0, plan.signin_limit - user.signins)

    return remaining

  """ Checks if the plan is full.
  Returns: True if the plan is full, False otherwise. """
  def is_full(self):
    self.__update_availability()
    return self.full

  """ Checks whether a user requesting this plan at the beginning of the signup
  process should be allowed to use it.
  name: The name of the plan being requested.
  user: The user requesting the plan, as returned by
  ProjectHandler.current_user. Can be None if no user is logged in.
  Returns: True if they can use the plan, False if they can't, None if no such
  plan exists. """
  @classmethod
  def can_subscribe(cls, name, user):
    try:
      plan = cls.get_by_name(name)
    except ValueError:
      # The plan doesn't exist. We shouldn't use it.
      return None

    if plan.is_full():
      logging.warning("Can't use plan '%s' because it's full." % (name))
      return False
    if plan.admin_only:
      if (not user or not user["is_admin"]):
        logging.warning("Only an admin can put someone on plan '%s'." % (name))
        return False

    return True

  """ Builds a list of the ids of all known plans.
  Returns: A list, where each item is a tuple. The first item in the tuple is
  the name of a plan, and the second is the ID of that plan. """
  @classmethod
  def get_all_plan_ids(cls):
    ids = []
    for plan in cls.all_plans:
      ids.append((plan.name, plan.plan_id))

    return ids


# Plans
newfull = Plan("newfull", 195, "The standard plan.",
               human_name="Standard")
newstudent = Plan("newstudent", 60, "A cheap plan for students.",
                  human_name="Student",
                  selectable=False)
newyearly = Plan("newyearly", 162, "Bills every year instead.",
                 human_name="Yearly")
newhive = Plan("newhive", 325, "You get a private desk too!",
               human_name="Premium", member_limit=Config().HIVE_MAX_OCCUPANCY,
               desk=True, selectable=False, admin_only=True)

full = Plan("full", 125, "The old standard plan.",
            human_name="Old Standard",
            legacy=newfull)
student = Plan("student", 50, "Old version of the student plan.",
               human_name="Old Student", aliases=["hardship"],
               legacy=newstudent)
supporter = Plan("supporter", 10, "A monthly donation to the dojo.",
                 human_name="Monthly Donation", signin_limit=0,
                 create_events=False)
family = Plan("family", 50, "Get a family discount.",
              human_name="Family",
              selectable=False, admin_only=True)
worktrade = Plan("worktrade", 0, "Free until we cancel it.",
                 human_name="Free Ride",
                 selectable=False, admin_only=True)
comped = Plan("comped", 0, "One year free.",
              human_name="Free Year",
              selectable=False, admin_only=True)
threecomp = Plan("threecomp", 0, "Three months free.",
                 human_name="Free Three Months",
                 selectable=False, admin_only=True)
yearly = Plan("yearly", 125, "Old yearly plan.",
              human_name="Old Yearly",
              legacy=newyearly)
fiveyear = Plan("fiveyear", 83.33, "Pay for five years now.",
                human_name="Five Years")
hive = Plan("Hive", 275, "Old premium plan.",
            human_name="Old Premium", member_limit=Config().HIVE_MAX_OCCUPANCY,
            aliases=["thielcomp"],
            legacy=newhive, desk=True)
lite = Plan("lite", 100, "A limited but cheaper plan.",
            signin_limit=Config().LITE_VISITS, create_events=False)
cleaners = Plan("cleaners", 0, 0,
                "A special plan to allow the cleaners access to the dojo.",
                selectable=False, admin_only=True)
