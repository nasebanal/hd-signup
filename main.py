from cgi import escape
import base64
import json
import sys

import datetime, hashlib, urllib, re
from google.appengine.api import urlfetch, mail, taskqueue
from google.appengine.ext import db

from config import Config
from list_pages import *
from login import *
from membership import Membership
from project_handler import ProjectHandler, BaseApp
from select_plan import *
import keymaster
import logging
import plans
import subscriber_api


class UsedCode(db.Model):
  email = db.StringProperty()
  created = db.DateTimeProperty(auto_now_add=True)
  code = db.StringProperty()
  extra = db.StringProperty()
  completed = db.DateTimeProperty()


class BadgeChange(db.Model):
    created = db.DateTimeProperty(auto_now_add=True)
    rfid_tag = db.StringProperty()
    username = db.StringProperty()
    description = db.StringProperty(multiline=True)


class MainHandler(ProjectHandler):
  """ Goes on to the appropriate next step in the signup process.
  plan: The plan we are using. """
  def __continue(self, plan):
    logging.debug("Using plan: %s" % (plan))

    if plan == "choose":
      # Have the user select a plan.
      self.redirect("/plan")
    else:
      # A plan was specified for us, so go on to creating the account.
      logging.info("Got plan '%s', skipping plan selection step." % (plan))
      query = urllib.urlencode({"plan": plan})
      self.redirect("/account/?%s" % (query))

  def get(self):
    # Whether to ignore an existing session.
    plan = self.request.get("plan", "choose")

    if plan != "choose":
      # A plan was specified. Make sure it's valid.
      valid = plans.Plan.can_subscribe(plan, self.current_user())
      if valid == None:
        # Nonexistent plan. Just ignore it.
        plan = "choose"
      elif valid == False:
        # Bad plan. Show error, and give users a chance to authenticate as an
        # admin.
        login_url = self.create_login_url(self.request.uri)
        self.response.out.write(self.render("templates/error.html",
                                internal=False,
                                message="Plan '%s' is not available for you. \
                                <br><a href=%s>Login as someone else.</a>" % \
                                    (plan, login_url)))
        self.response.set_status(422)
        return

    cookie_values = {"plan": plan}
    self.response.set_cookie("signup_progress", json.dumps(cookie_values))

    self.response.out.write(self.render("templates/main.html"))

  def post(self):
    first_name = self.request.get("first_name")
    last_name = self.request.get("last_name")
    twitter = self.request.get("twitter").lower().strip().strip("@")
    email = self.request.get("email").lower().strip()

    cookie_values = self.request.cookies.get("signup_progress")
    cookie_values = json.loads(cookie_values)
    plan = cookie_values["plan"]

    if not first_name or not last_name or not email:
      self.response.out.write(self.render("templates/main.html",
          message="Sorry, we need name and email address."))
      self.response.set_status(400)
      return

    membership = Membership.get_by_email(email)

    if membership:
      # A membership object already exists in the datastore.
      if membership.status == "suspended":
        self.response.out.write(self.render("templates/main.html",
            message="Your account has been suspended." \
            " <a href=\"/reactivate\">Click here</a> to reactivate."))
        self.response.set_status(422)
        return
      elif membership.status in ("active", "no_visits"):
        self.response.out.write(self.render("templates/main.html",
                                message="Account already exists."))
        self.response.set_status(422)
        return
      elif (membership.plan and not membership.spreedly_token):
        # They've already filled out everything, but they haven't started a
        # subscription. Take them to the PinPayments page.
        logging.info("Taking user %s directly to PinPayments page." %
                      (membership.email))
        self.redirect(membership.new_subscribe_url(self.request.host))
        return

    else:
      # Save our data.
      cookie_values["first_name"] = first_name
      cookie_values["last_name"] = last_name
      cookie_values["email"] = email
      cookie_values["twitter"] = twitter

    cookie_values["hash"] = hashlib.md5(email).hexdigest()
    if "1337" in self.request.get("referrer").upper():
      cookie_values["referrer"] = re.sub("[^0-9]", "",
          self.request.get("referrer").upper())
    else:
      cookie_values["referrer"] = \
          self.request.get("referrer").replace("\n", " ")

    self.response.set_cookie("signup_progress", json.dumps(cookie_values))
    self.__continue(plan)

