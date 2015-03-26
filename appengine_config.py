"""
`appengine_config.py` gets loaded every time a new instance is started.

Use this file to configure app engine modules as defined here:
https://developers.google.com/appengine/docs/python/tools/appengineconfig
"""

import os
import shutil
import subprocess

from google.appengine.ext import vendor


# Use external libraries.
vendor.add("externals")
