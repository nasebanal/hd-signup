# Signup Software for Hacker Dojo Global Network

Hacker Dojo is non-profit coworking space originated in Mountain View, California. Hacker Dojo distributes the source code for their operation software, and this is folked project in order to internationalize their assets with continuous integration environment.


[Prerequisite]

* Install Google App Engine SDK


[How to Use]

Step.1) Download the source code

 $ git clone https://github.com/nasebanal/hd-signup.git


Step.2) Test-run the software in your local environment.

 $ git rm shared
 $ git submodule add <Shared repository path> shared

Step.3) Launch the service on local.

 $ python deploy.py dev-server

Step.4) Register secret key to datastorage for encryption.
You can access console window from http://localhost:8080/_kh/key login as admin

 spreedly:hackerdojotest = e0cbfb79cc82ba9b5ff21ec2441feee92f535b7e

Then you can access this software through http://localhost:8080.
If you are using virtual machine technology, and want to forward the request and get response, you can use the following command instead of deploy.py.

 $ dev_appserver.py --host=0.0.0.0 .

Step.5) Create a new project in Google App Console window (https://appengine.google.com/). Determine Application ID which is unique in Google App Engine, and put the same id in application id of app.yaml.

Step.6) Deploy the souce code with the following command. Then you can access your web site from http://<application ID>.appspot.com.

 $ appcfg.py update .


[![Build Status](https://travis-ci.org/nasebanal/hd-signup.svg)](https://travis-ci.org/nasebanal/hd-signup)