class AccountHandler(ProjectHandler):
    def get(self):
      cookie_values = self.request.cookies.get("signup_progress")
      cookie_values = json.loads(cookie_values)

      # Save the plan they want.
      plan = self.request.get("plan", "newfull")
      cookie_values["plan"] = plan
      self.response.set_cookie("signup_progress", json.dumps(cookie_values))

      # Check to see if we already created a user. It is a security
      # risk to allow them to set their password again.
      membership = Membership.get_by_email(cookie_values["email"])
      if membership:
        logging.info("Not allowing password reentry.")
        # Send them directly to PinPayments.
        self.redirect(membership.new_subscribe_url(self.request.host,
                                                   plan=plan))
        return

      self.response.out.write(self.render("templates/account.html", locals()))

    def post(self):
        password = self.request.get("password")
        cookie_values = self.request.cookies.get("signup_progress")
        cookie_values = json.loads(cookie_values)
        plan_object = plans.Plan.get_by_name(cookie_values["plan"])

        # Do a final check to make sure we're not overwriting anything.
        existing_user = Membership.get_by_email(cookie_values["email"])
        if existing_user:
          logging.critical("Duplicate user %s detected!" % \
              (cookie_values["email"]))

          self.response.delete_cookie("signup_progress")
          self.response.set_status(422)
          response = self.render("templates/error.html",
              message="This email is already in use.")
          self.response.out.write(response)
          return

        # Create the user.
        logging.info("Creating new user: %s" % (cookie_values))
        membership = Membership.create_user(cookie_values["email"],
            password, first_name=cookie_values["first_name"],
            last_name=cookie_values["last_name"],
            hash=cookie_values["hash"],
            plan=cookie_values["plan"],
            referrer=cookie_values.get("referrer"),
            twitter=cookie_values.get("twitter"))

        customer_id = membership.get_id()

        # All our giftcards start out with 1337.
        if (membership.referrer and "1337" in membership.referrer):
            conf = Config()

            if len(membership.referrer) != 16:
                message = "<p>Error: code must be 16 digits."
                message += "<p>Please contact %s if you believe this \
                          message is in error and we can help!" % \
                          (conf.SIGNUP_HELP_EMAIL)
                message += "<p><a href=\"/\">Start again</a>"
                internal = False
                self.response.out.write(self.render("templates/error.html", locals()))
                self.response.set_status(422)
                return

            # A unique number on all the giftcards.
            serial = membership.referrer[4:8]
            # How we know it's valid.
            hash = membership.referrer[8:16]
            confirmation_hash = re.sub("[a-f]","",hashlib.sha1(serial+keymaster.get("code:hash")).hexdigest())[:8]

            if hash != confirmation_hash:
                message = "<p>Error: this code was invalid: %s" % \
                    (membership.referrer)
                message += "<p>Please contact %s if you believe this \
                          message is in error and we can help!" % \
                          (conf.SIGNUP_HELP_EMAIL)
                message += "<p><a href=\"/\">Start again</a>"
                internal = False
                uc = UsedCode(code=membership.referrer,email=membership.email,extra="invalid code")
                uc.put()
                self.response.out.write(self.render("templates/error.html", locals()))
                self.response.set_status(422)
                return

            previous = UsedCode.all().filter("code =", membership.referrer).get()
            if previous:
                message = "<p>Error: this code has already been used: "+ membership.referrer
                message += "<p>Please contact %s if you believe this" \
                            " message is in error and we can help!" % \
                            (conf.SIGNUP_HELP_EMAIL)
                message += "<p><a href=\"/\">Start again</a>"
                internal = False
                uc = UsedCode(code=membership.referrer,email=membership.email,extra="2nd+ attempt")
                uc.put()
                self.response.out.write(self.render("templates/error.html", locals()))
                self.response.set_status(422)
                return

            # If we're testing, I don't want it doing random things on
            # pinpayments.
            if not conf.is_testing:
              headers = {"Authorization": "Basic %s" % \
                  base64.b64encode("%s:X" % conf.get_api_key()),
                  "Content-Type":"application/xml"}
              # Create subscriber
              data = "<subscriber><customer-id>%s</customer-id><email>%s</email></subscriber>" % (customer_id, membership.email)
              resp = \
                  urlfetch.fetch("https://subs.pinpayments.com"
                                 "/api/v4/%s/subscribers.xml" % \
                                 (conf.SPREEDLY_ACCOUNT),
                                 method="POST", payload=data,
                                 headers = headers, deadline=5)
              # Credit
              data = "<credit><amount>95.00</amount></credit>"
              resp = \
                  urlfetch.fetch("https://subs.pinpayments.com/api/v4"
                                 "/%s/subscribers/%s/credits.xml" % \
                                 (conf.SPREEDLY_ACCOUNT, customer_id),
                                 method="POST", payload=data,
                                 headers=headers, deadline=5)

            uc = UsedCode(code=membership.referrer,email=membership.email,extra="OK")
            uc.put()

        # Update the cookie.
        cookie_values["pin_payments"] = True
        self.response.set_cookie("signup_progress", json.dumps(cookie_values))
        # Redirect them to the PinPayments page, where they actually pay.
        self.redirect(membership.new_subscribe_url(self.request.host,
                                                   plan=cookie_values["plan"]))


