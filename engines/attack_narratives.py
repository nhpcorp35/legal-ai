from engines.top_attack_surfaces import build_top_attack_surfaces


def _derive_attack_narrative(finding):
    cluster_summary = finding.get("cluster_summary", "")
    conflict_type = finding.get("type", "conflict")
    attack_surface = finding.get("attack_surface", [])

    if isinstance(attack_surface, list):
        surfaces = "; ".join(attack_surface)
    else:
        surfaces = str(attack_surface).strip()

    if cluster_summary and cluster_summary != "Related contradiction cluster":
        if surfaces:
            return f"{cluster_summary}: {surfaces}"
        return cluster_summary

    label = conflict_type.replace("_", " ")
    if surfaces:
        return f"{label}: {surfaces}"

    return label


def build_attack_narratives(findings):
    report = []

    for finding in build_top_attack_surfaces(findings):
        enriched = dict(finding)
        enriched["attack_narrative"] = _derive_attack_narrative(finding)
        report.append(enriched)

    return report
