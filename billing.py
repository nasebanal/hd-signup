#!/usr/bin/env python

from google.appengine.api import users
from google.appengine.ext import db
import webapp2

from membership import Membership

class BillingHandler(webapp2.RequestHandler):
  def get(self):
    user = users.get_current_user()
    member = Membership.get_by_username(user.nickname())
    if not member:
      # User is not (yet) a member.
      self.redirect("http://signup.hackerdojo.com")
    else:
      # Open billing information.
      url = member.spreedly_url()
      self.redirect(url)

app = webapp2.WSGIApplication([
    ("/my_billing", BillingHandler),
    ], debug = True)
