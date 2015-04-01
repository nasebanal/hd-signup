""" Tests for the signup page. """

import datetime
import unittest

from google.appengine.ext import testbed

from membership import Membership
from main import UpdateHandler


""" Simulates responses from the pinpayments API. """
class PinPaymentsApiSimulator:
  """ Base subscriber info. """
  subscriber_info = {u'eligible-for-free-trial': u'false',
                     u'on-metered': u'false',
                     u'payment-account-on-file': u'true',
                     u'card-expires-before-next-auto-renew': u'false',
                     u'store-credit': u'0.0',
                     u'lifetime-subscription': u'false',
                     u'subscription-plan-version': {u'description': None,
                         u'currency-code': u'USD', u'plan-type': u'regular',
                         u'feature-level': u'full', u'return-url':
                         u'http://hackerdojo.pbworks.com/SubscriptionSuccess',
                         u'amount': u'100.0', u'version': u'1', u'name':
                         u'Full Membership', u'id': u'3842',
                         u'setup-fee-currency-code': u'USD',
                         u'needs-to-be-renewed': 'setme',
                         u'minimum-needed-for-charge': u'0.0',
                         u'terms': u'1 month',
                         u'subscription-plan-id': u'1957',
                         u'charge-later-duration-quantity': None,
                         u'force-recurring': u'true',
                         u'setup-fee-description': None,
                         u'duration-units': u'months',
                         u'setup-fee-amount': u'0.0',
                             u'updated-at': u'2013-09-04T23:44:45Z',
                         u'duration-quantity': u'1',
                         u'created-at': u'2009-09-04T23:44:45Z',
                         u'charge-later-duration-units': None,
                         u'enabled': u'true',
                         u'charge-after-first-period': u'false'},
                     u'grace-until': u'2010-04-19T19:54:25Z',
                     u'billing-last-name': 'setme', u'ready-to-renew': 'setme',
                     u'on-trial': u'false', u'active': 'setme',
                     u'billing-zip': None, u'billing-country': None,
                     u'expired-at': 'setme', u'token':
                     u'8dab5cfcc30d55255f9c2a5145f7a7b007fcb489',
                     u'customer-id': u'5629499534213120',
                     u'invoices': {u'invoice': {u'price': u'$100.00',
                              u'recurring-amount': u'0',
                              u'updated-at': u'2013-04-19T18:28:51Z',
                              u'token': \
                              u'7bb4e988a9264c3029443949b884413b41b90edb',
                              u'closed': u'true',
                              u'created-at': u'2013-04-19T18:28:41Z',
                              u'line-items': {u'line-item': {u'notes': None,
                                      u'description': u'Every 1 month',
                                      u'price': u'$100.00',
                                      u'currency-code': u'USD',
                                      u'metadata': u'full',
                                      u'feature-level': u'full',
                                      u'one-time': None,
                                      u'amount': u'100.0'}},
                              u'currency-code': u'USD', u'metadata': u'full',
                              u'response-customer-message': None,
                              u'gateway-transaction-reference': \
                                  u'SpreedlyGateway#purchase',
                              u'response-client-message': None,
                              u'response-message': None,
                              u'title': u'Full Membership',
                              u'amount': u'100.0'}},
                     u'email': 'setme', u'active-until': 'setme', u'in-grace-period': u'false',
                     u'ready-to-renew-since': 'setme', u'on-gift': u'false',
                     u'store-credit-currency-code':
                     u'USD', u'billing-first-name': u'asdf',
                     u'pagination-id': u'1200339', u'billing-address1': None,
                     u'payment-account-display': u'Valid test Visa',
                     u'eligible-for-setup-fee': u'true', u'billing-state': None,
                     u'updated-at': 'setme', u'billing-phone-number': None,
                     u'subscription-plan-name': u'Full Membership',
                     u'created-at': u'2013-04-19T18:28:41Z',
                     u'billing-city': None, u'screen-name': 'setme',
                     u'recurring': u'true', u'feature-level': u'full'}

  """ Sets a particular key in the subscriber info dictionary.
  info: The dictionary we are working with.
  key: The key that we are setting.
  value: The value that we are setting it to. """
  def set_key(self, info, key, value):
    if value == None:
      info[key] = value
    else:
      if value == True:
        value = "true"
      elif value == False:
        value = "false"

      value = str(value)
      info[key] = value

  """ Return a dict for a subscription query.
  member: The member instance representing the subsriber.
  days_since_payment: How many days it's been since we made a subscription
  payment.
  cancelled: Whether the user cancelled the plan.
  Returns: The generated dict representing the info for this subscriber. """
  def generate_subscriber_info(self, member, days_since_payment,
      cancelled=False):
    last_payment = datetime.datetime.now() - \
        datetime.timedelta(days=days_since_payment)
    expires = last_payment + datetime.timedelta(days=30)
    last_payment = last_payment.isoformat()
    expires = expires.isoformat()

    active = days_since_payment < 30 if not cancelled else False
    should_renew = (not active and not cancelled)

    info = self.subscriber_info
    self.set_key(info, "needs-to-be-renewed", should_renew)
    self.set_key(info, "updated-at", last_payment)
    self.set_key(info, "ready-to-renew", should_renew)
    self.set_key(info, "ready-to-renew-since",
                 expires if not cancelled else None)
    self.set_key(info, "active", active)
    self.set_key(info, "expired-at",
                 None if (active or cancelled) else expires)
    self.set_key(info, "active-until", expires if active else None)

    self.set_key(info, "billing-last-name", member.last_name)
    self.set_key(info, "email", member.email)
    self.set_key(info, "screen-name", "%s.%s" % (member.first_name,
                                                 member.last_name))

    return info


