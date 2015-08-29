/** Code for managing pagination. */


/** Pseudo-namespace for everything in this file. */
var pagination = {};


/** Sets the base URI that will be used for all page requests.
 @param {String} baseUri: The base URI to use.
 */
pagination.setBaseUri = function(baseUri) {
  pagination.baseUri = baseUri;
}


/** Class for managing large tables to be split up into multiple pages.
 * @param {String} baseUri: The base URI that all the page requests will be
 * built off of.
 */
pagination.paginatedTable = function(baseUri) {
  this.baseUri = baseUri;
  // An array containing page data that we have loaded, in order. (We always
  // load each page in order, because that makes the datastore happy.)
  this.loadedPages_ = [];
  // The cursor we will use to fetch the next page.
  this.pageCursor_ = 'start';
  // Whether we are currently waiting on a page load.
  this.isLoading_ = false;
  // Callbacks for all the deferred page load requests.
  this.deferred_ = [];
  // The currently active page marker.
  this.activePage_ = null;

  /** Figures out how many pages there are total by asking the backend, and
   * renders the first page.
   * @private
   */
  this.renderFirstPage_ = function() {
    var outer_this = this;

    // Perform AJAX request.
    $.get(this.baseUri + '/total_pages', function(data) {
      outer_this.totalPages_ = Number(data);

      // Only show up to the first 11 page markers.
      var showPages = outer_this.totalPages_;
      if (showPages > 11) {
        $('#more-right').show();
        showPages = 11;
      }

      // Make the pagination thingy.
      for (var i = 1; i <= showPages; ++i) {
        var pageMarker = $('<li><a>' + String(i) + '</a></li>');
        $('#more-right').before(pageMarker);

        if (i == 1) {
          outer_this.activePage_ = pageMarker;
          pageMarker.addClass('active');
        }

        // Make a click event for it.
        pageMarker.click(function(event) {
          // Make the page marker active, and deactivate the old one.
          var marker = $(event.target).parent();
          if (marker.html() == outer_this.activePage_.html()) {
            // We clicked the same one twice. Don't do anything.
            return;
          }

          // Figure out what page we clicked on.
          var page = Number($(event.target).text());
          outer_this.showPageMarkers_(page);
          outer_this.renderPage(page);
        });
      }

      outer_this.renderPage(1);
      // Start pre-loading pages.
      outer_this.preloadPages_();
    });
  };

  /** Renders a page of data. NOTE: This function is asynchronous, in that it
   * returns before the page actually gets rendered.
   * @param {Number} page: The page number to render.
   */
  this.renderPage = function(page) {
    var outer_this = this;

    // Show the loading bar.
    $('#page-content').empty();
    $('#loading-bar').show();

    // Actually render the page once we have the data.
    var renderFunction = function() {
      $('#loading-bar').hide();

      var pageData = outer_this.loadedPages_[page - 1];

      // Display the page.
      $('#page-content').html(pageData);
    };

    // Check to see if this page is cached.
    var loaderFunction = function() {
      if (page > outer_this.loadedPages_.length) {
        // We need to fetch more pages first.
        outer_this.loadPage_(loaderFunction);
      } else {
        // We have the data we need to render the page.
        renderFunction();
      }
    };
    loaderFunction();
  };

  /** Loads data for the next page.
   * @private
   * @param {Object} callback: Function to call after the page is loaded.
   */
  this.loadPage_ = function(callback) {
    var outer_this = this;

    var doLoad = function(callback) {
      outer_this.isLoading_ = true;

      // Perform an AJAX request to get the page content.
      $.get(this.baseUri, {'page': outer_this.pageCursor_}, function(data) {
        // Save the page data.
        var pageData = JSON.parse(data);
        outer_this.pageCursor_ = pageData['nextPage'];
        outer_this.loadedPages_.push(pageData['html']);

        // If we have any deferred calls, run it again.
        if (outer_this.deferred_.length) {
          var deferredCallback = outer_this.deferred_.shift();
          doLoad(deferredCallback);
        } else {
          // Nothing to run.
          outer_this.isLoading_ = false;
        }

        callback();
      });
    };

    // Because of the way the cursor-based pagination system works, we have to
    // serialize all these AJAX requests. Otherwise, it's entirely possible that
    // it will start two requests using the same cursor.
    if (this.isLoading_) {
      this.deferred_.push(callback);
    } else {
      doLoad(callback);
    }
  };

  /** Preemtively loads all the pages so they can be ready when we need them.
   * @private
   */
  this.preloadPages_ = function() {
    var outer_this = this;

    var loaderFunction = function() {
      if (outer_this.loadedPages_.length < outer_this.totalPages_) {
        outer_this.loadPage_(loaderFunction);
      }
    };

    loaderFunction();
  };

  /** Recalculates which page markers to show, since we only show 10 at any
   * given time.
   * @private
   * @param {Number} page: The page number that we are switching to.
   */
  this.showPageMarkers_ = function(page) {
    // We want our page to be in the middle.
    var firstPage = page - 5;
    var lastPage = page + 5;

    if (this.totalPages_ <= 11) {
      // We don't have to bother with this, because we have few enough pages.
      firstPage = 1;
      lastPage = this.totalPages_;
    } else {
      // Cap it at either end.
      if (firstPage < 1) {
        lastPage += 1 - firstPage;
        firstPage = 1;
      } else if (lastPage > this.totalPages_) {
        firstPage -= lastPage - this.totalPages_;
        lastPage = this.totalPages_;
      }
    }

    // Show the overflow indicators.
    if (firstPage > 1) {
      $('#more-left').show();
    } else {
      $('#more-left').hide();
    }
    if (lastPage < this.totalPages_) {
      $('#more-right').show();
    } else {
      $('#more-right').hide();
    }

    // Display the proper page markers. Instead of making new ones, we can just
    // change the text on the ones already being displayed.
    var currentPage = firstPage;
    var outer_this = this;
    $('#pages').children('li').each(function() {
      if (this.id.indexOf('more-') > -1) {
        // Skip the indicators on the left and right.
        return;
      }

      var textElement = $(this).children('a').first();
      $(textElement).text(currentPage);

      // Ensure that the proper one is active.
      if (currentPage == page) {
        // This one should be active.
        $(this).addClass('active');
        outer_this.activePage_ = $(this);
      } else {
        // This one shouldn't be active.
        $(this).removeClass('active');
      }

      ++currentPage;
    });
  };

  this.renderFirstPage_();
};


$(document).ready(function() {
  var pages = pagination.paginatedTable(pagination.baseUri);
});
