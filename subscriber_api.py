from datetime import datetime, date, time, timedelta
import logging

import dateutil.parser

from config import Config

""" Suspend the requested user.
username: The username of the user to suspend. """
def suspend(username):
  conf = Config()

  def fail(exception):
    mail.send_mail(sender=conf.EMAIL_FROM,
        to=conf.INTERNAL_DEV_EMAIL,
        subject="[%s] User suspension failure: " % (conf.APP_NAME, username),
        body=str(exception))
    logging.error("User suspension failure: %s" % (exception))

  try:
    resp = urlfetch.fetch("http://%s/suspend/%s" % \
        (conf.DOMAIN_HOST, username),
        method="POST", deadline=10,
        payload=urllib.urlencode({"secret": keymaster.get("api")}))
  except Exception, e:
    return fail(e)

""" Restore the requested user.
username: The username of the user to restore. """
def restore(username):
  conf = Config()

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
        payload=urllib.urlencode({"secret": keymaster.get("api")}))
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
    member.status = "active"
  else:
    # Membership is not active.
    member.status = "suspended"

    if member.plan == "full":
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
          member.plan = "newfull"
      else:
        # Membership was cancelled. In this case, they don't
        # get to stay on the legacy plan.
        logging.info("Not renewing legacy plan for %s because"
                     " it was cancelled." % (member.username))
        member.plan = "newfull"

""" Gets the data from PinPayments for a particular subscriber and updates
their status accordingly.
subscriber_id: The id token of the subscriber.
Returns: True if the member is active,
    False otherwise, and the plan of the member. """
def update_subscriber(subscriber_id):
  conf = Config()
  api = spreedly.Spreedly(conf.SPREEDLY_ACCOUNT, token=conf.SPREEDLY_APIKEY)
  subscriber = api.subscriber_details(sub_id=int(subscriber_id))
  logging.debug("subscriber_info: %s" % (subscriber))
  logging.debug("customer_id: "+ subscriber["customer-id"])

  member = Membership.get_by_id(int(subscriber["customer-id"]))
  if member:
    if member.status == "paypal":
      mail.send_mail(sender=conf.EMAIL_FROM,
      to=conf.PAYPAL_EMAIL,
      subject="Please cancel PayPal subscription for %s" % member.full_name(),
      body=member.email)

    cls.update_plan(subscriber, member)

    if member.status == "active" and not member.username:
      taskqueue.add(url="/tasks/create_user", method="POST",
                    params={"hash": member.hash}, countdown=3)
    if member.status == "active" and member.unsubscribe_reason:
      member.unsubscribe_reason = None

    member.spreedly_token = subscriber["token"]
    member.plan = subscriber["feature-level"] or member.plan
    if not subscriber["email"]:
      subscriber["email"] = "noemail@hackerdojo.com"
    member.email = subscriber["email"]

    member.put()

    # TODO: After a few months (now() = 06.13.2011), only suspend/restore if
    # status CHANGED. As of right now, we can't trust previous status, so lets
    # take action on each call to /update
    if member.status == "active" and member.username:
      logging.info("Restoring User: " + member.username)
      cls.restore(member.username)
    if member.status == "suspended" and member.username:
      logging.info("Suspending User: " + member.username)
      cls.suspend(member.username)

    return ((member.status == "active"), member.plan)

