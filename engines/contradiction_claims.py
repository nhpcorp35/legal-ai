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


FACT_PATTERNS = [
    r"\bnever\b",
    r"\balways\b",
    r"\bno\b",
    r"\byes\b",
    r"\bnot\b",
    r"\bwas\b",
    r"\bwere\b",
    r"\bis\b",
    r"\bare\b",
    r"\bcaused\b",
    r"\bresulted\b",
    r"\boccurred\b",
    r"\bprovided\b",
    r"\bsent\b",
    r"\breceived\b",
]


NEGATIVE_PATTERNS = [
    r"\bnever\b",
    r"\bno\b",
    r"\bnot\b",
    r"\bdenies\b",
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


def is_claim(sentence):
    lowered = sentence.lower()

    if any(
        re.search(pattern, lowered)
        for pattern in CLAIM_PATTERNS
    ):
        return True

    if any(
        re.search(pattern, lowered)
        for pattern in FACT_PATTERNS
    ):
        return True

    return False


def determine_polarity(sentence):
    lowered = sentence.lower()

    if any(
        re.search(pattern, lowered)
        for pattern in NEGATIVE_PATTERNS
    ):
        return "negative"

    return "positive"


def build_claim(sentence):
    return {
        "text": sentence,
        "claim_type": "assertion",
        "polarity": determine_polarity(sentence),
    }


def extract_claims(text):
    text = clean_text(text)

    claims = []

    for sentence in split_sentences(text):

        sentence = sentence.strip()

        if len(sentence) < 20:
            continue

        if is_claim(sentence):
            claims.append(
                build_claim(sentence)
            )

    return claims
