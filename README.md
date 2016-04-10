# Signup Software for Hacker Dojo Global Network

Hacker Dojo is non-profit coworking space originated in Mountain View, California. Hacker Dojo distributes the source code for their operation software, and this is folked project in order to internationalize their assets with continuous integration environment.


[Prerequisite]

* Install Google App Engine SDK


[How to Use]

Step.1) Download the source code

 $ git clone https://github.com/nasebanal/hd-signup.git


Step.2) If you want to have local translation, prepare translation file in translate directory.

Step.3) Test-run the software in your local environment.

 $ dev_appserver.py .

Then you can access this software through http://localhost:8080.
If you are using virtual machine technology, and want to forward the request and get response, you can use the following command instead.

 $ dev_appserver.py --host=0.0.0.0 .

Step.4) Create a new project in Google App Console window (https://appengine.google.com/). Determine Application ID which is unique in Google App Engine, and put the same id in application id of app.yaml.

Step.5) Deploy the souce code with the following command. Then you can access your web site from http://<application ID>.appspot.com.

 $ appcfg.py update .


[![Build Status](https://travis-ci.org/nasebanal/hd-signup.svg)](https://travis-ci.org/nasebanal/hd-signup)
