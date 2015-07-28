from keymaster import Keymaster
from project_handler import BaseApp, ProjectHandler


class KeymasterHandler(ProjectHandler):
    @ProjectHandler.admin_only
    def get(self):
      self.response.out.write("""<html><body><form method="post">
          <input type="text" name="key" /><input type="text" name="secret" /><input type="submit" /></form></body></html>""")

    @ProjectHandler.admin_only
    def post(self):
      Keymaster.encrypt(self.request.get('key'), self.request.get('secret'))
      self.response.out.write("Saved: %s" % Keymaster.decrypt(self.request.get('key')))

app = BaseApp([
        ('/_km/key', KeymasterHandler),
        ], debug=True)
