import hashlib
import hashing
assert hashing.sha256_hex("abc") == hashlib.sha256(b"abc").hexdigest()
