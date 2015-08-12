/** Handles the login page. */

/** Pseudo-namespace for everything in this file. */
var login = {};

/** Class for handling the login box. */
login.loginBox = function() {
  // Whether the login button is enabled.
  this.loginEnabled_ = false;
  // Whether a keyup event has been triggered on the form.
  this.keyUpTriggered_ = false;

  /** Registers all the event handlers for this class.
   * @private
   */
  this.registerHandlers_ = function() {
    // Do actions whenever the user enters text.
    var outer_this = this;
    $('#login-form').on('keyup change', function(event) {
      outer_this.validateInput_(event);
    });

    $('#reset-password').click(function(event) {
      event.preventDefault();

      outer_this.handleForgottenPassword_();
    });
    $('#modal-password-reset').click(function(event) {
      outer_this.handleForgottenPassword_();
    });
    $('#return-button').click(function() {
      outer_this.showLogin_();
    });
  };

  /** Checks if the user's input is valid and enables/disables the submit button
   * accordingly.
   * @private
   */
  this.validateInput_ = function(event) {
    var email = $('#email').val();
    var password = $('#password').val();

    // Chrome (at least) has an idosyncrasy related to autofilling passwords:
    // http://code.google.com/p/chromium/issues/detail?id=352527#c17
    // Basically, the workaround for this is to check whether a change event
    // occurs and the email is filled in without any keyup events happening. If
    // this happens, it must be the browser autofill, so even though the
    // password hasn't registered, we should enable the login button.
    if (event.type == 'keyup') {
      this.keyUpTriggered_ = true;
    }

    if (!email) {
      // Empty email, this is a no-go.
      this.disableLogin_();
    } else if (password.length < 8) {
      if (event.type == 'change' && !this.keyUpTriggered_) {
        // Autofill.
        this.enableLogin_();
        return;
      }

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

  /** Performs the proper action when the "forgot password" link is clicked.
   * @private
   */
  this.handleForgottenPassword_ = function() {
    // Disable the login button.
    $('#login').prop('disabled', true);
    // Fade out the text.
    $('#reset-password').fadeOut();

    // Do the backend call.
    var email = $('#email').val()
    $.post('/forgot_password', {'email': email}, function() {
      $('#login-form').fadeOut(function() {
        $('#reset-password').show();

        $('#forgot-password').fadeIn();
      });
    });
  };

  /** Returns to the login screen from the forgotten password screen.
   * @private
   */
  this.showLogin_ = function() {
    $('#forgot-password').fadeOut(function() {
      $('#login-form').fadeIn();
    });

    // Clear the password field.
    $('#password').val('');
  };

  this.registerHandlers_();
};

$(document).ready(function() {
  box = new login.loginBox();
});
