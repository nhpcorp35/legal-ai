# matter_builder.py

from types import SimpleNamespace


def clean_text(value):
    return " ".join(str(value or "").split()).strip()


def build_empty_matter(search_value=""):
    """
    Foundation object for Matter Builder v1.

    This is intentionally simple:
    - no ingestion yet
    - no parsing yet
    - no document matching yet

    Goal:
    stable structure + rendering first
    """

    return SimpleNamespace(
        search_value=clean_text(search_value),

        # top-level matter identity
        title="Matter Builder",
        matter_name="",
        index_number="",
        court="",
        judge="",
        status="",

        # grouped documents
        complaint=[],
        answer=[],
        motions=[],
        affirmations=[],
        oppositions=[],
        declarations=[],
        exhibits=[],
        memorandum_of_law=[],
        prior_orders=[],
        decisions=[],
    )


def get_matter(search_value=""):
    """
    Public entry point used by app.py route.

    Later this will:
    - search by index number
    - search by case name
    - group matching filings
    - build one unified matter page

    For v1:
    return stable empty structure only.
    """

    matter = build_empty_matter(search_value)

    if search_value:
        matter.matter_name = clean_text(search_value)
        matter.title = f"Matter: {matter.matter_name}"

    return matter