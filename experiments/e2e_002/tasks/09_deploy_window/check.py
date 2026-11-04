import deploy

assert deploy.can_deploy("Tuesday") is True
assert deploy.can_deploy("Monday") is False
assert deploy.can_deploy("Wednesday") is False
