from engines.top_attack_surfaces import build_top_attack_surfaces


def _derive_litigation_impact(finding):
    credibility_score = finding.get("credibility_score", 0)
    severity = finding.get("severity", 0)

    if credibility_score >= 8 or severity >= 9:
        return "high"

    if credibility_score >= 6 or severity >= 7:
        return "medium"

    return "low"


def build_litigation_impact(findings):
    report = []

    for finding in build_top_attack_surfaces(findings):
        enriched = dict(finding)
        enriched["litigation_impact"] = _derive_litigation_impact(finding)
        report.append(enriched)

    return report
