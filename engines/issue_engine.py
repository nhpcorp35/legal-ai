ENGINE_VERSION = "Issue Engine v3.0"


def build_issue_analysis(selected_case, documents=None, attorney_notes=None):
    """
    Core litigation issue detection engine.
    v3.0 skeleton only.
    """

    documents = documents or []
    attorney_notes = attorney_notes or []

    return {
        "engine": ENGINE_VERSION,
        "core_issues": [],
        "contradictions": [],
        "attack_points": [],
        "missing_evidence": [],
        "weak_claims": [],
        "priority_ranking": [],
        "attorney_notes": attorney_notes,
        "fact_risk_flags": [],
        "credibility_flags": [],
    }
