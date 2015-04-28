from cgi import escape
from pprint import pprint
import json

import wsgiref.handlers
import datetime, time, hashlib, urllib, urllib2, re, os
from google.appengine.api import urlfetch, mail, memcache, users, taskqueue
from google.appengine.ext import deferred
from google.appengine.ext import db
from google.appengine.ext.webapp import template
import webapp2

from config import Config
from membership import Membership
from project_handler import ProjectHandler
from select_plan import SelectPlanHandler
import base64
import keymaster
import logging
import spreedly
import subscriber_api
import sys


class UsedCode(db.Model):
    email = db.StringProperty()
    created = db.DateTimeProperty(auto_now_add=True)
    code = db.StringProperty()
    extra = db.StringProperty()
    completed = db.DateTimeProperty()

class RFIDSwipe(db.Model):
    username = db.StringProperty()
    rfid_tag = db.StringProperty()
    created = db.DateTimeProperty(auto_now_add=True)
    success = db.BooleanProperty()

class RFIDSwipeHandler(ProjectHandler):
    def get(self):
        if self.request.get("maglock:key") != keymaster.get("maglock:key"):
            self.response.out.write("Access denied")
        else:
            rfid_tag = self.request.get("rfid_tag")
            if rfid_tag:
                m = Membership.all().filter("rfid_tag ==", rfid_tag).get()
                if m:
                  username = m.username
                  if "active" in m.status:
                     success = True
                  else:
                     success = False
                     subject = "Reactivate your RFID key now - renew your Hacker Dojo Subscription!"
                     body = """
Hi %s,

It looks like you just tried using your RFID key to open the doors to Hacker Dojo.

One teeny tiny issue, it looks like your membership has lapsed!  This can happen by mistake sometimes, so no worries at all.  The good news is you can reactivate your membership with only a few clicks:

%s

With warmest regards,
The Lobby Door
""" % (m.first_name,m.subscribe_url())
                     deferred.defer(mail.send_mail, sender="Maglock <robot@hackerdojo.com>", to=m.email,
                     subject=subject, body=body, _queue="emailthrottle")
                else:
                  username = "unknown ("+rfid_tag+")"
                  success = False
                rs = RFIDSwipe(username=username, rfid_tag=rfid_tag, success=success)
                rs.put()
                if "mark.hutsell" in username or "some.other.evilguy" in username:
                  deferred.defer(mail.send_mail, sender="Maglock <robot@hackerdojo.com>", to="Emergency Paging System <page@hackerdojo.com>",
                     subject="RFID Entry: " + username, body="Lobby entry", _queue="emailthrottle")
                  urlfetch.fetch("http://www.dustball.com/call/call.php?str=RFID+Entry+"+username)
            self.response.out.write("OK")

class BadgeChange(db.Model):
    created = db.DateTimeProperty(auto_now_add=True)
    rfid_tag = db.StringProperty()
    username = db.StringProperty()
    description = db.StringProperty()

class MainHandler(ProjectHandler):
    def get(self):
      self.response.out.write(self.render("templates/main.html"))

    def post(self):
      first_name = self.request.get("first_name")
      last_name = self.request.get("last_name")
      twitter = self.request.get("twitter").lower().strip().strip("@")
      email = self.request.get("email").lower().strip()

      if not first_name or not last_name or not email:
        self.response.out.write(self.render("templates/main.html",
            {"message": "Sorry, we need name and e-mail address."}))
        return

      first_part = re.compile(r"[^\w]").sub("", first_name.split(" ")[0])
      last_part = re.compile(r"[^\w]").sub("", last_name)
      if len(first_part)+len(last_part) >= 15:
        last_part = last_part[0]
      username = ".".join([first_part, last_part]).lower()

      usernames = self.fetch_usernames()
      if usernames == None:
        # Error page is already rendered.
        return
      if username in usernames:
        username = email.split("@")[0].lower()

      membership = db.GqlQuery("SELECT * FROM Membership WHERE email = :email",
                               email=email).get()

      if membership:
        # A membership object already exists in the datastore.
        if membership.extra_dnd == True:
          self.response.out.write("Error #237.  Please contact signupops@hackerdojo.com")
          return
        if membership.status == "suspended":
          self.response.out.write(self.render("templates/main.html",
              message="Your account has been suspended." \
              " <a href=\"/reactivate\">Click here</a> to reactivate."))
          return
        elif membership.status == "active":
          self.response.out.write(self.render("templates/main.html",
                                  message="Account already exists."))
          return
        else:
          # Existing membership never got activated. Overwrite it.
          logging.info("Overwriting existing membership for %s." % (email))
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

      # Have the user select a plan.
      self.redirect(str("/plan/%s" % membership.hash))


