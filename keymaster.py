from google.appengine.ext import db

import os

try:
    from Crypto.Cipher import ARC4
except ImportError:
    # Just pass through in dev mode
    class ARC4:
        new = classmethod(lambda k,x: ARC4)
        encrypt = classmethod(lambda k,x: x)
        decrypt = classmethod(lambda k,x: x)

class KeymasterError(Exception): pass

class Keymaster(db.Model):
    secret  = db.BlobProperty(required=True)

    @classmethod
    def encrypt(cls, key_name, secret):
        secret  = ARC4.new(os.environ['APPLICATION_ID']).encrypt(secret)
        k = cls.get_by_key_name(key_name)
        if k:
            k.secret = str(secret)
        else:
            k = cls(key_name=str(key_name), secret=str(secret))
        return k.put()

    @classmethod
    def decrypt(cls, key_name):
        k = cls.get_by_key_name(str(key_name))
        if not k:
            raise KeymasterError("Keymaster has no secret for %s" % key_name)
        return ARC4.new(os.environ['APPLICATION_ID']).encrypt(k.secret)

def get(key):
    return Keymaster.decrypt(key)
