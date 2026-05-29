import re


CLAIM_PATTERNS = [
    r"\balleges\b",
    r"\bclaims\b",
    r"\basserts\b",
    r"\bstates\b",
    r"\btestified\b",
    r"\bswore\b",
    r"\bdenies\b",
    r"\badmits\b",
    r"\bcontends\b",
]


def clean_text(text):
    if not text:
        return ""

    return re.sub(r"\s+", " ", str(text)).strip()


def split_sentences(text):
    return re.split(
        r"(?<=[.!?])\s+",
        text,
    )


def extract_claims(text):
    text = clean_text(text)

    claims = []

    for sentence in split_sentences(text):

        lowered = sentence.lower()

        if any(
            re.search(pattern, lowered)
            for pattern in CLAIM_PATTERNS
        ):
            claims.append(sentence.strip())

    return claims