class AccountHandler(ProjectHandler):
    def get(self, hash):
        membership = Membership.get_by_hash(hash)
        if membership:
          # Save the plan they want.
          plan = self.request.get("plan", "newfull")
          membership.plan = plan
          membership.put()

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
              username = membership.email.split("@")[0].lower()
          if self.request.get("u"):
              pick_username = True

          account_url = str("/account/%s" % membership.hash)
          self.response.out.write(self.render("templates/account.html", locals()))
        else:
          self.response.set_status(422)
          self.response.out.write("Unknown member hash.")
          logging.error("Could not find member with hash '%s'." % (hash))

    def post(self, hash):
        username = self.request.get("username")
        password = self.request.get("password")
        plan = self.request.get("plan")
        account_url = str("/account/%s" % hash)

        conf = Config()
        if password != self.request.get("password_confirm"):
            self.response.out.write(self.render("templates/account.html",
                locals(), message="Passwords do not match."))
            return
        elif len(password) < 8:
            self.response.out.write(self.render("templates/account.html",
                locals(), message="Password must be at least 8 characters."))
            return
        else:
            membership = Membership.get_by_hash(hash)
            if membership.username:
                self.redirect(str(self.request.path + "?message=You already have a user account"))
                return

            # Yes, storing their username and password temporarily so we can make their account later
            memcache.set(str(hashlib.sha1(str(membership.hash) \
                + conf.SPREEDLY_APIKEY).hexdigest()),
                "%s:%s" % (username, password), time=3600)

            if membership.status == "active":
                taskqueue.add(url="/tasks/create_user", method="POST", params={"hash": membership.hash}, countdown=3)
                self.redirect(str("http://%s/success/%s" % (self.request.host, membership.hash)))
            else:
                customer_id = membership.key().id()

                # This code is not weird...
                if "1337" in membership.referrer:

                    if len(membership.referrer) != 16:
                        message = "<p>Error: code must be 16 digits."
                        message += "<p>Please contact %s if you believe this \
                                 message is in error and we can help!" % \
                                 (conf.SIGNUP_HELP_EMAIL)
                        message += "<p><a href="/">Start again</a>"
                        internal = False
                        self.response.out.write(self.render("templates/error.html", locals()))
                        return

                    serial = membership.referrer[4:8]
                    hash = membership.referrer[8:16]
                    confirmation_hash = re.sub("[a-f]","",hashlib.sha1(serial+keymaster.get("code:hash")).hexdigest())[:8]

                    if hash != confirmation_hash:
                        message = "<p>Error: this code was invavlid: %s" % \
                            (membership.referrer)
                        message += "<p>Please contact %s if you believe this \
                                 message is in error and we can help!" % \
                                 (conf.SIGNUP_HELP_EMAIL)
                        message += "<p><a href="/">Start again</a>"
                        internal = False
                        uc = UsedCode(code=membership.referrer,email=membership.email,extra="invalid code")
                        uc.put()
                        self.response.out.write(self.render("templates/error.html", locals()))
                        return

                    previous = UsedCode.all().filter("code =", membership.referrer).get()
                    if previous:
                        message = "<p>Error: this code has already been used: "+ membership.referrer
                        message += "<p>Please contact "+ SIGNUP_HELP_EMAIL+" if you believe this message is in error and we can help!"
                        message += "<p><a href="/">Start again</a>"
                        internal = False
                        uc = UsedCode(code=membership.referrer,email=membership.email,extra="2nd+ attempt")
                        uc.put()
                        self.response.out.write(self.render("templates/error.html", locals()))
                        return

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

                query_str = urllib.urlencode({"first_name": membership.first_name, "last_name": membership.last_name,
                    "email": membership.email, "return_url":
                    "http://%s/success/%s" % (self.request.host, membership.hash)})
                # check if they are active already since we didn"t create a new member above
                # apparently the URL will be different
                self.redirect(str("https://spreedly.com/%s/subscribers/%s/subscribe/%s/%s?%s" %
                    (conf.SPREEDLY_ACCOUNT, customer_id, conf.PLAN_IDS[plan], username, query_str)))


