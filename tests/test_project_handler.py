""" Tests for the subscriber api handler. """


import os
import unittest

from google.appengine.ext import testbed

import webapp2

from membership import Membership
import project_handler


""" Test case for the ProjectHandler class """
class ProjectHandlerTests(unittest.TestCase):
  """ A very basic handler proxy. We use this mainly so decorators we want to
  test have a response object to write to. """
  class ProxyHandler(project_handler.ProjectHandler):
    """ Class for simulating a request object. """
    class ProxyRequest:
      def __init__(self):
        self.uri = "/test"
        self.url = "http://www.test_url.com/test"

    def __init__(self):
      self.response = webapp2.Response()
      self.request = self.ProxyRequest()
      self.app = project_handler.BaseApp()

  """ Set up for every test. """
  def setUp(self):
    # Create and activate testbed instance.
    self.testbed = testbed.Testbed()
    self.testbed.activate()
    self.testbed.init_datastore_v3_stub()

    self.handler = project_handler.ProjectHandler()

    # Fake template for testing.
    test_file = file("test_template.html", "w")
    test_file.write("{{ value1 }} {{ value2 }}")
    test_file.close()

  """ Cleanup for every test. """
  def tearDown(self):
    self.testbed.deactivate()

    os.remove("test_template.html")

  """ Tests that the render method fills in values correctly. """
  def test_render_values(self):
    # Test with the dict interface.
    response = self.handler.render("test_template.html",
                                   {"value1": "hello", "value2": "world"})
    self.assertEqual(response.encode("ascii"), "hello world")

    # Test with the kwargs interface.
    response = self.handler.render("test_template.html", value1="hello",
                                   value2="world")
    self.assertEqual(response.encode("ascii"), "hello world")

    # I don't know why anyone would do this, but it is supported.
    response = self.handler.render("test_template.html", {"value1": "hello"},
                                   value2="world")
    self.assertEqual(response.encode("ascii"), "hello world")

  """ Tests that the admin_only decorator works. """
  def test_admin_only(self):
    """ A function that we can decorate with it for testing purposes. (The
    decorator expects it to be a class method, so it needs to have a self
    argument.) """
    @project_handler.ProjectHandler.admin_only
    def test_restricted_function(self):
      return True

    # Simulate a logged-in admin.
    user = Membership.create_user("testy.testerson@gmail.com", "notasecret",
                                  first_name="Testy", last_name="Testerson",
                                  hash="notahash", is_admin=True,
                                  status="active")
    project_handler.ProjectHandler.simulate_logged_in_user(user)
    # It should work.
    self.assertTrue(test_restricted_function(self.ProxyHandler()))

    # Simulate a logged-in user that is not an admin.
    user.is_admin = False
    user.put()
    project_handler.ProjectHandler.simulate_logged_in_user(user)
    self.assertEqual(None, test_restricted_function(self.ProxyHandler()))

    # Simulate a user that is not logged in.
    project_handler.ProjectHandler.simulate_logged_in_user(None)
    self.assertEqual(None, test_restricted_function(self.ProxyHandler()))

  """ Tests that the login_required function works as expected. """
  def test_login_required(self):
    """ A function that we can decorate it with for testing purposes. (The
    decorator expects it to be a class method, so it needs to have a self
    argument.) """
    @project_handler.ProjectHandler.login_required
    def test_restricted_function(self):
      return True

    # Simulate a logged-in user.
    user = Membership.create_user("testy.testerson@gmail.com", "notasecret",
                                  first_name="Testy", last_name="Testerson",
                                  hash="notahash", is_admin=True,
                                  status="active")
    project_handler.ProjectHandler.simulate_logged_in_user(user)
    # It should work.
    self.assertTrue(test_restricted_function(self.ProxyHandler()))

    # Simulate a logged-in user that is not an admin.
    user.is_admin = False
    user.put()
    project_handler.ProjectHandler.simulate_logged_in_user(user)
    self.assertTrue(test_restricted_function(self.ProxyHandler()))

    # Simulate a user that is not logged in.
    project_handler.ProjectHandler.simulate_logged_in_user(None)
    self.assertEqual(None, test_restricted_function(self.ProxyHandler()))
