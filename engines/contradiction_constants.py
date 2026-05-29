ENGINE_VERSION = "Contradiction Engine v2.0"


CONTRADICTION_PATTERNS = [
    (
        "position_shift",
        [
            r"never",
            r"always",
            r"did not",
            r"later claimed",
            r"subsequently asserted",
        ],
    ),
    (
        "timeline_conflict",
        [
            r"before",
            r"after",
            r"earlier",
            r"later",
            r"same day",
            r"at that time",
        ],
    ),
    (
        "fact_vs_evidence",
        [
            r"claims",
            r"alleges",
            r"asserts",
            r"photograph",
            r"video",
            r"record",
            r"documentary evidence",
        ],
    ),
    (
        "document_conflict",
        [
            r"agreement",
            r"contract",
            r"lease",
            r"email",
            r"letter",
            r"notice",
        ],
    ),
    (
        "witness_conflict",
        [
            r"testified",
            r"stated",
            r"swore",
            r"deposition",
            r"affidavit",
        ],
    ),
    (
        "procedural_conflict",
        [
            r"served",
            r"filed",
            r"jurisdiction",
            r"venue",
            r"timely",
        ],
    ),
    (
        "authority_conflict",
        [
            r"holding",
            r"precedent",
            r"authority",
            r"case law",
            r"controlling",
        ],
    ),
    (
        "damages_conflict",
        [
            r"damages",
            r"loss",
            r"injury",
            r"expense",
            r"valuation",
        ],
    ),
    (
        "notice_conflict",
        [
            r"notice",
            r"aware",
            r"knowledge",
            r"informed",
        ],
    ),
    (
        "causation_conflict",
        [
            r"caused",
            r"resulted",
            r"led to",
            r"because of",
            r"proximate cause",
        ],
    ),
]