class CreateUserTask(ProjectHandler):
    def post(self):
        def fail(exception):
            logging.error("CreateUserTask failed: %s" % exception)
            mail.send_mail(sender=Config().EMAIL_FROM,
                to=Config().INTERNAL_DEV_EMAIL,
                subject="[%s] CreateUserTask failure" % Config().APP_NAME,
                body=str(exception))
        def retry(countdown=3):
            retries = int(self.request.get("retries", 0)) + 1
            if retries <= 5:
                taskqueue.add(url="/tasks/create_user", method="POST", countdown=countdown,
                    params={"hash": self.request.get("hash"), "retries": retries})
            else:
                fail(Exception("Too many retries for %s" % self.request.get("hash")))

        user_hash = self.request.get("hash")
        membership = Membership.get_by_hash(user_hash)
        if membership is None or membership.username:
            return
        if not membership.spreedly_token:
            logging.warn("CreateUserTask: No spreedly token yet, retrying")
            return retry(300)


        try:
            username, password = memcache.get(hashlib.sha1(membership.hash + \
                Config().SPREEDLY_APIKEY).hexdigest()).split(":")
        except (AttributeError, ValueError):
            return fail(Exception("Account information expired for %s" % membership.email))

        try:
            url = "http://%s/users" % DOMAIN_HOST
            payload = urllib.urlencode({
                "username": username,
                "password": password,
                "first_name": membership.first_name,
                "last_name": membership.last_name,
                "secret": keymaster.get("api"),
            })
            logging.info("CreateUserTask: About to create user: "+username)
            logging.info("CreateUserTask: URL: "+url)
            logging.info("CreateUserTask: Payload: "+payload)
            resp = urlfetch.fetch(url, method="POST", payload=payload, deadline=120)
            membership.username = username
            membership.put()
            logging.warning("CreateUserTask: I think that worked: HTTP %d" % \
                            (resp.status_code))

            # Send the welcome email.
            SuccessHandler.send_email(membership)
        except urlfetch.DownloadError, e:
            logging.warn("CreateUserTask: API response error or timeout, retrying")
            return retry()
        except keymaster.KeymasterError, e:
            fail(e)
            return retry(3600)
        except Exception, e:
            return fail(e)


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
    @classmethod
    def send_email(cls, member):
      spreedly_url = member.spreedly_url()
      dojo_email = "%s@hackerdojo.com" % (member.username)
      name = member.full_name()
      mail.send_mail(sender=EMAIL_FROM,
          to="%s <%s>; %s <%s>" % (name, member.email, name, dojo_email),
          subject="Welcome to Hacker Dojo, %s!" % member.first_name,
          body=self.render("templates/welcome.txt", locals()))

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
    def get(self):
        pass

    def post(self):
        subscriber_ids = self.request.get("subscriber_ids").split(",")
        for id in subscriber_ids:
          subscriber_api.update_subscriber(Membership.get_by_id(int(id)))

        self.response.out.write("ok")


class LinkedHandler(ProjectHandler):
    def get(self):
        self.response.out.write(json.dumps([m.username for m in Membership.all().filter("username !=", None)]))


class APISuspendedHandler(ProjectHandler):
    def get(self):
        self.response.out.write(json.dumps([[m.fullname(), m.username] for m in Membership.all().filter("status =", "suspended")]))


class MemberListHandler(ProjectHandler):
    def get(self):
      user = users.get_current_user()
      if not user:
        self.redirect(users.create_login_url("/memberlist"))
      signup_users = Membership.all().order("last_name").fetch(10000);
      self.response.out.write(self.render("templates/memberlist.html", locals()))


class DebugHandler(ProjectHandler):
    def get(self):
      user = users.get_current_user()
      if not user:
        self.redirect(users.create_login_url("/debug_users"))
      if users.is_current_user_admin():
        if not self.request.get("from"):
          all_users = Membership.all()
          x = all_users.count()
          self.response.out.write("There are ")
          self.response.out.write(x)
          self.response.out.write( \
              " user records. Use GET params \"from\" and \"to\" to analyze.")
        else:
          fr = self.request.get("from")
          to = self.request.get("to")
          for i in range(int(fr),int(to)):
            a = Membership.all().fetch(1,i)[0]
            self.response.out.write("<p>")
            self.response.out.write(a.key().id())
            self.response.out.write(" - ")
            self.response.out.write(a.username)
      else:
        self.response.out.write("Need admin access")


