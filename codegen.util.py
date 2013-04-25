# This program generates the credit-card style coupon codes

import hashlib, re

for serial in range(7000,8000):
   hash = hashlib.sha1(str(serial)+get_secret("code:hash")).hexdigest()
   hash = re.sub('[a-f]','',hash)[:8]
   print "1337 "+str(serial)+" "+hash[0:4]+" "+hash[4:8]
