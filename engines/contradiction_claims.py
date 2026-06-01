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


SOURCE_TYPES = [
    "affidavit",
    "affirmation",
    "deposition",
    "testimony",
    "declaration",
]


DOCUMENT_SUBJECTS = [
    "affidavit",
    "affirmation",
    "deposition",
    "declaration",
    "order",
    "decision",
    "lease",
    "contract",
    "agreement",
    "email",
    "letter",
    "notice",
]


DOCUMENT_ACTION_PATTERNS = {
    "require": [
        r"\brequire\b",
        r"\brequires\b",
        r"\brequired\b",
        r"\brequiring\b",
    ],
    "prohibit": [
        r"\bprohibit\b",
        r"\bprohibits\b",
        r"\bprohibited\b",
        r"\bprohibiting\b",
    ],
    "allow": [
        r"\ballow\b",
        r"\ballows\b",
        r"\ballowed\b",
        r"\ballowing\b",
        r"\bpermit\b",
        r"\bpermits\b",
        r"\bpermitted\b",
        r"\bpermitting\b",
    ],
    "mandate": [
        r"\bmandate\b",
        r"\bmandates\b",
        r"\bmandated\b",
        r"\bmandating\b",
    ],
    "confirm": [
        r"\bconfirm\b",
        r"\bconfirms\b",
        r"\bconfirmed\b",
        r"\bconfirming\b",
    ],
    "provide": [
        r"\bprovide\b",
        r"\bprovides\b",
        r"\bprovided\b",
        r"\bproviding\b",
    ],
    "state": [
        r"\bstate\b",
        r"\bstates\b",
        r"\bstated\b",
        r"\bstating\b",
    ],
    "execute": [
        r"\bexecute\b",
        r"\bexecutes\b",
        r"\bexecuted\b",
        r"\bexecuting\b",
    ],
}


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
    r"\bcause\b",
    r"\bcaused\b",
    r"\bcauses\b",
    r"\bcausing\b",
    r"\bresulted\b",
    r"\boccurred\b",
    r"\bbefore\b",
    r"\bafter\b",
    r"\bearlier\b",
    r"\blater\b",
    r"\bprovide\b",
    r"\bprovides\b",
    r"\bprovided\b",
    r"\bsend\b",
    r"\bsends\b",
    r"\bsent\b",
    r"\breceive\b",
    r"\breceives\b",
    r"\breceived\b",
    r"\brequire\b",
    r"\brequires\b",
    r"\brequired\b",
    r"\bmandate\b",
    r"\bmandates\b",
    r"\bmandated\b",
    r"\bprohibit\b",
    r"\bprohibits\b",
    r"\bprohibited\b",
    r"\ballow\b",
    r"\ballows\b",
    r"\ballowed\b",
    r"\bconfirm\b",
    r"\bconfirms\b",
    r"\bconfirmed\b",
    r"\bagree\b",
    r"\bagrees\b",
    r"\bagreed\b",
    r"\bexecute\b",
    r"\bexecutes\b",
    r"\bexecuted\b",
    r"\bentered into\b",
    r"\bpaid\b",
    r"\bpay\b",
    r"\bpays\b",
    r"\bpayment\b",
    r"\bpayments\b",
    r"\bowe\b",
    r"\bowes\b",
    r"\bowed\b",
    r"\bamount\b",
    r"\bbalance\b",
    r"\bdamages\b",
    r"\brent\b",
    r"\bdeposit\b",
    r"\bfee\b",
    r"\bfees\b",
    r"\b\d+\b",
    r"\$\s*\d+",
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
    "witness",
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


QUANTITY_PATTERNS = [
    r"\$\s*\d+(?:,\d{3})*(?:\.\d+)?",
    r"\b\d+(?:,\d{3})*(?:\.\d+)?\s+(?:payment|payments|installment|installments|days|months|years)\b",
    r"\b(?:paid|pay|pays|owed|owes|owe|amount|balance|damages|rent|deposit|fee|fees)\b",
]