class LeaveReasonListHandler(ProjectHandler):
    def get(self):
      user = users.get_current_user()
      if not user:
        self.redirect(users.create_login_url("/leavereasonlist"))
      if users.is_current_user_admin():
        all_users = Membership.all().order("-updated").fetch(10000)
        self.response.out.write(self.render("templates/leavereasonlist.html", locals()))
      else:
        self.response.out.write("Need admin access")


class JoinReasonListHandler(ProjectHandler):
    def get(self):
      user = users.get_current_user()
      if not user:
        self.redirect(users.create_login_url("/joinreasonlist"))
      if users.is_current_user_admin():
        all_users = Membership.all().order("created").fetch(10000)
        self.response.out.write(self.render("templates/joinreasonlist.html", locals()))
      else:
        self.response.out.write("Need admin access")


class SuspendedHandler(ProjectHandler):
    def get(self):
      user = users.get_current_user()
      if not user:
        self.redirect(users.create_login_url("/suspended"))
      if users.is_current_user_admin():
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
      else:
        self.response.out.write("Need admin access")


class AllHandler(ProjectHandler):
    def get(self):
      user = users.get_current_user()
      if not user:
        self.redirect(users.create_login_url("/userlist"))
      if users.is_current_user_admin():
        signup_users = Membership.all().fetch(10000)
        signup_users = sorted(signup_users, key=lambda user: user.last_name.lower())
        user_keys = [str(user.key()) for user in signup_users]
        user_ids = [user.key().id() for user in signup_users]
        self.response.out.write(self.render("templates/users.html", locals()))
      else:
        self.response.out.write("Need admin access")


class HardshipHandler(ProjectHandler):
    def get(self):
      user = users.get_current_user()
      if not user:
        self.redirect(users.create_login_url("/hardshiplist"))
      if users.is_current_user_admin():
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
      else:
        self.response.out.write("Need admin access")


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
            # One e-mail every 20 min = 72 e-mails a day (100 is free appengine
            # limit)
            countdown += 1200
            self.response.out.write("Are you still there %s ?<br/>" % \
                                    (membership.email))
            taskqueue.add(url="/tasks/areyoustillthere_mail",
                params={"user": membership.key().id()}, countdown=countdown)


class AreYouStillThereMail(ProjectHandler):
    def post(self):
        user = Membership.get_by_id(int(self.request.get("user")))
        subject = "Hacker Dojo Membership: ACTION REQUIRED"

        first_name = user.first_name
        subscribe_url = user.subscribe_url()
        unsubscribe_url = user.unsubscribe_url()
        body = self.render("templates/areyoustillthere.txt", locals())

        to = "%s <%s>" % (user.full_name(), user.email)
        bcc = "%s <%s>" % ("Billing System", "robot@hackerdojo.com")
        if user.username:
            cc="%s <%s@hackerdojo.com>" % (user.full_name(), user.username),
            mail.send_mail(sender=Config().EMAIL_FROM_AYST, to=to,
                           subject=subject, body=body, bcc=bcc, cc=cc)
        else:
            mail.send_mail(sender=Config().EMAIL_FROM_AYST, to=to,
                           subject=subject, body=body, bcc=bcc)


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
                self.redirect(str(self.request.path + \
                    "?message=You are still an active member"))
            else:
              subject = "Reactivate your Hacker Dojo Membership"
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
            if (datetime.now().date() - membership.created.date()).days > 1:
                countdown += 90
                self.response.out.write("bye %s " % (membership.email))
                taskqueue.add(url="/tasks/clean_row", params={"user": membership.key().id()}, countdown=countdown)


class CleanupTask(ProjectHandler):
    def post(self):
        user = Membership.get_by_id(int(self.request.get("user")))
        try:
          mail.send_mail(sender=Config().EMAIL_FROM,
              to=user.email,
              subject="Hi again -- from Hacker Dojo!",
              body="Hi %s,"
              "\nOur fancy membership system noted that you started filling"
              " out the Membership Signup form, but didn't complete it."
              "\nWell -- We'd love to have you as a member!"
              "\nHacker Dojo has grown by leaps and bounds in recent years."
              " Give us a try?"
              "\nIf you would like to become a member of Hacker Dojo, just"
              " complete the signup process at http://signup.hackerdojo.com"
              "\nIf you don't want to sign up -- please give us anonymous"
              " feedback so we know how we can do better!  URL:"
              " http://bit.ly/jJAGYM"
              "\nCheers!\nHacker Dojo"
              "\n\nPS: Please ignore this e-mail if you already signed up --"
              " you might have started signing up twice or something :)"
              " PPS: This is an automated e-mail and we're now deleting your"
              " e-mail address from the signup application." % (user.full_name)
          )
        except:
          noop = True
        user.delete()


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

