# engines/top_attack_surfaces.py


def build_top_attack_surfaces(findings, limit=None):
    findings = list(findings)

    findings.sort(
        key=lambda x: (
            x.get("attack_rank", 999),
            -x.get("credibility_score", 0),
            -x.get("severity", 0),
        )
    )

    if limit is not None:
        findings = findings[:limit]

    return findings