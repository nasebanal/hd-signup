from cgi import escape
import base64
import sys

import datetime, hashlib, urllib, re
from google.appengine.api import urlfetch, mail, users, taskqueue
from google.appengine.ext import db
import webapp2

from config import Config
from membership import Membership
from project_handler import ProjectHandler
from select_plan import SelectPlanHandler, ChangePlanHandler
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
    description = db.StringProperty()


class MainHandler(ProjectHandler):
    def get(self):
      plan = self.request.get("plan", "choose")

      if plan != "choose":
        # A plan was specified. Make sure it's valid.
        valid = plans.Plan.can_subscribe(plan)
        if valid == None:
          # Nonexistent plan. Just ignore it.
          plan = "choose"
        elif valid == False:
          # Bad plan. Show error.
          self.response.out.write(self.render("templates/error.html",
                                  internal=False,
                                  message="Plan '%s' is not available." % \
                                      (plan)))
          self.response.set_status(422)
          return

      self.response.out.write(self.render("templates/main.html", plan=plan))

    def post(self):
      first_name = self.request.get("first_name")
      last_name = self.request.get("last_name")
      twitter = self.request.get("twitter").lower().strip().strip("@")
      email = self.request.get("email").lower().strip()
      plan = self.request.get("plan")

      if not first_name or not last_name or not email:
        self.response.out.write(self.render("templates/main.html",
            message="Sorry, we need name and email address.", plan=plan))
        self.response.set_status(400)
        return

      membership = db.GqlQuery("SELECT * FROM Membership WHERE email = :email",
                               email=email).get()

      if membership:
        # A membership object already exists in the datastore.
        if membership.extra_dnd == True:
          self.response.out.write("Error #237.  Please contact signupops@hackerdojo.com")
          self.response.set_status(422)
          return
        if membership.status == "suspended":
          self.response.out.write(self.render("templates/main.html",
              message="Your account has been suspended." \
              " <a href=\"/reactivate\">Click here</a> to reactivate.",
              plan=plan))
          self.response.set_status(422)
          return
        elif membership.status in ("active", "no_visits"):
          self.response.out.write(self.render("templates/main.html",
                                  message="Account already exists.",
                                  plan=plan))
          self.response.set_status(422)
          return
        elif ((membership.username and membership.password) and not \
              membership.spreedly_token):
          self.response.out.write(self.render("templates/main.html",
              message="We're processing your payment. Be patient.", plan=plan))
          self.response.set_status(422)
          return
        else:
          # Existing membership never got activated. Overwrite it.
          logging.info("Overwriting existing membership for %s." % (email))

          membership.first_name = first_name
          membership.last_name = last_name
          membership.email = email
          membership.twitter = twitter
      else:
        # Make a new membership object.
        membership = Membership(
            first_name=first_name, last_name=last_name, email=email,
            twitter=twitter)

      if self.request.get("paypal") == "1":
        membership.status = "paypal"
      membership.hash = hashlib.md5(membership.email).hexdigest()
      if "1337" in self.request.get("referrer").upper():
        membership.referrer = re.sub("[^0-9]", "", self.request.get("referrer").upper())
      else:
        membership.referrer = self.request.get("referrer").replace("\n", " ")
      membership.put()

      logging.debug("Using plan: %s" % (plan))
      if plan == "choose":
        # Have the user select a plan.
        self.redirect("/plan/%s" % (membership.hash))
      else:
        # A plan was specified for us, so go on to creating the account.
        logging.info("Got plan '%s', skipping plan selection step." % (plan))
        query = urllib.urlencode({"plan": plan})
        self.redirect("/account/%s?%s" % (membership.hash, query))


