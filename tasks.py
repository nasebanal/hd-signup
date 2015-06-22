""" Contains handlers that are run as tasks. """


import logging
import urllib

from google.appengine.api import mail, taskqueue, urlfetch

import webapp2

from config import Config
from main import SuccessHandler
from membership import Membership
from project_handler import ProjectHandler


""" Superclass for all taskqueue handlers. """
class QueueHandlerBase(ProjectHandler):
  """ A function meant to be used as a decorator. It ensures that a task queue
  is making the request before running the function.
  function: The function that we are decorating.
  Returns: A wrapped version of the function that interrupts the flow if it
           finds a problem. """
  @classmethod
  def taskqueue_only(cls, function):
    """ Wrapper function to return. """
    def wrapper(self, *args, **kwargs):
      queue = self.request.headers.get("X-Appengine-QueueName", None)

      # If we're not on production, don't deny any requests.
      conf = Config()
      if not conf.is_prod:
        logging.info("Non-production environment, servicing all requests.")

      elif not queue:
        logging.warning("Not running '%s' for non-taskqueue job." % \
            (function.__name__))
        self.response.out.write("Only taskqueues can do that.")
        self.set_status(403)
        return

      return function(self, *args, **kwargs)

    return wrapper


""" A handler for creating GoogleApps domain users. Basically gets run once for
everybody who signs up. """
class CreateUserTask(QueueHandlerBase):
  """ Create domain user.
  Parameters:
  hash: The hash of the user we are creating a domain account for.
  username: The username we want the domain account to have.
  password: The password we want the domain account to have. """
  @QueueHandlerBase.taskqueue_only
  def post(self):
    """ Report a failure of this task. """
    def fail(exception):
      logging.error("CreateUserTask failed: %s" % exception)
      mail.send_mail(sender=Config().EMAIL_FROM,
          to=Config().INTERNAL_DEV_EMAIL,
          subject="[%s] CreateUserTask failure" % Config().APP_NAME,
          body=str(exception))

      self.response.set_status(500)

    """ Retry this task.
    countdown: How long to wait before running it again. """
    def retry(countdown=3):
      retries = int(self.request.get("retries", 0)) + 1
      if retries <= 5:
        taskqueue.add(url="/tasks/create_user", method="POST",
                      countdown=countdown,
            params={"hash": self.request.get("hash"),
                    "username": self.request.get("username"),
                    "password": self.request.get("password"),
                    "retries": retries})
      else:
        fail(Exception("Too many retries for %s" % self.request.get("hash")))

    user_hash = self.request.get("hash")
    membership = Membership.get_by_hash(user_hash)

    if membership is None:
      logging.error("Got nonexistent hash: %s" % (user_hash))
      self.response.set_status(422)
      return
    if membership.domain_user:
      logging.warning(
          "Not creating domain account for already-existing user '%s'." \
          % (membership.username))
      # Don't set another status here, because we don't want the
      # PinPayments system to keep retrying the call.
      return

    if not membership.spreedly_token:
      logging.warn("CreateUserTask: No spreedly token yet, retrying")
      return retry(300)

    username = self.request.get("username")
    password = self.request.get("password")

    try:
      url = "http://%s/users" % Config().DOMAIN_HOST
      payload = urllib.urlencode({
          "username": username,
          "password": password,
          "first_name": membership.first_name,
          "last_name": membership.last_name,
      })
      logging.info("CreateUserTask: About to create user: "+username)
      logging.info("CreateUserTask: URL: "+url)
      logging.info("CreateUserTask: Payload: "+payload)

      if not Config().is_testing:
        resp = urlfetch.fetch(url, method="POST", payload=payload,
                              deadline=120, follow_redirects=False)
        if resp.status_code == 200:
          logging.info("I think that worked.")
        else:
          logging.error("I think that failed: HTTP %d" % (resp.status_code))
          return retry()

      else:
        # I want to see what query string it would have used.
        self.response.out.write(payload)

      # Invalidate the current cached usernames, since we added a new one.
      self.invalidate_cached_usernames()

      membership.domain_user = True
      # We'll never use the password again, and there's no sense in
      # leaving this sensitive information sitting in the datastore, so we
      # might as well get rid of it.
      membership.password = None
      membership.put()

      # Send the welcome email.
      SuccessHandler.send_email(self, membership)
    except urlfetch.DownloadError, e:
      logging.error("Domain app response error or timeout, retrying")
      return retry()
    except Exception, e:
      return fail(e)


""" Sends a reminder email to suspended users. """
class AreYouStillThereMail(QueueHandlerBase):
  """ Send the reminder email to a specific user.
  Parameters:
  user: The ID of the user to send the email to. """
  @QueueHandlerBase.taskqueue_only
  def post(self):
    user_id = int(self.request.get("user"))
    logging.debug("Getting member with id: %d" % (user_id))
    user = Membership.get_by_id(int(self.request.get("user")))
    if not user:
      logging.error("Bad ID for member.")
      # Don't change the status, because we don't want it to try the request
      # again.
      return

    logging.info("Sending email to %s %s." % \
                  (user.first_name, user.last_name))
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


""" Sends an email to and then deletes people who never finished signing up. """
class CleanupTask(QueueHandlerBase):
  """ Send an email to and delete a specific person.
  user: The ID of the user to send the email to. """
  @QueueHandlerBase.taskqueue_only
  def post(self):
    user_id = self.request.get("user")
    user = Membership.get_by_id(int(user_id))
    if not user:
      logging.warning("No user with id %s." % (user_id))
      # Don't change the status, because we don't want it to retry.
      return

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
        " e-mail address from the signup application." % (user.full_name())
    )

    user.delete()


app = webapp2.WSGIApplication([
    ("/tasks/create_user", CreateUserTask),
    ("/tasks/clean_row", CleanupTask),
    ("/tasks/areyoustillthere_mail", AreYouStillThereMail),
    ], debug=True)
