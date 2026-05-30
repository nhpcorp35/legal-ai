from engines.contradiction_claims import extract_claims


def extract_document_claims(document):
    claims = extract_claims(
        document.get("text", "")
    )

    filename = document.get(
        "filename",
        "",
    )

    document_type = document.get(
        "type",
        "",
    )

    enriched_claims = []

    for claim in claims:

        enriched = dict(claim)

        enriched["source_document"] = filename
        enriched["source_type"] = document_type

        enriched_claims.append(
            enriched
        )

    return enriched_claims


def extract_claims_from_documents(documents):
    claims = []

    for document in documents:
        claims.extend(
            extract_document_claims(
                document
            )
        )

    return claims
