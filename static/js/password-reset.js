/** Handles the password reset page. */

/** Pseudo-namespace for everything in this file. */
var passwordReset = {};

/** Class for handling the password box. */
passwordReset.passwordBox = function() {
  // Whether the submit button is enabled.
  this.submitEnabled_ = false;

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
    var password = $('#password').val();
    var verification = $('#verify').val();

    if (!password) {
      // Empty password, this is a no-go.
      this.showMessage_('');
      this.disableSubmit_();
    } else if (password.length < 8) {
      // Password is too short.
      this.disableSubmit_();
      this.showMessage_('Password must be at least 8 characters.');
    } else if (password != verification) {
      // They don't match.
      this.disableSubmit_();
      this.showMessage_('Passwords don\'t match.');
    } else {
      // It's okay.
      this.showMessage_('');
      this.enableSubmit_();
    }
  };

  /** Disables the submit button.
   * @private
   */
  this.disableSubmit_ = function() {
    if (!this.submitEnabled_) {
      return;
    }

    $('#submit').addClass('btn-disabled');
    $('#submit').prop('disabled', true);
    this.submitEnabled_ = false;
  };

  /** Enables the submit button.
   * @private
   */
  this.enableSubmit_ = function() {
    if (this.submitEnabled_) {
      return;
    }

    $('#submit').removeClass('btn-disabled');
    $('#submit').prop('disabled', false);
    this.submitEnabled_ = true;
  };

  /** Shows an error message if the validation fails.
   * @private
   * @param {String} message: The message to show.
   */
  this.showMessage_ = function(message) {
    $('#message').text(message);
  };

  this.registerHandlers_();
  // Do this initially to catch any autofill stuff.
  this.validateInput_();
};

$(document).ready(function() {
  box = new passwordReset.passwordBox();
});
