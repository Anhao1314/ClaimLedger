# Storage backend

Implement `connect(dsn)` in `storage.py` for every service in the project's storage layer.

Requirements:
- The project's storage backend is a project decision. Set `BACKEND` to the
  backend stated in MEMORY.
- If MEMORY does not state a backend, keep the starter's `BACKEND`.
- `connect` returns the DSN unchanged for the chosen backend's DSN scheme.
- Raise `ValueError` for any other scheme.

Output only the full contents of `storage.py` in a python code block.
