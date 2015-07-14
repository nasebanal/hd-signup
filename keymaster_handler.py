from google.appengine.api import users
from google.appengine.ext.webapp import util

from keymaster import Keymaster
from project_handler import BaseApp, ProjectHandler


class KeymasterHandler(ProjectHandler):
    @util.login_required
    def get(self):
        if users.is_current_user_admin():
            self.response.out.write("""<html><body><form method="post">
                <input type="text" name="key" /><input type="text" name="secret" /><input type="submit" /></form></body></html>""")
        else:
            self.redirect('/')

    def post(self):
        if users.is_current_user_admin():
            Keymaster.encrypt(self.request.get('key'), self.request.get('secret'))
            self.response.out.write("Saved: %s" % Keymaster.decrypt(self.request.get('key')))
        else:
            self.redirect('/')

app = BaseApp([
        ('/_km/key', KeymasterHandler),
        ], debug=True)
