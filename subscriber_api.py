from datetime import datetime, date, time, timedelta
import logging
import urllib

from google.appengine.api import mail, urlfetch, taskqueue

import dateutil.parser

from config import Config
import keymaster
import plans
import spreedly


""" Suspend the requested user.
username: The username of the user to suspend. """
def suspend(username):
  conf = Config()
  if conf.is_testing:
    # Don't do this if we're testing.
    return

  def fail(exception):
    mail.send_mail(sender=conf.EMAIL_FROM,
        to=conf.INTERNAL_DEV_EMAIL,
        subject="[%s] User suspension failure: %s" % (conf.APP_NAME, username),
        body=str(exception))
    logging.error("User suspension failure: %s" % (exception))

  try:
    resp = urlfetch.fetch("http://%s/suspend/%s" % \
        (conf.DOMAIN_HOST, username),
        method="POST", deadline=10,
        payload=urllib.urlencode({"secret": keymaster.get("api")}),
        follow_redirects=False)
  except IOError as e:
    return fail(e)

""" Restore the requested user.
username: The username of the user to restore. """
def restore(username):
  conf = Config()
  if conf.is_testing:
    # Don't do this if we're testing.
    return

  def fail(exception):
    mail.send_mail(sender=conf.EMAIL_FROM,
        to=conf.INTERNAL_DEV_EMAIL,
        subject="[%s] User restore failure: " % (conf.APP_NAME, username),
        body=str(exception))
    logging.error("User restore failure: %s" % (exception))
  try:
    resp = urlfetch.fetch("http://%s/restore/%s" % \
        (conf.DOMAIN_HOST, username),
        method="POST", deadline=10,
        payload=urllib.urlencode({"secret": keymaster.get("api")}),
        follow_redirects=False)
  except Exception, e:
    return fail(e)

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
  api = spreedly.Spreedly(conf.SPREEDLY_ACCOUNT, token=conf.SPREEDLY_APIKEY)
  subscriber = api.subscriber_details(sub_id=int(member.key().id()))
  logging.debug("subscriber_info: %s" % (subscriber))

  if member.status == "paypal":
    mail.send_mail(sender=conf.EMAIL_FROM,
    to=conf.PAYPAL_EMAIL,
    subject="Please cancel PayPal subscription for %s" % member.full_name(),
    body=member.email)

  update_plan(subscriber, member)

  if (member.status in ("active", "no_visits") and not member.domain_user):
    if not member.password:
      # In this case, it pulled an old datastore entry and updated the schema,
      # which defaulted the password value. In this case, there is nothing we can
      # really do besides exiting gracefully, because we have permanently lost the
      # username and password values.
      logging.warning("Cannot handle old member with expired login info: %s." % \
                      (member.email))
      # Set domain_user so that it stops bothering us.
      member.domain_user = True

    else:
      taskqueue.add(url="/tasks/create_user", method="POST",
                    params={"hash": member.hash,
                            "username": member.username,
                            "password": member.password},
                    countdown=3)

  if member.status in ("active", "no_visits") and member.unsubscribe_reason:
    member.unsubscribe_reason = None

  member.spreedly_token = subscriber["token"]
  member.plan = subscriber["feature-level"] or member.plan

  member.put()

  # TODO: After a few months (now() = 06.13.2011), only suspend/restore if
  # status CHANGED. As of right now, we can't trust previous status, so lets
  # take action on each call to /update
  if member.status == "active" and member.domain_user:
    logging.info("Restoring User: %s" % (member.username))
    restore(member.username)
  if member.status == "suspended" and member.domain_user:
    logging.info("Suspending User: %s" % (member.username))
    suspend(member.username)

  return ((member.status in ("active", "no_visits")), member.plan)
