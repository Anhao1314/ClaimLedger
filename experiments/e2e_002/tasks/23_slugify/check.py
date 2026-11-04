import slug
assert slug.slugify("Hello, World!") == "hello-world"
assert slug.slugify("  A  B  ") == "a-b"
assert slug.slugify("---") == ""