class AccountHandler(ProjectHandler):
    def get(self, hash):
      membership = Membership.get_by_hash(hash)
      if not membership:
        self.response.set_status(422)
        self.response.out.write("Unknown member hash.")
        logging.error("Could not find member with hash '%s'." % (hash))
        return

      # Save the plan they want.
      plan = self.request.get("plan", "newfull")
      membership.plan = plan
      membership.put()

      if ((membership.username and membership.password) and not \
          membership.spreedly_token):
        # We've filled out our account information, but we never started a
        # subscription. (This could be reached by going back and trying to
        # change our plan after we were already taken to the PinPayments
        # page.) In this case, just pass them through to PinPayments.
        query_str = urllib.urlencode({"first_name": membership.first_name,
                                      "last_name": membership.last_name,
                                      "email": membership.email,
                                      "return_url": "http://%s/success/%s" % \
                                          (self.request.host, membership.hash)})
        self.redirect(membership.new_subscribe_url(query_str))

      # steal this part to detect if they registered with hacker dojo email above
      first_part = re.compile(r"[^\w]").sub("", membership.first_name.split(" ")[0]) # First word of first name
      last_part = re.compile(r"[^\w]").sub("", membership.last_name)
      if len(first_part)+len(last_part) >= 15:
          last_part = last_part[0] # Just last initial
      username = ".".join([first_part, last_part]).lower()

      usernames = self.fetch_usernames()
      if usernames == None:
        # Error page is already rendered.
        return
      if username in usernames:
        # Duplicate username. Use the first part of the email instead.
        username = membership.email.split("@")[0].lower()

        user_number = 0
        base_username = username
        while username in usernames:
          # Still a duplicate. Add a number.
          user_number += 1
          username = "%s%d" % (base_username, user_number)

      if self.request.get("pick_username"):
        pick_username = True

      account_url = str("/account/%s" % membership.hash)
      self.response.out.write(self.render("templates/account.html", locals()))

    def post(self, hash):
        username = self.request.get("username")
        password = self.request.get("password")
        plan = self.request.get("plan")
        plan_object = plans.Plan.get_by_name(plan)
        account_url = str("/account/%s" % hash)

        conf = Config()
        if password != self.request.get("password_confirm"):
            self.response.out.write(self.render("templates/account.html",
                locals(), message="Passwords do not match."))
            self.response.set_status(422)
            return
        elif len(password) < 8:
            self.response.out.write(self.render("templates/account.html",
                locals(), message="Password must be at least 8 characters."))
            self.response.set_status(422)
            return

        membership = Membership.get_by_hash(hash)

        if membership.domain_user:
            logging.warning(
                "Duplicate user '%s' should have been caught" \
                " in first step." % (membership.username))
            self.response.out.write(self.render("templates/account.html",
                locals(), message="You already have an account."))
            self.response.set_status(422)
            return

        # Set a username and password in the datastore.
        membership.username = username
        membership.password = password
        membership.put()

        if membership.status in ("active", "no_visits"):
            taskqueue.add(url="/tasks/create_user", method="POST",
                          params={"hash": membership.hash,
                                  "username": username,
                                  "password": password},
                          countdown=3)
            self.redirect(str("http://%s/success/%s" % (self.request.host, membership.hash)))
            return

        customer_id = membership.key().id()

        # All our giftcards start out with 1337.
        if (membership.referrer and "1337" in membership.referrer):

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
            if not Config().is_testing:
              headers = {"Authorization": "Basic %s" % \
                  base64.b64encode("%s:X" % conf.SPREEDLY_APIKEY),
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

        query_str = urllib.urlencode({"first_name": membership.first_name,
                                      "last_name": membership.last_name,
                                      "email": membership.email,
                                      "return_url": "http://%s/success/%s" % \
                                          (self.request.host, membership.hash)})
        # The plan should already be written, so no point in doing another put.
        # It might have been recent enough that we wouldn't see it, though.
        membership.plan = plan
        # Redirect them to the PinPayments page, where they actually pay.
        self.redirect(membership.new_subscribe_url(query_str))


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


class MemberListHandler(ProjectHandler):
    @ProjectHandler.admin_only
    def get(self):
      signup_users = db.GqlQuery("SELECT * FROM Membership WHERE" \
                                 " status = 'active' ORDER BY last_name") \
                                 .fetch(10000);
      self.response.out.write(self.render("templates/memberlist.html", locals()))


class LeaveReasonListHandler(ProjectHandler):
    @ProjectHandler.admin_only
    def get(self):
      all_users = Membership.all().order("-updated").fetch(10000)
      self.response.out.write(self.render("templates/leavereasonlist.html", locals()))


class JoinReasonListHandler(ProjectHandler):
    @ProjectHandler.admin_only
    def get(self):
      all_users = Membership.all().order("created").fetch(10000)
      self.response.out.write(self.render("templates/joinreasonlist.html", locals()))


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


class AreYouStillThereHandler(ProjectHandler):
    def get(self):
        if not Config().is_dev:
            self.post()

    def post(self):
        countdown = 0
        for membership in Membership.all().filter("status =", "suspended"):
          if (not membership.unsubscribe_reason and membership.spreedly_token \
              and "Deleted" not in membership.last_name and \
              membership.extra_dnd != True):
            # One e-mail every 90 seconds = 960 e-mails a day.
            countdown += 90
            self.response.out.write("Are you still there %s ?<br/>" % \
                                    (membership.email))
            taskqueue.add(url="/tasks/areyoustillthere_mail",
                params={"user": membership.key().id()}, countdown=countdown)


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
            subscriber_api.update_subscriber(membership)

            if membership.status == "active":
              self.redirect("%s?message=You are still an active member." % \
                            (self.request.path))
            elif membership.status == "no_visits":
              self.redirect("%s?message=Your plan is active, but you need to" \
                            " upgrade it." % (self.request.path))
            else:
              subject = "Reactivate your Hacker Dojo Membership"
              subscribe_url = membership.subscribe_url()
              body = self.render("templates/reactivate.txt", locals())
              to = "%s <%s>" % (membership.full_name(), membership.email)
              bcc = "%s <%s>" % ("Billing System", "robot@hackerdojo.com")
              mail.send_mail(sender=Config().EMAIL_FROM_AYST, to=to,
                             subject=subject, body=body, bcc=bcc)
              sent = True
              self.response.out.write(self.render("templates/reactivate.html", locals()))
        else:
            self.redirect(str(self.request.path + "?message=There is no record of that email."))


class CleanupHandler(ProjectHandler):
    def get(self):
        self.post()

    def post(self):
        countdown = 0
        for membership in Membership.all().filter("status =", None):
            if (datetime.datetime.now().date() - membership.created.date()).days > 1:
                countdown += 90
                self.response.out.write("bye %s " % (membership.email))
                taskqueue.add(url="/tasks/clean_row", params={"user": membership.key().id()}, countdown=countdown)


class ProfileHandler(ProjectHandler):
    def get(self):
      user = users.get_current_user()
      if not user:
          self.redirect(users.create_login_url("/profile"))
          return
      else:
          account = Membership.all().filter("username =", user.nickname().split("@")[0]).get()
          email = "%s@%s" % (account.username, Config().APPS_DOMAIN)
          gravatar_url = "http://www.gravatar.com/avatar/" + \
              hashlib.md5(email.lower()).hexdigest()
          self.response.out.write(self.render("templates/profile.html", locals()))


class KeyHandler(ProjectHandler):
    def get(self):
        user = users.get_current_user()
        conf = Config()
        message = escape(self.request.get("message"))
        if not user:
            self.redirect(users.create_login_url("/key"))
            return
        else:
            account = Membership.all().filter("username =", user.nickname().split("@")[0]).get()
            if not account or not account.spreedly_token:
                message = """<p>It appears that you have an account on @%(domain)s, but you do not have a corresponding account in the signup application.</p>
                <p>How to remedy:</p>
                <ol><li>If you <b>are not</b> in the Spreedly system yet, <a href=\"/\">sign up</a> now.</li>
                <li>If you <b>are</b> in Spreedly already, please contact <a href=\"mailto:%(signup_email)s?Subject=Spreedly+account+not+linked+to+account\">%(signup_email)s</a>.</li></ol>
                <pre>Nick: %(nick)s</pre>
                <pre>Email: %(email)s</pre>
                <pre>Account: %(account)s</pre>
                """ % {"domain": conf.APPS_DOMAIN,
                       "signup_email": conf.SIGNUP_HELP_EMAIL,
                       "nick": user.nickname().split("@")[0],
                       "email": user.email(), "account": account}
                if account:
                    message += "<pre>Token: %s</pre>" % account.spreedly_token

                internal = False
                self.response.out.write(self.render("templates/error.html", locals()))
                return
            if account.status != "active":
                url = "https://spreedly.com/"+conf.SPREEDLY_ACCOUNT+"/subscriber_accounts/" + account.spreedly_token
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

    def post(self):
      user = users.get_current_user()
      if not user:
          self.redirect(users.create_login_url("/key"))
          return
      account = Membership.all().filter("username =", user.nickname().split("@")[0]).get()
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


app = webapp2.WSGIApplication([
        ("/", MainHandler),
        ("/userlist", AllHandler),
        ("/suspended", SuspendedHandler),
        ("/cleanup", CleanupHandler),
        ("/profile", ProfileHandler),
        ("/key", KeyHandler),
        ("/genlink/(.+)", GenLinkHandler),
        ("/account/(.+)", AccountHandler),
        ("/upgrade/needaccount", NeedAccountHandler),
        ("/success/(.+)", SuccessHandler),
        ("/joinreasonlist", JoinReasonListHandler),
        ("/leavereasonlist", LeaveReasonListHandler),
        ("/hardshiplist", HardshipHandler),
        ("/memberlist", MemberListHandler),
        ("/areyoustillthere", AreYouStillThereHandler),
        ("/unsubscribe/(.*)", UnsubscribeHandler),
        ("/update", UpdateHandler),
        ("/reactivate", ReactivateHandler),
        ("/plan/(.+)", SelectPlanHandler),
        ("/change_plan", ChangePlanHandler),
        ], debug=True)
