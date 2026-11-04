import claims

assert claims.claim_strength(10) == "weak"
assert claims.claim_strength(99) == "weak"
assert claims.claim_strength(100) == "strong"
