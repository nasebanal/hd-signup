from datetime import datetime, date, time, timedelta
import logging
import urllib

from google.appengine.api import mail, urlfetch, taskqueue

import dateutil.parser

from config import Config
from membership import Membership
import keymaster
import plans
import spreedly


""" Notifies the events app of the requested user's suspension.
email: The email of the user to suspend. """
def notify_suspend(email):
  if Config().is_testing:
    # Don't do this if we're testing.
    return

  # Alert the events app that the user's status has changed.
  query = {"email": email, "status": "suspended"}
  response = urlfetch.fetch("http://%s/api/v1/status_change" % \
                            (conf.EVENTS_HOST), method="POST",
                            payload=urllib.urlencode(query),
                            follow_redirects=False)

  if response.status_code != 200:
    logging.warning("Notifying events app failed.")

""" Notifies the events app of the requested user's restoration.
email: The email of the user to restore. """
def notify_restore(email):
  if Config().is_testing:
    # Don't do this if we're testing.
    return

  # Alert the events app that the user's status has changed.
  query = {"email": email, "status": "active"}
  response = urlfetch.fetch("http://%s/api/v1/status_change" % \
                            (conf.EVENTS_HOST), method="POST",
                            payload=urllib.urlencode(query),
                            follow_redirects=False)

  if response.status_code != 200:
    logging.warning("Notifying events app failed.")

""" Handle PinPayments XML data for a particular subscriber, updating the
corresponding membership instance to be on the proper plan and have the
proper status.
subscriber: The input dictionary to interpret from the XML response.
member: The membership object to update. """
def update_plan(subscriber, member):
  if subscriber["active"] == "true":
    # Membership is active.
    if (not member.status or member.status == "suspended"):
      member.status = "active"
  else:
    # Membership is not active.
    member.status = "suspended"

    plan = plans.Plan.get_by_name(member.plan)

    if plan.legacy:
      # If they are on a legacy plan, we have to figure out
      # whether they can stay on it.
      if subscriber["ready-to-renew"] == "true":
        # Membership wasn't cancelled, it expired.
        # Figure out how long ago it expired.
        expire_date = \
            dateutil.parser.parse(
                subscriber["ready-to-renew-since"])
        expired_time = datetime.now() - expire_date.replace(tzinfo=None)
        logging.debug("Plan expired for %s" % (str(expired_time)))

        if expired_time >= timedelta(30):
          # If it expired more than 30 days ago, we are
          # not even going to consider giving them the
          # legacy rate again.
          logging.info("Not renewing legacy plan for %s"
                       " due to excessive wait time." %
                       (member.username))
          member.plan = plan.get_legacy_pair().name
      else:
        # Membership was cancelled. In this case, they don't
        # get to stay on the legacy plan.
        logging.info("Not renewing legacy plan for %s because"
                     " it was cancelled." % (member.username))
        member.plan = plan.get_legacy_pair().name

""" Gets the data from PinPayments for a particular subscriber and updates
their status accordingly.
member: The Membership object we are updating.
Returns: True if the member is active,
    False otherwise, and the plan of the member. """
def update_subscriber(member):
  if not member:
    return

  conf = Config()
  api = spreedly.Spreedly(conf.SPREEDLY_ACCOUNT, token=conf.get_api_key())
  subscriber = api.subscriber_details(sub_id=int(member.key().id()))
  logging.debug("subscriber_info: %s" % (subscriber))

  if member.status == "paypal":
    mail.send_mail(sender=conf.EMAIL_FROM,
    to=conf.PAYPAL_EMAIL,
    subject="Please cancel PayPal subscription for %s" % member.full_name(),
    body=member.email)

  # Save their old status.
  old_status = member.status

  update_plan(subscriber, member)

  # TODO (daniep): Deal with people who haven't yet migrated to new-style
  # accounts here.

  if member.status in ("active", "no_visits") and member.unsubscribe_reason:
    member.unsubscribe_reason = None

  member.spreedly_token = subscriber["token"]
  member.plan = subscriber["feature-level"] or member.plan

  member.put()

  if member.status != old_status:
    if member.status == "active":
      logging.info("Restoring User: %s" % (member.username))
      notify_restore(member.email)
    if member.status == "suspended" and member.domain_user:
      logging.info("Suspending User: %s" % (member.username))
      notify_suspend(member.email)

  return ((member.status in ("active", "no_visits")), member.plan)
