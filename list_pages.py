""" The pages that just list members use a lot of the same code, so this file
contains utilities for creating those pages with minimal code duplication. """


import json
import logging

from google.appengine.ext import db

from project_handler import ProjectHandler


""" A special handler class for list page handlers. """
class ListHandler(ProjectHandler):
  """ Gets a response for a particular list page requests. Specifically, there
  are two different types of data that you can request from a list page:
  /total_pages gets the total number of pages, and setting the page argument
  requests data for the next page. This function processes the incoming request,
  grabs the right data, and returns it.
  data_query: The query to use for requesting page data.
  table_template: The template to use for rendering table data.
  Returns: The response to write, or None, if we are just requesting the base
  page. """
  def _process_list_page_request(self, data_query, table_template):
    if self.request.uri.endswith("/total_pages"):
      # Get the total number of pages.
      users_query = db.GqlQuery(data_query)

      users = users_query.count()
      pages = users / 25
      if users % 25:
        pages += 1

      return pages

    elif self.request.get("page"):
      # A request for the next page.
      cursor = self.request.get("page")
      logging.debug("Got cursor: %s" % (cursor))

      users_query = db.GqlQuery(data_query)

      if cursor != "start":
        # Start fetching from where we left off.
        users_query.with_cursor(start_cursor=cursor)

      fetched_users = users_query.fetch(25)

      next_cursor = users_query.cursor()
      logging.debug("Next cursor: %s" % (cursor))

      # Render out the HTML.
      user_table = self.render(table_template,
                                signup_users=fetched_users)
      return json.dumps({"nextPage": next_cursor, "html": user_table})


class MemberListHandler(ListHandler):
  @ProjectHandler.admin_only
  def get(self, *args):
    response = self._process_list_page_request("SELECT * FROM Membership" \
        " WHERE status = 'active' ORDER BY last_name ASC",
        "templates/memberlist_table.html")

    if not response:
      self.response.out.write(self.render("templates/memberlist.html",
                                          title="Active Member List",
                                          endpoint="/memberlist"))
      return

    self.response.out.write(response)


class LeaveReasonListHandler(ListHandler):
    @ProjectHandler.admin_only
    def get(self, *args):
      response = self._process_list_page_request("SELECT * FROM Membership " \
          "WHERE status = 'suspended' ORDER BY updated DESC",
          "templates/leavereasonlist_table.html")

      if not response:
        self.response.out.write(self.render("templates/memberlist.html",
                                            title="Member Reasons for Leaving",
                                            endpoint="/leavereasonlist"))
        return

      self.response.out.write(response)