class UnsubscribeHandler(ProjectHandler):
    def get(self, id):
        member = Membership.get_by_id(int(id))
        if member:
            self.response.out.write(self.render("templates/unsubscribe.html", locals()))
        else:
            self.response.out.write("error: could not locate your membership record.")

    def post(self,id):
        member = Membership.get_by_id(int(id))
        if member:
            unsubscribe_reason = self.request.get("unsubscribe_reason")
            if unsubscribe_reason:
                member.unsubscribe_reason = unsubscribe_reason
                member.put()
                self.response.out.write(self.render("templates/unsubscribe_thanks.html", locals()))
            else:
                self.response.out.write(self.render("templates/unsubscribe_error.html", locals()))
        else:
            self.response.out.write("error: could not locate your membership record.")


class SuccessHandler(ProjectHandler):
    """ Sends the welcome email to the specified person.
    handler: The handler that is sending the email. (ProjectHandler)
    member: The member that will receive the email. (Membership) """
    @classmethod
    def send_email(cls, handler, member):
      spreedly_url = member.spreedly_url()
      dojo_email = "%s@hackerdojo.com" % (member.username)
      name = member.full_name()
      mail.send_mail(sender=Config().EMAIL_FROM,
          to="%s <%s>; %s <%s>" % (name, member.email, name, dojo_email),
          subject="Welcome to Hacker Dojo, %s!" % member.first_name,
          body=handler.render("templates/welcome.txt", locals()))

    def get(self, hash):
        member = Membership.get_by_hash(hash)
        conf = Config()
        if member:
          success_html = urlfetch.fetch(conf.SUCCESS_HTML_URL).content
          success_html = success_html.replace("joining!", "joining, %s!" % member.first_name)
          is_prod = conf.is_prod
          self.response.out.write(self.render("templates/success.html", locals()))


class NeedAccountHandler(ProjectHandler):
    def get(self):
        message = escape(self.request.get("message"))
        self.response.out.write(self.render("templates/needaccount.html", locals()))

    def post(self):
        email = self.request.get("email").lower()
        if not email:
            self.redirect(str(self.request.path))
        else:
            member = Membership.all().filter("email =", email).filter("status =", "active").get()
            if not member:
                self.redirect(str(self.request.path + "?message=There is no active record of that email."))
            else:
                mail.send_mail(sender=Config().EMAIL_FROM,
                    to="%s <%s>" % (member.full_name(), member.email),
                    subject="Create your Hacker Dojo account",
                    body="""Hello,\n\nHere"s a link to create your Hacker Dojo account:\n\nhttp://%s/account/%s""" % (self.request.host, member.hash))
                sent = True
                self.response.out.write(self.render("templates/needaccount.html", locals()))


class UpdateHandler(ProjectHandler):
    def post(self):
        subscriber_ids = self.request.get("subscriber_ids").split(",")
        for id in subscriber_ids:
          logging.debug("Updating subscriber with id %s." % id)
          subscriber_api.update_subscriber(Membership.get_by_id(int(id)))

        self.response.out.write("ok")


class SuspendedHandler(ProjectHandler):
    @ProjectHandler.admin_only
    def get(self):
      suspended_users = Membership.all().filter("status =", "suspended").filter("last_name !=", "Deleted").fetch(10000)
      tokened_users = []
      for user in suspended_users:
          if user.spreedly_token:
              tokened_users.append(user)
      suspended_users = sorted(tokened_users, key=lambda user: user.last_name.lower())
      total = len(suspended_users)
      reasonable = 0
      for user in suspended_users:
          if user.unsubscribe_reason:
              reasonable += 1
      self.response.out.write(self.render("templates/suspended.html", locals()))