""" Test case for the "update" URL endpoint. """
class UpdateTests(unittest.TestCase):
  """ Set up for every test. """
  def setUp(self):
    # Create and activate testbed instance.
    self.testbed = testbed.Testbed()
    self.testbed.activate()

    self.api_simulation = PinPaymentsApiSimulator()

    self.test_member = Membership(first_name = "Test", last_name = "Tester",
                                  email = "test@gmail.com", plan = "newfull")

  """ Cleanup for every test. """
  def tearDown(self):
    self.testbed.deactivate()

  """ Tests that Update sets the proper plan given when the member has paid. """
  def test_plan_update(self):
    update_handler = UpdateHandler()

    # This member is active and on the new plan. Nothing should change.
    member_info = self.api_simulation.generate_subscriber_info(
        self.test_member, 10)
    update_handler.update_plan(member_info, self.test_member)
    self.assertEqual("active", self.test_member.status)
    self.assertEqual("newfull", self.test_member.plan)

    # This member is active, so nothing should get messed with, even though they
    # are on the legacy plan.
    self.test_member.plan = "full"
    member_info = self.api_simulation.generate_subscriber_info(
        self.test_member, 10)
    update_handler.update_plan(member_info, self.test_member)
    self.assertEqual("active", self.test_member.status)
    self.assertEqual("full", self.test_member.plan)

    # This member has allowed their subscription to lapse.
    self.test_member.plan = "newfull"
    member_info = self.api_simulation.generate_subscriber_info(
        self.test_member, 40)
    update_handler.update_plan(member_info, self.test_member)
    self.assertEqual("suspended", self.test_member.status)
    self.assertEqual("newfull", self.test_member.plan)

    # This member has allowed their subscription to lapse, but has not yet lost
    # their chance to stay on the legacy plan.
    self.test_member.plan = "full"
    member_info = self.api_simulation.generate_subscriber_info(
        self.test_member, 40)
    update_handler.update_plan(member_info, self.test_member)
    self.assertEqual("suspended", self.test_member.status)
    self.assertEqual("full", self.test_member.plan)

    # This member has allowed their subscription to lapse, and missed their
    # chance to stay on the legacy plan.
    self.test_member.plan = "full"
    member_info = self.api_simulation.generate_subscriber_info(
        self.test_member, 60)
    update_handler.update_plan(member_info, self.test_member)
    self.assertEqual("suspended", self.test_member.status)
    self.assertEqual("newfull", self.test_member.plan)

    # This member cancelled their subscription.
    self.test_member.plan = "newfull"
    member_info = self.api_simulation.generate_subscriber_info(
        self.test_member, 10, cancelled=True)
    update_handler.update_plan(member_info, self.test_member)
    self.assertEqual("suspended", self.test_member.status)
    self.assertEqual("newfull", self.test_member.plan)

    # This member cancelled their subscription. They don't get to stay on the
    # legacy plan.
    self.test_member.plan = "full"
    member_info = self.api_simulation.generate_subscriber_info(
        self.test_member, 10, cancelled=True)
    update_handler.update_plan(member_info, self.test_member)
    self.assertEqual("suspended", self.test_member.status)
    self.assertEqual("newfull", self.test_member.plan)
