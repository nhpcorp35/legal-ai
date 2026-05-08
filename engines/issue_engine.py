# engines/issue_engine.py

import re


ENGINE_VERSION = "Issue Engine v3.1"


REQUIRED_DOCUMENT_TYPES = {
    "summary judgment motion": ["motion", "memo", "affirmation", "opposition"],
    "motion to dismiss": ["motion", "memo", "complaint", "opposition"],
    "default judgment motion": ["motion", "affirmation", "complaint"],
}


BURDEN_RULES = {
    "summary judgment motion": [
        "Movant must establish prima facie entitlement to judgment as a matter of law.",
        "Failure to satisfy the initial burden requires denial regardless of opposition proof.",
        "Triable issues of fact defeat summary judgment.",
    ],
    "motion to dismiss": [
        "Pleadings should be liberally construed.",
        "The Court must accept allegations as true at this stage.",
        "Documentary evidence must conclusively dispose of claims.",
    ],
}


DATE_PATTERNS = [
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2},\s+\d{4}\b",
]


WEAK_PHRASES = [
    "upon information and belief",
    "approximately",
    "appears to",
    "may have",
    "possibly",
    "unknown",
    "to be determined",
]


ATTACK_KEYWORDS = {
    "standing": "Standing challenge may be dispositive.",
    "jurisdiction": "Jurisdictional defects may defeat the action.",
    "notice": "Notice allegations may be factually insufficient.",
    "causation": "Causation proof may be incomplete or speculative.",
    "damages": "Damages proof may be unsupported.",
    "breach": "Breach allegations should be tested against documentary proof.",
    "contract": "Contract interpretation may control the outcome.",
    "discovery": "Discovery deficiencies may support procedural attack.",
    "documentary evidence": "Documentary evidence may contradict the allegations.",
}


FACT_RISK_TERMS = [
    "approximately",
    "unknown",
    "estimate",
    "unclear",
    "cannot recall",
    "believed",
]


CREDIBILITY_TERMS = [
    "inconsistent",
    "contradict",
    "changed testimony",
    "recanted",
    "false",
    "misleading",
]


def clean_text(value):
    return " ".join(str(value or "").split()).strip()


def detect_motion_type(selected_case, documents):
    selected_motion = clean_text((selected_case or {}).get("motion")).lower()

    if selected_motion:
        return selected_motion

    combined = " ".join(
        clean_text(doc.get("filename", "")).lower()
        for doc in documents
    )

    if "summary judgment" in combined:
        return "summary judgment motion"

    if "dismiss" in combined or "3211" in combined:
        return "motion to dismiss"

    if "default judgment" in combined:
        return "default judgment motion"

    return "general motion"


def detect_missing_documents(documents, motion_type):
    existing = set()

    for doc in documents:
        existing.add(doc.get("type", "other"))

    required = REQUIRED_DOCUMENT_TYPES.get(motion_type, [])

    missing = []

    for item in required:
        if item not in existing:
            missing.append(f"Missing expected document category: {item}.")

    return missing


def detect_burden_issues(motion_type):
    return BURDEN_RULES.get(motion_type, [])


def extract_dates(text):
    found = []

    for pattern in DATE_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)

        for match in matches:
            if match not in found:
                found.append(match)

    return found


def detect_date_contradictions(documents):
    date_map = {}

    for doc in documents:
        text = clean_text(doc.get("text") or doc.get("preview"))[:5000]
        filename = clean_text(doc.get("filename"))

        dates = extract_dates(text)

        for item in dates:
            date_map.setdefault(item, []).append(filename)

    contradictions = []

    for date_value, sources in date_map.items():
        unique_sources = list(set(sources))

        if len(unique_sources) >= 3:
            contradictions.append(
                f"Date '{date_value}' appears across multiple documents and should be verified for consistency."
            )

    return contradictions[:10]


def detect_weak_allegations(documents):
    weak = []

    for doc in documents:
        text = clean_text(doc.get("text") or doc.get("preview"))
        filename = clean_text(doc.get("filename"))

        lower = text.lower()

        for phrase in WEAK_PHRASES:
            if phrase in lower:
                weak.append(
                    f"Potential weak allegation language detected in {filename}: '{phrase}'."
                )

    return weak[:12]


def detect_attack_points(documents):
    findings = []

    combined = " ".join(
        clean_text(doc.get("text") or doc.get("preview"))
        for doc in documents
    ).lower()

    for keyword, message in ATTACK_KEYWORDS.items():
        if keyword in combined:
            findings.append(message)

    return findings[:12]


def detect_fact_risks(documents):
    risks = []

    for doc in documents:
        text = clean_text(doc.get("text") or doc.get("preview"))
        filename = clean_text(doc.get("filename"))

        lower = text.lower()

        for term in FACT_RISK_TERMS:
            if term in lower:
                risks.append(
                    f"Potential factual uncertainty detected in {filename}: '{term}'."
                )

    return risks[:10]


def detect_credibility_flags(documents):
    flags = []

    for doc in documents:
        text = clean_text(doc.get("text") or doc.get("preview"))
        filename = clean_text(doc.get("filename"))

        lower = text.lower()

        for term in CREDIBILITY_TERMS:
            if term in lower:
                flags.append(
                    f"Potential credibility issue detected in {filename}: '{term}'."
                )

    return flags[:10]


def rank_priority_issues(core_issues, contradictions, attack_points):
    ranked = []

    ranked.extend(attack_points[:3])
    ranked.extend(contradictions[:2])
    ranked.extend(core_issues[:3])

    unique = []

    for item in ranked:
        if item not in unique:
            unique.append(item)

    return unique[:8]


def build_issue_analysis(selected_case, documents=None, attorney_notes=None):
    """
    Core litigation issue detection engine.
    v3.1 rule-based implementation.
    """

    documents = documents or []
    attorney_notes = attorney_notes or []

    motion_type = detect_motion_type(selected_case, documents)

    missing_evidence = detect_missing_documents(documents, motion_type)
    burden_issues = detect_burden_issues(motion_type)
    contradictions = detect_date_contradictions(documents)
    weak_claims = detect_weak_allegations(documents)
    attack_points = detect_attack_points(documents)
    fact_risk_flags = detect_fact_risks(documents)
    credibility_flags = detect_credibility_flags(documents)

    core_issues = []
    core_issues.extend(burden_issues)
    core_issues.extend(missing_evidence)

    priority_ranking = rank_priority_issues(
        core_issues,
        contradictions,
        attack_points,
    )

    return {
        "engine": ENGINE_VERSION,
        "motion_type": motion_type,
        "core_issues": core_issues,
        "contradictions": contradictions,
        "attack_points": attack_points,
        "missing_evidence": missing_evidence,
        "weak_claims": weak_claims,
        "priority_ranking": priority_ranking,
        "attorney_notes": attorney_notes,
        "fact_risk_flags": fact_risk_flags,
        "credibility_flags": credibility_flags,
    }