class PrefHandler(ProjectHandler):
   def get(self):
      user = users.get_current_user()
      if not user:
          self.redirect(users.create_login_url("/pref"))
          return
      else:
          account = Membership.all().filter("username =", user.nickname().split("@")[0]).get()
          if not account:
            message = "<p>Error - couldn't find your account.</p>"
            message += "<pre>Nick: "+str(user.nickname().split("@")[0])
            message += "<pre>Email: "+str(user.email())
            message += "<pre>Account: "+str(account)
            if account:
              message += "<pre>Token: "+str(account.spreedly_token)
            internal = False
            self.response.out.write(self.render("templates/error.html", locals()))
            return
          auto_signin = account.auto_signin
          self.response.out.write(self.render("templates/pref.html", locals()))

   def post(self):
      user = users.get_current_user()
      if not user:
          self.redirect(users.create_login_url("/pref"))
          return
      account = Membership.all().filter("username =", user.nickname().split("@")[0]).get()
      if not account:
            message = "Error #1983, which should never happen."
            internal = True
            self.response.out.write(self.render("templates/error.html", locals()))
            return
      auto_signin = self.request.get("auto").strip()
      account.auto_signin = auto_signin
      account.put()
      self.response.out.write(self.render("templates/prefsaved.html", locals()))


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
                """ % {"url": url, "signup_email": SIGNUP_HELP_EMAIL}
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

class RFIDHandler(ProjectHandler):
    def get(self):
      if self.request.get("id"):
        m = Membership.all().filter("rfid_tag ==", self.request.get("id")).filter("status =", "active").get()
        if self.request.get("callback"): # jsonp callback support
          self.response.out.write(self.request.get("callback")+"(");
        if m:
          email = "%s@%s" % (m.username, APPS_DOMAIN)
          gravatar_url = "http://www.gravatar.com/avatar/" + hashlib.md5(email.lower()).hexdigest()
          self.response.out.write(json.dumps({"gravatar": gravatar_url,"auto_signin":m.auto_signin, "status" : m.status, "name" : m.first_name + " " + m.last_name, "rfid_tag" : m.rfid_tag, "username" : m.username }))
        else:
          self.response.out.write(json.dumps({}))
        if self.request.get("callback"):
          self.response.out.write(")");
      else:
        if self.request.get("maglock:key") == keymaster.get("maglock:key"):
          if self.request.get("machine"):
            members = Membership.all().filter("rfid_tag !=", None).filter("status =", "active").filter("extra_"+self.request.get("machine")+" =","True")
          else:
            members = Membership.all().filter("rfid_tag !=", None).filter("status =", "active")
          self.response.out.write(json.dumps([ {"rfid_tag" : m.rfid_tag, "username" : m.username } for m in members]))
        else:
          self.response.out.write("Access denied")

class ModifyHandler(ProjectHandler):
    def get(self):
      user = users.get_current_user()
      account = Membership.all().filter("username =", user.nickname().split("@")[0]).get()
      if not account:
          self.redirect(users.create_login_url("/modify"))
          return
      else:
          if not account or not account.spreedly_token:
            message = """<p>Sorry, your %(name)s account does not appear to be linked to a Spreedly account.
