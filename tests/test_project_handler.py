""" Tests for the subscriber api handler. """


import os
import unittest

from google.appengine.ext import testbed

import webapp2

import project_handler


""" Test case for the ProjectHandler class """
class ProjectHandlerTests(unittest.TestCase):
  """ Set up for every test. """
  def setUp(self):
    # Create and activate testbed instance.
    self.testbed = testbed.Testbed()
    self.testbed.activate()
    self.testbed.init_user_stub()

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
    argument. """
    @project_handler.ProjectHandler.admin_only
    def test_restricted_function(self):
      return True

    """ A very basic handler proxy. We use this mainly so the decorator has a
    response object to write to. """
    class ProxyHandler(project_handler.ProjectHandler):
      """ Class for simulating a request object. """
      class ProxyRequest:
        def __init__(self):
          self.uri = "test"

      def __init__(self):
        self.response = webapp2.Response()
        self.request = self.ProxyRequest()

    # Simulate a logged-in admin.
    self.testbed.setup_env(user_email="testy.testerson@gmail.com",
                           user_is_admin="1", overwrite=True)
    # It should work.
    self.assertTrue(test_restricted_function(ProxyHandler()))

    # Simulate a logged-in user that is not an admin.
    self.testbed.setup_env(user_email="testy.testerson@gmail.com",
                           user_is_admin="0", overwrite=True)
    self.assertEqual(None, test_restricted_function(ProxyHandler()))

    # Simulate a user that is not logged in.
    self.testbed.setup_env(user_email="", user_is_admin="1", overwrite=True)
    self.assertEqual(None, test_restricted_function(ProxyHandler()))
