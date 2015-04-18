import os

from google.appengine.ext import webapp

import jinja2

from config import Config


JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)))


""" A generic superclass for all handlers. """
class ProjectHandler(webapp.RequestHandler):
  """ Render out templates with the proper information.
  path: Path to the template file.
  values: Values to fill in the template with.
  These values can also be passed in as individual keyword arguments. """
  def render(self, path, values={}, **kwargs):
      conf = Config()
      template_vars = {"is_prod": conf.is_prod, "org_name": conf.ORG_NAME,
          "analytics_id": conf.GOOGLE_ANALYTICS_ID, "domain": conf.APPS_DOMAIN}
      # Add the request object if we have one.
      try:
        template_vars["request"] = self.request
      except AttributeError:
        pass

      template_vars.update(values)
      template_vars.update(kwargs)

      if conf.is_dev:
          template_vars["dev_message"] = "You are using the dev version of \
              Signup."

      template = JINJA_ENVIRONMENT.get_template(path)
      return template.render(template_vars)
