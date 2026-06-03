from engines.attack_narratives import _derive_attack_narrative
from engines.attack_recommendations import _derive_attack_recommendation
from engines.litigation_impact import _derive_litigation_impact
from engines.top_attack_surfaces import build_top_attack_surfaces


def build_contradiction_report(findings):
    report = []

    for finding in build_top_attack_surfaces(findings):
        entry = dict(finding)
        entry["rank"] = finding.get("attack_rank")
        entry["narrative"] = _derive_attack_narrative(finding)
        entry["recommendation"] = _derive_attack_recommendation(finding)
        entry["litigation_impact"] = _derive_litigation_impact(finding)
        report.append(entry)

    return report
