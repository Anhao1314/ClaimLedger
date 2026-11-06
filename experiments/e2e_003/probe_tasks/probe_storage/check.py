import storage

assert storage.BACKEND == "postgresql", storage.BACKEND
assert storage.connect("postgresql://u@h/db").startswith("postgresql://")
try:
    storage.connect("sqlite:///tmp.db")
except ValueError:
    pass
else:
    raise AssertionError("sqlite DSN was accepted")
