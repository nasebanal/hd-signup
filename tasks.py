""" Contains handlers that are run as tasks. """


import logging
import urllib

from google.appengine.api import mail, taskqueue, urlfetch

from config import Config
from main import SuccessHandler
from membership import Membership
from project_handler import ProjectHandler, BaseApp


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
        self.response.set_status(403)
        return

      return function(self, *args, **kwargs)

    return wrapper


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
      cc="%s <%s>" % (user.full_name(), user.email),
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

    logging.info("Sending email to %s." % (user.email))

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
          " e-mail address from the signup application." % (user.full_name())
      )
    except mail.BadRequestError:
      # Apparently, sometimes people enter bad email addresses. In this case, we
      # can just clear them silently.
      logging.warning("Deleting user with invalid email address.")

    user.delete()


app = BaseApp([
    ("/tasks/clean_row", CleanupTask),
    ("/tasks/areyoustillthere_mail", AreYouStillThereMail),
    ], debug=True)
