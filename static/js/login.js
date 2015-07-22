/** Handles the login page. */

/** Pseudo-namespace for everything in this file. */
var login = {};

/** Class for handling the login box. */
login.loginBox = function() {
  // Whether the login button is enabled.
  this.loginEnabled_ = false;

  /** Registers all the event handlers for this class.
   * @private
   */
  this.registerHandlers_ = function() {
    // Do actions whenever the user enters text.
    var outer_this = this;
    $('input').on('keyup', function() {
      outer_this.validateInput_();
    });
  };

  /** Checks if the user's input is valid and enables/disables the submit button
   * accordingly.
   * @private
   */
  this.validateInput_ = function() {
    var email = $('#email').val();
    var password = $('#password').val();

    if (!email) {
      // Empty email, this is a no-go.
      this.disableLogin_();
    } else if (password.length < 8) {
      // Password is too short.
      this.disableLogin_();
    } else {
      // It's okay.
      this.enableLogin_();
    }
  };

  /** Disables the login button.
   * @private
   */
  this.disableLogin_ = function() {
    if (!this.loginEnabled_) {
      return;
    }

    $('#login').addClass('btn-disabled');
    $('#login').prop('disabled', true);
    this.loginEnabled_ = false;
  };

  /** Enables the login button.
   * @private
   */
  this.enableLogin_ = function() {
    if (this.loginEnabled_) {
      return;
    }

    $('#login').removeClass('btn-disabled');
    $('#login').prop('disabled', false);
    this.loginEnabled_ = true;
  };

  this.registerHandlers_();
  // Do this initially to catch any autofill stuff.
  this.validateInput_();
};

$(document).ready(function() {
  box = new login.loginBox();
});
