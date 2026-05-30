from engines.contradiction_document_claims import (
    extract_claims_from_documents,
)

from engines.contradiction_comparison import (
    compare_claims,
)


def detect_cross_document_conflicts(documents):
    claims = extract_claims_from_documents(
        documents
    )

    return compare_claims(claims)