CLAIM_TYPE_PATTERNS = {
    "quantity": QUANTITY_PATTERNS,
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
        r"\bcause\b",
        r"\bcaused\b",
        r"\bcauses\b",
        r"\bcausing\b",
        r"\bresulted\b",
        r"\bled to\b",
        r"\bbecause\b",
        r"\bresponsible for\b",
    ],
    "witness": [
        r"\btestified\b",
        r"\bswore\b",
        r"\bdeposition\b",
        r"\btestimony\b",
        r"\baffidavit\b",
        r"\bdeclaration\b",
        r"\bwitness\b",
    ],
    "document": [
        r"\bcontract\b",
        r"\blease\b",
        r"\bagreement\b",
        r"\bemail\b",
        r"\bletter\b",
        r"\bnotice\b",
        r"\baffidavit\b",
        r"\baffirmation\b",
        r"\bdeposition\b",
        r"\bdeclaration\b",
        r"\border\b",
        r"\bdecision\b",
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

    if any(
        re.search(pattern, lowered)
        for pattern in QUANTITY_PATTERNS
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

    if extract_witness_name(sentence):
        return "witness"

    for speaker in SPEAKER_PATTERNS:
        if re.search(rf"\b{speaker}\b", lowered):
            return speaker

    return "unknown"


def extract_witness_name(sentence):
    match = re.search(
        r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s+(?:testified|swore)\b",
        sentence,
    )

    if match:
        return match.group(1)

    return ""


def extract_source_type(sentence):
    lowered = sentence.lower()

    if re.search(r"\btestified\b|\btestimony\b", lowered):
        return "testimony"

    for source_type in SOURCE_TYPES:
        if re.search(rf"\b{source_type}\b", lowered):
            return source_type

    return "unknown"


def has_document_subject(sentence):
    lowered = sentence.lower()

    for subject in DOCUMENT_SUBJECTS:
        if re.search(rf"\b{subject}\b", lowered):
            return True

    return False


def has_document_action(sentence):
    lowered = sentence.lower()

    for patterns in DOCUMENT_ACTION_PATTERNS.values():
        for pattern in patterns:
            if re.search(pattern, lowered):
                return True

    return False


def is_document_claim(sentence):
    return (
        has_document_subject(sentence)
        and has_document_action(sentence)
    )


def is_quantity_claim(sentence):
    lowered = sentence.lower()

    return any(
        re.search(pattern, lowered)
        for pattern in QUANTITY_PATTERNS
    )


def determine_claim_type(sentence):
    lowered = sentence.lower()

    if is_document_claim(sentence):
        return "document"

    if is_quantity_claim(sentence):
        return "quantity"

    for claim_type, patterns in CLAIM_TYPE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, lowered):
                return claim_type

    return "assertion"


def normalize_fact_text(fact):
    fact = clean_text(fact)

    fact = re.sub(
        r"\b(did|does|do)\b",
        "",
        fact,
        flags=re.IGNORECASE,
    )

    fact = re.sub(
        r"\b(never|not|no)\b",
        "",
        fact,
        flags=re.IGNORECASE,
    )

    fact = re.sub(
        r"\b(caused|causes|causing)\b",
        "cause",
        fact,
        flags=re.IGNORECASE,
    )

    fact = re.sub(
        r"\bresulted in\b",
        "cause",
        fact,
        flags=re.IGNORECASE,
    )

    fact = re.sub(
        r"\bled to\b",
        "cause",
        fact,
        flags=re.IGNORECASE,
    )

    fact = re.sub(r"\s+", " ", fact)

    return fact.strip(" .").lower()


def extract_fact_text(sentence):
    fact = sentence

    witness_name = extract_witness_name(sentence)

    if witness_name:
        fact = re.sub(
            re.escape(witness_name),
            "",
            fact,
            flags=re.IGNORECASE,
        )

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

    return normalize_fact_text(fact)


def extract_timeline_relation(sentence):
    lowered = sentence.lower()

    if re.search(r"\bbefore\b|\bearlier\b", lowered):
        return "before"

    if re.search(r"\bafter\b|\blater\b", lowered):
        return "after"

    return ""


def extract_timeline_date(sentence):
    lowered = clean_text(sentence).lower()

    match = re.search(
        r"\b(?:before|after|earlier than|later than)\s+"
        r"([a-z]+\.?\s+\d{1,2}(?:,\s*\d{4})?)\b",
        lowered,
    )

    if match:
        return clean_text(match.group(1)).strip(" .,")

    match = re.search(
        r"\b(?:before|after|earlier than|later than)\s+"
        r"(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\b",
        lowered,
    )

    if match:
        return clean_text(match.group(1)).strip(" .,")

    match = re.search(
        r"\b(?:before|after|earlier than|later than)\s+"
        r"(\d{4}-\d{1,2}-\d{1,2})\b",
        lowered,
    )

    if match:
        return clean_text(match.group(1)).strip(" .,")

    return ""


def extract_timeline_event(sentence):
    claim_type = determine_claim_type(sentence)

    if claim_type != "timeline":
        return ""

    fact = extract_fact_text(sentence)

    fact = re.sub(
        r"\b(before|after|earlier|later)\b.*$",
        "",
        fact,
        flags=re.IGNORECASE,
    )

    fact = re.sub(r"\s+", " ", fact)

    return fact.strip(" .").lower()


def extract_document_subject(sentence):
    lowered = sentence.lower()

    for subject in DOCUMENT_SUBJECTS:
        if re.search(rf"\b{subject}\b", lowered):
            return subject

    return ""


def extract_document_action(sentence):
    lowered = sentence.lower()

    for action, patterns in DOCUMENT_ACTION_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, lowered):
                return action

    return ""

