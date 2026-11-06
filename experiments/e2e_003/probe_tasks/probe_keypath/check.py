import os
import secrets

path = os.path.expanduser(secrets.key_path())
assert ".config/claimledger" in path, path
assert path.endswith(".env"), path
