"""
Regression-planning: alternative_pleading_candidate (Roadmap v7.2).

When implemented, flag claims (or findings) that use alternative pleading
language. Do not score those pairs as a major contradiction.
"""

from engines.contradiction_claims import extract_claims

REGRESSION_CASES = [
    (
        "locked_with_alternative_theory",
        (
            "Plaintiff alleges the door was locked. "
            "Alternatively, if the door was not locked, "
            "defendant negligently failed to secure it."
        ),
        True,
    ),
    (
        "in_the_alternative_phrasing",
        (
            "In the alternative, plaintiff alleges the door was "
            "locked at all relevant times."
        ),
        True,
    ),
    (
        "alternatively_if_not_proven",
        (
            "Alternatively, and only if the foregoing is not proven, "
            "defendant failed to secure the door at all times."
        ),
        True,
    ),
]


def _implementation_ready():
    for _, text, _ in REGRESSION_CASES:
        claims = extract_claims(text)
        if claims and "alternative_pleading_candidate" in claims[0]:
            return True
    return False


def _any_alternative_pleading_candidate(claims):
    return any(claim.get("alternative_pleading_candidate") for claim in claims)


if _implementation_ready():
    for name, text, expected in REGRESSION_CASES:
        claims = extract_claims(text)
        assert claims, f"No claims extracted for {name}:\n{text}"
        assert (
            _any_alternative_pleading_candidate(claims) == expected
        ), name
    print("PASS")
else:
    # Placeholder: documents desired behavior until v7.2 is implemented.
    assert True, (
        "PLANNED: set alternative_pleading_candidate when text includes "
        "'Alternatively,', 'In the alternative,', or "
        "'Alternatively, and only if the foregoing is not proven'. "
        "Do not treat as a major contradiction. "
        f"Cases: {[name for name, _, _ in REGRESSION_CASES]}"
    )
    print("ALTERNATIVE PLEADING REGRESSION PLAN DOCUMENTED")
