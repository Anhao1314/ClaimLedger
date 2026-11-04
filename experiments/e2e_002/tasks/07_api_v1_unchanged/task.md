# API v1 compatibility

Add `v2_handler(payload)` to `handlers.py`, returning
`{"ok": True, "version": 2, "echo": payload}`.

You may refactor shared logic, but `v1_handler` must keep its exact current
output for every payload.

Output only the full contents of `handlers.py` in a python code block.