class AllHandler(ProjectHandler):
    @ProjectHandler.admin_only
    def get(self):
      signup_users = Membership.all().fetch(10000)
      signup_users = sorted(signup_users, key=lambda user: user.last_name.lower())
      user_keys = [str(user.key()) for user in signup_users]
      user_ids = [user.key().id() for user in signup_users]
      self.response.out.write(self.render("templates/users.html", locals()))


class HardshipHandler(ProjectHandler):
    @ProjectHandler.admin_only
    def get(self):
      active_users = Membership.all().filter("status =", "active").filter("plan =", "hardship").fetch(10000)
      active_users = sorted(active_users, key=lambda user: user.created)
      subject = "About your Hacker Dojo membership"
      body1 = "\n\nWe hope you have enjoyed your discounted membership at \
              Hacker Dojo.  As you\nknow, we created the hardship program \
              to give temporary financial support to help\nmembers get \
              started at the Dojo. Our records show you began the program\n \
              on"
      body2 = ", and we hope you feel that you have benefited.\n\nBeginning \
              with your next month's term, we ask that you please sign up \
              at\nour regular rate:\n"
      body3 = "\n\nThank you for supporting the Dojo!"
      self.response.out.write(self.render("templates/hardship.html", locals()))


class ReactivateHandler(ProjectHandler):
    def get(self):
        message = escape(self.request.get("message"))
        self.response.out.write(self.render("templates/reactivate.html", locals()))

    def post(self):
        email = self.request.get("email").lower()
        existing_member = \
            db.GqlQuery("SELECT * FROM Membership WHERE email = :email",
            email=email).get()
        if existing_member:
            membership = existing_member

            if membership.status == "active":
              self.redirect("%s?message=You are still an active member." % \
                            (self.request.path))
            elif membership.status == "no_visits":
              self.redirect("%s?message=Your plan is active, but you need to" \
                            " upgrade it." % (self.request.path))
            else:
              subject = "Reactivate your Hacker Dojo Membership"
              reactivate_url = "%s/reactivate_plan/%s" % (self.request.host_url,
                                                          membership.hash)
              body = self.render("templates/reactivate.txt", locals())
              to = "%s <%s>" % (membership.full_name(), membership.email)
              bcc = "%s <%s>" % ("Billing System", "robot@hackerdojo.com")
              mail.send_mail(sender=Config().EMAIL_FROM_AYST, to=to,
                             subject=subject, body=body, bcc=bcc)
              sent = True
              self.response.out.write(self.render("templates/reactivate.html", locals()))
        else:
            self.redirect(str(self.request.path + "?message=There is no record of that email."))


class ProfileHandler(ProjectHandler):
  @ProjectHandler.login_required
  def get(self):
    current_user = self.current_user()
    email = current_user["email"]
    account = Membership.get_by_email(email)
    gravatar_url = "http://www.gravatar.com/avatar/" + \
        hashlib.md5(email.lower()).hexdigest()
    self.response.out.write(self.render("templates/profile.html", locals()))

