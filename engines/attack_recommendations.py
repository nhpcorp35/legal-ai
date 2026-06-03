from engines.top_attack_surfaces import build_top_attack_surfaces

ATTACK_RECOMMENDATIONS = {
    "credibility_conflict": "deposition impeachment",
    "document_conflict": "challenge document authenticity",
    "timeline_conflict": "challenge chronology",
}


def _derive_attack_recommendation(finding):
    conflict_type = finding.get("type", "")
    return ATTACK_RECOMMENDATIONS.get(
        conflict_type,
        "review conflicting claims",
    )


def build_attack_recommendations(findings):
    report = []

    for finding in build_top_attack_surfaces(findings):
        enriched = dict(finding)
        enriched["attack_recommendation"] = _derive_attack_recommendation(finding)
        report.append(enriched)

    return report