Please contact <a href=\"mailto:%(treasurer)s\">%(treasurer)s</a> so they can manually update your account.
""" % {"treasurer": TREASURER_EMAIL, "name": ORG_NAME}
            internal = False
            self.response.out.write(self.render("templates/error.html", locals()))
            return
          url = \
              "https://spreedly.com/%s/subscriber_accounts/%s" % \
              (Config().SPREEDLY_ACCOUNT, account.spreedly_token)
          self.redirect(str(url))

class GenLinkHandler(ProjectHandler):
    def get(self, key):
        conf = Config()
        sa = conf.SPREEDLY_ACCOUNT
        u = Membership.get_by_id(int(key))
        plans = conf.PLAN_IDS.items()
        self.response.out.write(self.render("templates/genlink.html", locals()))


class CacheUsersCron(ProjectHandler):
    def get(self):
        self.post()

    def post(self):
        self.fetch_usernames(use_cache=False)

class GetTwitterHandler(ProjectHandler):
    def get(self):
      user = users.get_current_user()
      if not user:
        self.redirect(users.create_login_url("/api/gettwitter"))
      if users.is_current_user_admin():
        need_twitter_users = Membership.all().filter("status =", "active").fetch(10000)
        countdown = 0
        for u in need_twitter_users:
          if u.username and not u.twitter:
            self.response.out.write(u.username)
            taskqueue.add(url="/tasks/twitter_mail", params={"user": u.key().id()}, countdown=countdown)
            countdown += 1
      else:
        self.response.out.write("Need admin access")


class TwitterMail(ProjectHandler):
    def post(self):
        user = Membership.get_by_id(int(self.request.get("user")))
        subject = "What's your twitter handle?"
        base = self.request.host
        body = self.render("templates/twittermail.txt", locals())
        to = "%s <%s@hackerdojo.com>" % (user.full_name(), user.username)
        bcc = "%s <%s>" % ("Robot", "robot@hackerdojo.com")
        mail.send_mail(sender=EMAIL_FROM_AYST, to=to, subject=subject, body=body, bcc=bcc, html=body)

class SetTwitterHandler(ProjectHandler):
    def get(self):
      if self.request.get("user"):
        m = Membership.get(self.request.get("user"))
        m.twitter = self.request.get("twitter").lower().strip().strip("@")
        m.put()
        self.response.out.write("<p>Thanks!  All set now.  <p>We'll send out more information in a week or two.")

class SetHSHandler(ProjectHandler):
    def get(self):
      if self.request.get("user"):
        m = Membership.get(self.request.get("user"))
        m.hardship_comment = self.request.get("comment").strip()
        m.put()
        self.response.out.write("<p>Set.")

class SetExtraHandler(ProjectHandler):
    def get(self):
      user = users.get_current_user()
      if not user:
        self.redirect(users.create_login_url("/api/setextra"))
      if users.is_current_user_admin():
        user = Membership.all().filter("username =", self.request.get("username")).get()
        if user:
          v = self.request.get("value")
          if v=="True":
              v = True
          if v=="False":
              v = False
          user.__setattr__("extra_"+self.request.get("key"), v)
          user.put()
          self.response.out.write("OK")
        else:
          self.response.out.write("User not found")
      else:
        self.response.out.write("Need admin access")

class CSVHandler(ProjectHandler):
    def get(self):
      self.response.headers["Content-type"] = "text/csv; charset=utf-8"
      self.response.headers["Content-disposition"] = "attachment;filename=HackerDojoMembers.csv"
      if keymaster.get("csvkey") == self.request.get("csvkey"):
        users = Membership.all().filter("status =", "active").filter("username !=", "").fetch(10000)
        for u in users:
          twitter = ""
          if u.twitter:
            twitter = u.twitter
          first = ""
          if u.first_name:
            first = u.first_name
          last = ""
          if u.last_name:
            last = u.last_name
          if u.username:
            self.response.out.write(first+","+last+","+u.username+"@hackerdojo.com,"+twitter+"\r\n")


app = webapp2.WSGIApplication([
        ("/", MainHandler),
        ("/api/rfid", RFIDHandler),
        ("/api/rfidswipe", RFIDSwipeHandler),
        ("/userlist", AllHandler),
        ("/suspended", SuspendedHandler),
        ("/api/linked", LinkedHandler),
        ("/api/suspended", APISuspendedHandler),
        ("/cleanup", CleanupHandler),
        ("/profile", ProfileHandler),
        ("/debug_users", DebugHandler),
        ("/key", KeyHandler),
        ("/pref", PrefHandler),
        ("/modify", ModifyHandler),
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
        ("/api/membercsv", CSVHandler),
        ("/api/gettwitter", GetTwitterHandler),
        ("/api/setextra", SetExtraHandler),
        ("/api/settwitter", SetTwitterHandler),
        ("/api/seths", SetHSHandler),
        ("/tasks/create_user", CreateUserTask),
        ("/tasks/clean_row", CleanupTask),
        ("/cron/cache_users", CacheUsersCron),
        ("/tasks/areyoustillthere_mail", AreYouStillThereMail),
        ("/tasks/twitter_mail", TwitterMail),
        ("/reactivate", ReactivateHandler),
        ("/plan/(.+)", SelectPlanHandler),
        ], debug=True)