def extract_document_requirement(sentence):
    subject = extract_document_subject(sentence)
    action = extract_document_action(sentence)

    if not subject or not action:
        return ""

    fact = extract_fact_text(sentence)

    subject_pattern = rf"\b(the\s+)?{re.escape(subject)}\b"
    fact = re.sub(
        subject_pattern,
        "",
        fact,
        flags=re.IGNORECASE,
    )

    action_patterns = DOCUMENT_ACTION_PATTERNS.get(
        action,
        [],
    )

    for pattern in action_patterns:
        fact = re.sub(
            pattern,
            "",
            fact,
            flags=re.IGNORECASE,
        )

    fact = re.sub(
        r"\bthat\b",
        "",
        fact,
        flags=re.IGNORECASE,
    )

    fact = re.sub(r"\s+", " ", fact)

    return fact.strip(" .").lower()


def extract_quantity_value(sentence):
    lowered = sentence.lower()

    money_match = re.search(
        r"\$\s*(\d+(?:,\d{3})*(?:\.\d+)?)",
        lowered,
    )

    if money_match:
        return float(money_match.group(1).replace(",", ""))

    number_match = re.search(
        r"\b(\d+(?:,\d{3})*(?:\.\d+)?)\b",
        lowered,
    )

    if number_match:
        return float(number_match.group(1).replace(",", ""))

    return None


def extract_quantity_unit(sentence):
    lowered = sentence.lower()

    if re.search(r"\$", lowered):
        return "dollars"

    unit_match = re.search(
        r"\b\d+(?:,\d{3})*(?:\.\d+)?\s+"
        r"(payment|payments|installment|installments|days|months|years)\b",
        lowered,
    )

    if unit_match:
        return unit_match.group(1)

    if re.search(r"\b(payment|payments|paid|pay|pays)\b", lowered):
        return "payments"

    if re.search(r"\b(rent|deposit|fee|fees|damages|amount|balance|owed|owes|owe)\b", lowered):
        return "dollars"

    return ""


def extract_quantity_subject(sentence):
    fact = extract_fact_text(sentence)

    fact = re.sub(
        r"\$\s*\d+(?:,\d{3})*(?:\.\d+)?",
        "",
        fact,
    )

    fact = re.sub(
        r"\b\d+(?:,\d{3})*(?:\.\d+)?\b",
        "",
        fact,
    )

    fact = re.sub(r"\s+", " ", fact)

    return fact.strip(" .").lower()


def build_claim(sentence):
    claim_type = determine_claim_type(sentence)

    claim = {
        "text": sentence,
        "speaker": determine_speaker(sentence),
        "witness_name": extract_witness_name(sentence),
        "fact_text": extract_fact_text(sentence),
        "claim_type": claim_type,
        "polarity": determine_polarity(sentence),
        "source_type": extract_source_type(sentence),
    }

    if claim_type == "timeline":
        claim["timeline_event"] = extract_timeline_event(sentence)
        claim["timeline_relation"] = extract_timeline_relation(sentence)
        claim["timeline_date"] = extract_timeline_date(sentence)

    if claim_type == "document":
        claim["document_subject"] = extract_document_subject(sentence)
        claim["document_action"] = extract_document_action(sentence)
        claim["document_requirement"] = extract_document_requirement(sentence)

    if claim_type == "quantity":
        claim["quantity_value"] = extract_quantity_value(sentence)
        claim["quantity_unit"] = extract_quantity_unit(sentence)
        claim["quantity_subject"] = extract_quantity_subject(sentence)

    return claim


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
