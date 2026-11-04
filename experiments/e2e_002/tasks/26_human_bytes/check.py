import bytesize
assert bytesize.human_bytes(1000) == "1.0 KB"
assert bytesize.human_bytes(1500) == "1.5 KB"
assert bytesize.human_bytes(2_000_000) == "2.0 MB"
