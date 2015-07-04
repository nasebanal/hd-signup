#!/usr/bin/env python

from google.appengine.api import users
from google.appengine.ext import db
import webapp2

from membership import Membership
from plans import Plan
from project_handler import ProjectHandler

class BillingHandler(ProjectHandler):
  def get(self):
    user = users.get_current_user()
    if not user:
      self.redirect(users.create_login_url(self.request.uri))
      return

    member = Membership.get_by_email(user.email())
    if not member:
      # User is not (yet) a member.
      self.redirect("/")
      return
    else:
      # Open billing information.
      url = member.spreedly_url()
      plan = Plan.get_by_name(member.plan)
      if plan.legacy:
        # Show the legacy plan warning.
        current = plan.get_legacy_pair()
        self.response.out.write(self.render(
            "templates/billing_popup.html",
            url=url, legacy=plan, current=current))
        return
      else:
        self.redirect(url)
        return


app = webapp2.WSGIApplication([
    ("/my_billing", BillingHandler),
    ], debug = True)