class KeyHandler(ProjectHandler):
  @ProjectHandler.login_required
  def get(self):
    user = self.current_user()
    conf = Config()
    message = escape(self.request.get("message"))
    account = Membership.get_by_email(user["email"])

    if account.status != "active":
        url = "https://subs.pinpayments.com/"+conf.SPREEDLY_ACCOUNT+"/subscriber_accounts/" + account.spreedly_token
        message = """<p>Your Spreedly account status does not appear to me marked as active. This might be a mistake, in which case we apologize. </p>
        <p>To investigate your account, you may go here: <a href=\"%(url)s\">%(url)s</a> </p>
        <p>If you believe this message is in error, please contact <a href=\"mailto:%(signup_email)s?Subject=Spreedly+account+not+linked+to+account\">%(signup_email)s</a></p>
        """ % {"url": url, "signup_email": conf.SIGNUP_HELP_EMAIL}
        internal = False
        self.response.out.write(self.render("templates/error.html", locals()))
        return
    delta = datetime.datetime.utcnow() - account.created
    if delta.days < conf.DAYS_FOR_KEY:
        message = """<p>You have been a member for %(deltadays)s days.
        After %(days)s days you qualify for a key.  Check back in %(delta)s days!</p>
        <p>If you believe this message is in error, please contact <a href=\"mailto:%(signup_email)s?Subject=Membership+create+date+not+correct\">%(signup_email)s</a>.</p>
        """ % {"deltadays": delta.days, "days": conf.DAYS_FOR_KEY,
                "delta": conf.DAYS_FOR_KEY - delta.days,
                "signup_email": SIGNUP_HELP_EMAIL}
        internal = False
        self.response.out.write(self.render("templates/error.html", locals()))
        return
    bc = BadgeChange.all().filter("username =", account.username).fetch(100)
    pp = account.parking_pass
    self.response.out.write(self.render("templates/key.html", locals()))

  @ProjectHandler.login_required
  def post(self):
    user = self.current_user()
    account = Membership.get_by_email(user["email"])
    if not account or not account.spreedly_token or account.status != "active":
          message = "Error #1982, which should never happen."
          internal = True
          self.response.out.write(self.render("templates/error.html", locals()))
          return
    is_park = self.request.get("ispark")
    if is_park == "True": #checks if user input is a parking pass number or an rfid number
      pass_to_add = self.request.get("parking_pass")
      try: #tests if there are only numbers in the parking pass
        float(pass_to_add)
      except ValueError:
        message = "<p>A Parking Pass may only contain numbers.</p><a href=\"/key\">Try Again</a>"
        internal = False
        self.response.out.write(self.render("templates/error.html", locals()))
        return
      account.parking_pass = pass_to_add

      logging.debug("Setting parking pass for %s to %s." % \
                    (account.full_name(), account.parking_pass))

      db.put(account)
      self.response.out.write(self.render("templates/pass_ok.html", locals())) #outputs the parking number
    else:
      rfid_tag = self.request.get("rfid_tag").strip()
      description = self.request.get("description").strip()
      if rfid_tag.isdigit():
        if Membership.all().filter("rfid_tag =", rfid_tag).get():
          message = "<p>That RFID tag is in use by someone else.</p>"
          internal = False
          self.response.out.write(self.render("templates/error.html", locals()))
          return
        if not description:
          message = "<p>Please enter a reason why you are associating a replacement RFID key.  Please hit BACK and try again.</p>"
          internal = False
          self.response.out.write(self.render("templates/error.html", locals()))
          return
        account.rfid_tag = rfid_tag

        logging.debug("Setting RFID for %s to %s." % (account.full_name(),
                                                      account.rfid_tag))

        account.put()
        bc = BadgeChange(rfid_tag = rfid_tag, username=account.username, description=description)
        bc.put()
        self.response.out.write(self.render("templates/key_ok.html", locals()))
        return
      else:
        message = "<p>That RFID ID seemed invalid. Hit back and try again.</p>"
        internal = False
        self.response.out.write(self.render("templates/error.html", locals()))
        return


class GenLinkHandler(ProjectHandler):
    @ProjectHandler.admin_only
    def get(self, key):
      conf = Config()
      sa = conf.SPREEDLY_ACCOUNT
      u = Membership.get_by_id(int(key))
      plan_ids = plans.Plan.get_all_plan_ids()
      self.response.out.write(self.render("templates/genlink.html", locals()))


app = BaseApp([
        ("/", MainHandler),
        ("/userlist", AllHandler),
        ("/suspended", SuspendedHandler),
        ("/profile", ProfileHandler),
        ("/key", KeyHandler),
        ("/genlink/(.+)", GenLinkHandler),
        ("/account", AccountHandler),
        ("/upgrade/needaccount", NeedAccountHandler),
        ("/success/(.+)", SuccessHandler),
        ("/leavereasonlist(.*)", LeaveReasonListHandler),
        ("/hardshiplist", HardshipHandler),
        ("/memberlist(.*)", MemberListHandler),
        ("/unsubscribe/(.*)", UnsubscribeHandler),
        ("/update", UpdateHandler),
        ("/reactivate", ReactivateHandler),
        ("/plan", SelectPlanHandler),
        ("/change_plan", ChangePlanHandler),
        ("/reactivate_plan/(.+)", ReactivatePlanHandler),
        ("/login", LoginHandler),
        ("/logout", LogoutHandler),
        ("/forgot_password", ForgottenPasswordHandler),
        ("/reset_password", PasswordResetHandler),
        ("/validate_token", ValidateTokenHandler),
        ], debug=True)
