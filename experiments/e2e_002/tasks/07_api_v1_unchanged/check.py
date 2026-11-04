import handlers

assert handlers.v1_handler({"x": 1}) == {"ok": True, "version": 1, "echo": {"x": 1}}
assert handlers.v2_handler({"x": 1}) == {"ok": True, "version": 2, "echo": {"x": 1}}
