""" Tests for the subscriber api handler. """

import os
import unittest

from google.appengine.ext import testbed

import project_handler


TEMPLATE_LOADERS_STRING = (
'django.template.loaders.filesystem.loader',
'django.template.loaders.app_directories.loader',
)


""" Test case for the ProjectHandler class """
class UpdateTests(unittest.TestCase):
  """ Set up for every test. """
  def setUp(self):
    # Create and activate testbed instance.
    self.testbed = testbed.Testbed()
    self.testbed.activate()

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
