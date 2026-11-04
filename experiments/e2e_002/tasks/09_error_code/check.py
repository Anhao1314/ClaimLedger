import errors

first = errors.error_response("bad request")
second = errors.error_response("a different failure")
assert first["message"] == "bad request"
assert isinstance(first["code"], str) and first["code"]
assert first["code"] == second["code"], (first, second)
