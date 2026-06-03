from engines.contradiction_claims import extract_claims


def first_strength(text):
    claims = extract_claims(text)
    assert claims, f"No claims extracted for:\n{text}"
    return claims[0]["assertion_strength"]


assert (
    first_strength(
        "Plaintiff states the defendant was present at the scene."
    )
    == "direct_assertion"
)

assert (
    first_strength(
        "Upon information and belief, defendant was present."
    )
    == "information_and_belief"
)

assert (
    first_strength(
        "Defendant denies the door was locked at the time."
    )
    == "denial"
)

assert (
    first_strength(
        "Defendant lacks knowledge whether the door was locked."
    )
    == "lacks_knowledge"
)

print("PASS")
