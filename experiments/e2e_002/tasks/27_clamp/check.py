import clamp
assert clamp.clamp(5, 0, 10) == 5
assert clamp.clamp(-1, 0, 10) == 0
assert clamp.clamp(11, 0, 10) == 10
