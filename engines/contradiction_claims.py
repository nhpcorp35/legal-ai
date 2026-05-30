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
    r"\brequired\b",
    r"\bmandated\b",
    r"\bprohibited\b",
    r"\ballowed\b",
    r"\bconfirmed\b",
    r"\bagreed\b",
    r"\bexecuted\b",
    r"\bentered into\b",
]


NEGATIVE_PATTERNS = [
    r"\bnever\b",
    r"\bno\b",
    r"\bnot\b",
    r"\bdenies\b",
]


SPEAKER_PATTERNS = [
    "plaintiff",
    "defendant",
    "claimant",
    "respondent",
    "petitioner",
]


VERB_PATTERNS = [
    "alleges",
    "claims",
    "asserts",
    "states",
    "testified",
    "swore",
    "denies",
    "admits",
    "contends",
]


CLAIM_TYPE_PATTERNS = {
    "notice": [
        r"\bnotice\b",
        r"\binformed\b",
        r"\baware\b",
        r"\breceived\b",
        r"\bsent\b",
    ],
    "timeline": [
        r"\bbefore\b",
        r"\bafter\b",
        r"\bearlier\b",
        r"\blater\b",
        r"\boccurred\b",
    ],
    "causation": [
        r"\bcaused\b",
        r"\bresulted\b",
        r"\bled to\b",
        r"\bbecause\b",
    ],
    "witness": [
        r"\btestified\b",
        r"\bswore\b",
        r"\bdeposition\b",
        r"\baffidavit\b",
        r"\bwitness\b",
    ],
    "document": [
        r"\bcontract\b",
        r"\blease\b",
        r"\bagreement\b",
        r"\bemail\b",
        r"\bletter\b",
    ],
}


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


def determine_speaker(sentence):
    lowered = sentence.lower()

    for speaker in SPEAKER_PATTERNS:
        if re.search(rf"\b{speaker}\b", lowered):
            return speaker

    return "unknown"


def determine_claim_type(sentence):
    lowered = sentence.lower()

    for claim_type, patterns in CLAIM_TYPE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, lowered):
                return claim_type

    return "assertion"


def extract_fact_text(sentence):
    fact = sentence

    for speaker in SPEAKER_PATTERNS:
        fact = re.sub(
            rf"\b{speaker}\b",
            "",
            fact,
            flags=re.IGNORECASE,
        )

    for verb in VERB_PATTERNS:
        fact = re.sub(
            rf"\b{verb}\b",
            "",
            fact,
            flags=re.IGNORECASE,
        )

    fact = re.sub(r"\s+", " ", fact)

    return fact.strip(" .")


def build_claim(sentence):
    return {
        "text": sentence,
        "speaker": determine_speaker(sentence),
        "fact_text": extract_fact_text(sentence),
        "claim_type": determine_claim_type(sentence),
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
