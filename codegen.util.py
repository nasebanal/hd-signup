# This program generates the credit-card style coupon codes

import hashlib

for serial in range(7001,8001):
   hash = hashlib.sha1(str(serial)+getsecret('code:hash')).hexdigest()[:8].upper()
   print "C22B "+str(serial)+" "+hash[0:4]+" "+hash[4:8]
