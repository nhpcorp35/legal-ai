#!/usr/bin/env python3
"""Create one bounded, cited, internal-only draft from verified B2 page indexes."""
from __future__ import annotations

import argparse, hashlib, json, os, re, socket, sys, tempfile, urllib.error, urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

# Railway executes this file by path, which otherwise exposes only ``scripts``
# on sys.path. Keep the repository-root package import identical in script and
# module execution modes.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines.litigation_reasoning import (
    MOTION_RECOMMENDATION_RE,
    MOTION_RESPONSE_RE,
    build_reasoning_context,
    classify_page,
    question_mode,
)
from engines.verified_authority_registry import match_verified_authorities

MAX_PAGES, MAX_PAGE_CHARS, MAX_CONTEXT_CHARS = 45, 2200, 75000
CONSOLIDATED_MAX_PAGES, CONSOLIDATED_MAX_CONTEXT_CHARS = 80, 130000
CASE_RE = re.compile(r"NY-[A-Za-z]+-[0-9]{6}-[0-9]{4}-[A-Za-z0-9-]{2,80}$")
CASE00_BENCHMARK_ID = "Case-00-Triborough"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
REVIEWED_AUTHORITY_KEY = "derived/reviewed-authorities"
OCR_PAGE_RECORDS_SUFFIX = "page_records.ocr-v1.jsonl"
BROAD_RECORD_TERMS = frozenset({"parties", "claims", "causes", "defenses", "relief"})
PLEADING_FILENAME_RE = re.compile(
    r"\b(?:complaint|answer|reply|cross(?:[ _-]?claim|[ _-]?c\b)|"
    r"counter(?:[ _-]?claim|[ _-]?c\b)|"
    r"third[ _-]?party|fourth[ _-]?party|bill[s]? of particulars)\b",
    re.IGNORECASE,
)
PLEADING_TEXT_RE = re.compile(
    r"\b(?:cause of action|wherefore|affirmative defense|cross[ -]?claim|"
    r"counter[ -]?claim|third[ -]?party|plaintiff|defendant)\b",
    re.IGNORECASE,
)
PLEADING_OPERATIONAL_TEXT_RE = re.compile(
    r"\b(?:cause of action|wherefore|prayer for relief|affirmative defense|"
    r"den(?:y|ies|ied)|cross[ -]?claim|counter[ -]?claim|"
    r"contractual indemnification|common[ -]?law indemnification|contribution)\b",
    re.IGNORECASE,
)
PLEADING_PARTY_ROLE_TEXT_RE = re.compile(
    r"\b(?:owner(?:ship)?|title(?:d)?|landlord|tenant|occup(?:y|ied|ancy)|"
    r"manager|member|principal|officer|agent|control(?:led|s)?)\b",
    re.IGNORECASE,
)
PARTY_ROLE_FACT_TEXT_RE = re.compile(
    r"\b(?:joint\s+|co[- ]?)owner(?:ship)?\b|\b(?:never|did not)\s+"
    r"(?:resid(?:e|ed)|live(?:d)?|occup(?:y|ied))\b|\bno\s+control\b",
    re.IGNORECASE,
)
PLEADING_SECTION_START_RE = re.compile(
    r"\b(?:verified\s+)?answer\b(?:\s+to\s+(?:verified\s+)?"
    r"(?:(?:second|third|fourth)\s+)?(?:third[ -]?party\s+)?complaint)?",
    re.IGNORECASE,
)
MERITS_PLEADING_PAGE_LIMIT = 45
MERITS_PLEADING_PAGES_PER_FILING = 3
MERITS_COMPLAINT_PAGES_PER_FILING = 8
# Every mandatory pleading page fits within MAX_CONTEXT_CHARS (45 × 1600).
MERITS_PLEADING_PAGE_CHARS = 1600
AFFIRMATIVE_DEFENSES_RE = re.compile(r"\baffirmative\s+defen[cs]es?\b", re.IGNORECASE)
PLEADING_FOCUSED_QUESTION_RE = re.compile(
    r"\b(?:affirmative\s+defen[cs]e|answer\s+to\s+(?:a\s+)?third[ -]?party|"
    r"third[ -]?party\s+complaint|cross[ -]?claim|counter[ -]?claim)\b",
    re.IGNORECASE,
)
MAIN_ACTION_ONLY_QUESTION_RE = re.compile(
    r"\bmain (?:action|case)(?: only)?\b|"
    r"\bplaintiff(?:[\'’]s|s[\'’]?)?\s+claims\s+against\b|"
    r"\boperative\s+complaint\s+and\s+answer\s+pages\b",
    re.IGNORECASE,
)
CROSS_CLAIM_ONLY_QUESTION_RE = re.compile(
    r"\b(?:(?:all|every)\s+)?counterclaims?\s+and\s+cross[ -]?claims?\b|"
    r"\bcross[ -]?claims?\s+and\s+counterclaims?\b|"
    r"\bmain action\b.*\b(?:counterclaims?|cross[ -]?claims?)\b",
    re.IGNORECASE,
)
COUNTER_CROSS_FILING_RE = re.compile(
    r"\b(?:cross[ -]?(?:claims?|c)|counter(?:[ -]?claims?|c)|"
    r"reply\s+to\s+(?:cross[ -]?claims?|counterclaims?)|"
    r"answer\s+to\s+(?:cross[ -]?claims?|counterclaims?))\b",
    re.IGNORECASE,
)
THIRD_PARTY_ONLY_QUESTION_RE = re.compile(
    r"\bthird[ -]?party(?:[ -]?claims?)?\s+layer\b|"
    r"\b(?:validate|identify|map)\b.*\bthird[ -]?party\s+claims?\b.*\bseparately\b|"
    r"\bthird[ -]?party\s+claims?\b.*\bseparately\s+from\s+the\s+main\s+(?:action|case)\b",
    re.IGNORECASE,
)
CONSOLIDATED_LITIGATION_MAP_RE = re.compile(
    r"\bmain\s+(?:case|action)\b.*\bcounterclaims?\s+and\s+cross[ -]?claims?\b.*\bthird[ -]?party\s+claims?\b",
    re.IGNORECASE | re.DOTALL,
)
CROSS_CLAIM_ASSERTING_PARTY_RE = re.compile(
    r"\basserted\s+by\s+(.+?)(?=,\s+the\s+parties\b|,\s+each\b|\.\s|$)",
    re.IGNORECASE,
)
PLEADING_CLAIM_TEXT_RE = re.compile(
    r"\b(?:cause of action|cross[ -]?claim|counter[ -]?claim|"
    r"negligence|breach of contract|contractual indemnification|"
    r"common[ -]?law indemnification|contribution|malicious prosecution|"
    r"private nuisance|harassment|menacing|intentional infliction of "
    r"emotional distress)\b|"
    r"\blabor\s+law\s*(?:§|section|sec\.?\s*)?\s*(?:200|240|241)\b",
    re.IGNORECASE,
)
PLEADING_RELIEF_TEXT_RE = re.compile(
    r"\b(?:wherefore|prayer for relief|demands? judgment|requests? judgment|"
    r"judgment (?:be )?(?:entered|granted)|dismiss(?:al|ing)|"
    r"damages(?:,|\s+and|\s+in)|costs? and disbursements)\b",
    re.IGNORECASE,
)
PLEADING_PRAYER_START_RE = re.compile(
    r"\b(?:wherefore|prayer for relief)\b",
    re.IGNORECASE,
)
THIRD_PARTY_COMPLAINT_QUESTION_RE = re.compile(
    r"\bthird[ -]?party\s+complaint\b",
    re.IGNORECASE,
)
TARGETED_THIRD_PARTY_COMPLAINT_PAGE_LIMIT = 16
THIRD_PARTY_ACTION_PAGE_LIMIT = 11
THIRD_PARTY_ORDINALS = ("first", "second", "third", "fourth")
THIRD_PARTY_ORDINAL_RE = re.compile(
    r"\b(first|second|third|fourth)\s+third[ -]?party\b", re.IGNORECASE
)
THIRD_PARTY_CAPTION_STOPWORDS = frozenset({
    "against", "answer", "complaint", "corp", "corporation", "defendant",
    "defendants", "first", "fourth", "inc", "llc", "party", "plaintiff",
    "plaintiffs", "second", "summons", "third", "verified",
})
TOP_ATTACK_SURFACES_MARKER = "v4.0 top attack surfaces report"
STRATEGIC_ANALYSIS_QUESTION_RE = re.compile(
    r"\b(?:weakest|strongest|strengths?|weaknesses?|shortcomings?|"
    r"vulnerabilit(?:y|ies)|likely\s+to\s+(?:win|lose)|"
    r"(?:most\s+)?(?:outcome[ -]?)?determinative|"
    r"(?:legally\s+)?defensib(?:le|ility)|"
    r"prove\s+or\s+disprove|"
    r"which\s+(?:side|argument|position)|compare\s+(?:the\s+)?"
    r"(?:parties|positions|arguments)|evaluate|assessment|"
    r"summary[ -]?judgment\s+prospects?|attack\s+surfaces?|"
    r"motions?\s+(?:should|could|can)\s+(?:i|we|counsel)|"
    r"motions?\s+(?:to\s+)?consider|answer\s+(?:the\s+)?motion|"
    r"oppose\s+(?:the\s+)?motion|respond\s+to\s+(?:the\s+)?motion|"
    r"(?:my\s+)?opponent\s+(?:made|filed)\s+(?:(?:an?\s+)|this\s+)?motion)\b",
    re.IGNORECASE,
)
STRATEGIC_SOURCE_FILENAME_RE = re.compile(
    r"\b(?:expert|affidavit|affirmation|report|memorandum|memo|brief|"
    r"order|decision|judgment|survey|site[ _-]?plan|permit|application)\b",
    re.IGNORECASE,
)
STRATEGIC_EXPERT_TEXT_RE = re.compile(
    r"\b(?:expert|professional\s+(?:engineer|surveyor)|"
    r"reasonable\s+(?:engineering|professional)\s+certainty|"
    r"expert\s+(?:opinion|report)|I\s+(?:conclude|opine)|"
    r"licensed\s+(?:engineer|surveyor))\b",
    re.IGNORECASE,
)
STRATEGIC_MEASUREMENT_TEXT_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:feet|foot|ft\.?|inches?|acres?|"
    r"square\s+feet|percent|%)\b|\b(?:dimensions?|measurements?|"
    r"boundary|property\s+line|setback|waterfront|site\s+plan|survey)\b",
    re.IGNORECASE,
)
STRATEGIC_LAW_TEXT_RE = re.compile(
    r"\b(?:statut(?:e|ory)|regulation|regulatory|(?:N\.?Y\.?)?\s*"
    r"ECL|CPLR|DEC|code|ordinance|riparian|navigation|equity|"
    r"equitable|precedent|court\s+held)\b|\b\d+\s+NY(?:2d|3d)\b",
    re.IGNORECASE,
)
STRATEGIC_POSITION_TEXT_RE = re.compile(
    r"\b(?:plaintiff|defendant|claimant|petitioner|respondent|movant)\b"
    r".{0,180}\b(?:alleges?|argues?|contends?|asserts?|maintains?|"
    r"opposes?|denies?|claims?)\b",
    re.IGNORECASE | re.DOTALL,
)
# A strategic packet must fit into the fixed 45-page context window while
# retaining primary posture and agency material. Previously the 18-page
# expert reservation could consume the window before either was selected.
STRATEGIC_MERITS_PAGE_LIMIT = 10
STRATEGIC_CATEGORY_PAGE_LIMIT = 4
STRATEGIC_EXPERT_PAGE_LIMIT = 12
STRATEGIC_EXPERT_PAGES_PER_DOCUMENT = 6
STRATEGIC_PROCEDURAL_PAGE_LIMIT = 5
STRATEGIC_REGULATORY_PAGE_LIMIT = 4
STRATEGIC_PROCEDURAL_RECORD_RE = re.compile(
    r"\b(?:order\s+to\s+show\s+cause|temporary\s+restraining\s+order|"
    r"\bTRO\b|preliminary\s+injunction|notice\s+of\s+motion|"
    r"undertaking|bond)\b",
    re.IGNORECASE,
)
DIRECT_REGULATORY_RECORD_RE = re.compile(
    r"\b(?:New\s+York\s+State\s+Department\s+of\s+Environmental\s+Conservation|"
    r"NYSDEC|Department\s+of\s+Environmental\s+Conservation|"
    r"United\s+States\s+Army\s+Corps\s+of\s+Engineers|U\.?S\.?\s+Army\s+Corps)\b"
    r".{0,300}\b(?:permit|permittee|facility|DECID|authorization|condition|inspection)\b|"
    r"\b(?:DECID\s*(?:No\.?|#)?\s*[0-9-]+|NAN-\d{4}-\d+)\b",
    re.IGNORECASE | re.DOTALL,
)
STRATEGIC_ADVOCACY_FILENAME_RE = re.compile(
    r"\b(?:affidavit|affirmation|memorandum|memo|brief|report)\b",
    re.IGNORECASE,
)
DIRECT_NYSDEC_RECORD_RE = re.compile(
    r"(?:New\s*York\s*State\s*Department\s*of\s*Environmental\s*Conservation|"
    r"NYS\s*DEC|DECID\s*(?:No\.?|#)?\s*[0-9-]+)",
    re.IGNORECASE,
)
DIRECT_USACE_RECORD_RE = re.compile(
    r"(?:United\s*States\s*Army\s*Corps\s*of\s*Engineers|"
    r"U\.?S\.?\s*Army\s*Corps|NAN-\d{4}-\d+)",
    re.IGNORECASE,
)


def direct_agency_issuer(page):
    """Return a directly identified regulatory-record issuer."""
    filename = str(page.get("filename") or "")
    text = str(page.get("text") or "")
    if (
        STRATEGIC_ADVOCACY_FILENAME_RE.search(filename)
        or classify_page(page)["source_type"] != "regulatory_record"
    ):
        return None
    if DIRECT_NYSDEC_RECORD_RE.search(text):
        return "nysdec"
    if DIRECT_USACE_RECORD_RE.search(text):
        return "usace"
    return None

V4_PROCEDURAL_ORDER_TEXT_RE = re.compile(r"\b(?:death|deceased|substitut(?:e|ion)|representative|jurisdiction)\b", re.IGNORECASE)
PROCEDURAL_POSTURE_QUESTION_RE = re.compile(
    r"\b(?:death|deceased|substitut(?:e|ion)|representative|jurisdiction|"
    r"summary[ -]judg(?:ment|ment motion)|merits decision|procedural disposition)\b",
    re.IGNORECASE,
)
RETRIEVAL_VALIDATION_PROFILES = {
    "main-action": (
        "Identify the plaintiffs claims in the main action against the defendants "
        "including defenses requested relief death substitution jurisdiction and "
        "summary judgment procedural disposition"
    ),
    "counter-cross": (
        "Identify all counterclaims and cross claims including asserting parties "
        "target parties defenses and requested relief"
    ),
    "third-party": (
        "Validate the third party claims layer separately from the main action "
        "including parties claims defenses and requested relief"
    ),
    "consolidated": (
        "Prepare one consolidated map in order Main case Counterclaims and cross "
        "claims Third party claims Identify parties claims defenses and relief"
    ),
}
# v4 reports need case-specific conflicts, not generic contract boilerplate.
# Filings are strongest; orders and sworn/testimonial materials follow.
ATTACK_SURFACE_PRIMARY_FILENAME_RE = re.compile(
    r"\b(?:order|decision|judgment|affidavit|deposition|transcript|testimony|"
    r"examination)\b",
    re.IGNORECASE,
)
ATTACK_SURFACE_EXHIBIT_FILENAME_RE = re.compile(r"\bexhibit\b", re.IGNORECASE)
# Exhibit filenames are often anonymized by NYSCEF export.  Detect the
# underlying evidentiary material from its verified page text as well.
ATTACK_SURFACE_PRIMARY_TEXT_RE = re.compile(
    r"\b(?:decision\s*(?:and|&)\s*order|\bordered\b|affidavit|affirmation|"
    r"deposition|examination\s+before\s+trial|transcript|testif(?:y|ied|ies)|"
    r"testimony|sworn)\b",
    re.IGNORECASE,
)
ATTACK_SURFACE_PARTY_EVIDENCE_TEXT_RE = re.compile(
    r"\b(?:incident\s+report|accident\s+report|notice\s+of\s+claim|"
    r"notice\s+of\s+occurrence|demand\s+letter|email|correspondence|"
    r"invoice|work\s+order|daily\s+report|inspection\s+report)\b",
    re.IGNORECASE,
)
ATTACK_SURFACE_MERITS_PLEADING_PAGE_LIMIT = 18
ATTACK_SURFACE_PRIMARY_PAGE_LIMIT = 18
ATTACK_SURFACE_EXHIBIT_PAGE_LIMIT = 9
# Attorney affirmations, counsel statements, service affidavits, and similar
# advocacy may describe evidence but are not first-hand proof.
ATTACK_SURFACE_NON_FIRST_HAND_RE = re.compile(
    r"\b(?:attorney|counsel)\b|\b(?:affidavit|affirmation)\s+of\s+service\b|"
    r"\b(?:counsel\s+(?:affirm|states?|argues?))\b|\b(?:affirmation\s+of\s+counsel)\b",
    re.IGNORECASE,
)
# A strategic answer may describe what a source says in Evidence, but the
# opposing parties' allegations and denials belong in Competing positions.
STRATEGIC_PARTY_POSITION_RE = re.compile(
    r"\b(?P<party>plaintiffs?|defendants?)\b(?:\s+\w+){0,10}?\s+"
    r"(?:allege|alleges|alleged|deny|denies|denied|contend|contends|contended|"
    r"assert|asserts|asserted|plead|pleads|pleaded|argue|argues|argued)\b",
    re.IGNORECASE,
)


class PreGenerationGateError(ValueError):
    """Raised when mandatory pleading coverage cannot fit before a model call."""

    def __init__(self, reason, detail=None, metrics=None):
        super().__init__(reason)
        self.detail = detail
        self.metrics = metrics if isinstance(metrics, dict) else {}


class EvidenceSelection(list):
    """Selected pages plus bounded retrieval-coverage metadata for the audit."""

    def __init__(self, pages, coverage):
        super().__init__(pages)
        self.coverage = coverage


PRE_GENERATION_GATE_REASONS = frozenset({
    "ambiguous_third_party_action_identity",
    "ambiguous_third_party_answer",
    "incomplete_third_party_action_slice",
    "missing_first_affirmative_defense_page",
    "missing_third_party_complaint",
    "missing_validated_layer",
    "noncontiguous_third_party_actions",
    "retrieval_replay_passed_current_code",
    "third_party_action_slices_exceed_context",
    "unresolved_third_party_action",
    "unmatched_third_party_answer",
})
PRE_GENERATION_GATE_DETAILS = frozenset({
    "duplicate_explicit_ordinal",
    "multiple_unlabeled_complaints",
})
PRE_GENERATION_GATE_METRICS = frozenset({
    "candidate_document_count",
    "candidate_section_count",
    "context_character_count",
    "mandatory_page_count",
    "missing_mandatory_page_count",
    "selected_page_count",
})
INCOMPLETE_OUTPUT_FIELDS = (
    "counterclaims_and_cross_claims",
    "finding",
    "limitations",
    "main_case",
    "missing_information",
    "summary",
    "third_party_claims",
)
INCOMPLETE_OUTPUT_SUBTYPES = (
    "connector_ended",
    "empty",
    "invalid_terminal",
    "near_schema_limit",
)
MODEL_VALIDATION_REASONS = frozenset({
    "incomplete_output",
    "incomplete_output_counterclaims_and_cross_claims",
    "incomplete_output_finding",
    "incomplete_output_limitations",
    "incomplete_output_main_case",
    "incomplete_output_missing_information",
    "incomplete_output_summary",
    "incomplete_output_third_party_claims",
    "incomplete_third_party_actions",
    "invalid_litigation_map_sections",
    "invalid_strategic_analysis_sections",
    "invalid_output",
    "party_positions_placed_in_evidence",
    "expert_agency_account_lacks_source_status_disclosure",
    "strategic_evidence_categories_not_analyzed",
    "strategic_direct_agency_records_not_analyzed",
    "uncited_output",
    "unverified_authority_citation",
    "unverified_citation",
    "unverified_missing_page_claim",
    "verified_pleading_called_missing",
}) | frozenset(
    f"incomplete_output_{field}_{subtype}"
    for field in INCOMPLETE_OUTPUT_FIELDS
    for subtype in INCOMPLETE_OUTPUT_SUBTYPES
)


def third_party_action_ordinal(filename, document_pages):
    """Return the expressly stated successive-action ordinal, if any."""
    identity = " ".join(
        [normalized_filename(filename)]
        + [text[:1200].casefold() for _, text in sorted(document_pages)[:3]]
    )
    match = THIRD_PARTY_ORDINAL_RE.search(identity)
    if match:
        return match.group(1).casefold()
    return None


def third_party_caption_tokens(filename, document_pages):
    """Extract stable caption-name tokens used only to pair answers to actions."""
    text = " ".join(
        [normalized_filename(filename)]
        + [page_text[:1600].casefold() for _, page_text in sorted(document_pages)[:3]]
    )
    return {
        token for token in re.findall(r"[a-z][a-z0-9]{2,}", text)
        if token not in THIRD_PARTY_CAPTION_STOPWORDS
    }


def third_party_action_slices(documents):
    """Group operative complaints and answers into successive actions."""
    filings = []
    for (source, filename), document_pages in documents.items():
        normalized = normalized_filename(filename)
        identity = " ".join(
            [normalized]
            + [text[:900].casefold() for _, text in sorted(document_pages)[:3]]
        )
        if not re.search(r"\bthird[ -]?(?:party|par)\b", identity):
            continue
        if re.search(r"\b(?:exhibit|affidavit|affirmation|notice|stipulation)\b", normalized):
            continue
        opening_text = " ".join(
            text[:1600].casefold() for _, text in sorted(document_pages)[:1]
        )
        filename_is_third_party = bool(re.search(r"\bthird[ -]?party\b", normalized))
        opening_is_third_party_answer = bool(re.search(
            r"\banswer\s+to\b.*\bthird[ -]?party\b|"
            r"\bthird[ -]?party\s+defendants?\b.*\banswer\b",
            opening_text,
        ))
        opening_is_third_party_complaint = bool(re.search(
            r"\b(?:first|second|third|fourth)?\s*third[ -]?party\b.*"
            r"\b(?:complaint|summons)\b",
            opening_text,
        ))
        is_answer = "answer" in normalized and (
            filename_is_third_party or opening_is_third_party_answer
        )
        is_complaint = not is_answer and bool(
            re.search(r"\b(?:complaint|summons)\b", normalized)
        ) and (filename_is_third_party or opening_is_third_party_complaint)
        if not (is_answer or is_complaint):
            continue
        filings.append({
            "source": source, "filename": filename,
            "pages": sorted(document_pages),
            "kind": "answer" if is_answer else "complaint",
            "ordinal": third_party_action_ordinal(filename, document_pages),
            "caption_tokens": third_party_caption_tokens(filename, document_pages),
            "action_summons": bool(re.search(r"\bthird party summons\b", normalized)),
        })

    complaints = [item for item in filings if item["kind"] == "complaint"]
    if not complaints:
        raise PreGenerationGateError("missing_third_party_complaint")
    def new_action(ordinal, complaint):
        return {
            "ordinal": ordinal,
            "complaint": complaint,
            "complaints": [complaint],
            "caption_tokens": set(complaint["caption_tokens"]),
            "answers": [],
        }

    def attach(action, complaint):
        action["complaints"].append(complaint)
        action["caption_tokens"].update(complaint["caption_tokens"])

    def filing_sequence(filing):
        match = re.search(r"(\d+)(?!.*\d)", normalized_filename(filing["filename"]))
        return int(match.group(1)) if match else None

    actions = []
    action_summonses = [item for item in complaints if item["action_summons"]]
    if len(action_summonses) > len(THIRD_PARTY_ORDINALS):
        raise PreGenerationGateError("ambiguous_third_party_action_identity")
    if len(action_summonses) > 1:
        sequences = [filing_sequence(item) for item in action_summonses]
        if None in sequences or len(set(sequences)) != len(sequences):
            raise PreGenerationGateError(
                "ambiguous_third_party_action_identity",
                "multiple_unlabeled_complaints",
            )
        for ordinal, complaint in zip(
            THIRD_PARTY_ORDINALS,
            [item for _, item in sorted(zip(sequences, action_summonses))],
        ):
            actions.append(new_action(ordinal, complaint))

    for complaint in sorted(
        (
            item for item in complaints
            if item["ordinal"] is not None
            and (len(action_summonses) <= 1 or not item["action_summons"])
        ),
        key=lambda item: (
            THIRD_PARTY_ORDINALS.index(item["ordinal"]),
            item["filename"].casefold(),
        ),
    ):
        ordinal = complaint["ordinal"]
        action = next((item for item in actions if item["ordinal"] == ordinal), None)
        if action is not None:
            # A successive action may have separate summons, complaint, or
            # amended-complaint filings carrying the same express ordinal.
            # Keep them in one action; the ordinal identifies the action, not
            # an individual source document.
            attach(action, complaint)
            continue
        actions.append(new_action(ordinal, complaint))

    # Cluster unlabeled summons/complaint files before assigning them. This
    # prevents a filing for a missing action from being consumed too early as
    # a duplicate of an explicitly labeled action.
    clusters = []
    for complaint in sorted(
        (
            item for item in complaints
            if item["ordinal"] is None
            and (len(action_summonses) <= 1 or not item["action_summons"])
        ),
        key=lambda item: item["filename"].casefold(),
    ):
        scored = sorted(
            ((len(complaint["caption_tokens"] & cluster["caption_tokens"]), cluster)
             for cluster in clusters),
            key=lambda pair: -pair[0],
        )
        if scored and scored[0][0] >= 2 and (
            len(scored) == 1 or scored[0][0] > scored[1][0]
        ):
            attach(scored[0][1], complaint)
        else:
            clusters.append(new_action(None, complaint))

    used = {action["ordinal"] for action in actions}
    highest = max(
        [THIRD_PARTY_ORDINALS.index(ordinal) for ordinal in used],
        default=0,
    )
    missing = [
        ordinal for ordinal in THIRD_PARTY_ORDINALS[:highest + 1]
        if ordinal not in used
    ]
    # If there are more unlabeled clusters than ordinal gaps, only clusters
    # with a unique, strong caption match may be absorbed as duplicate filings.
    while len(clusters) > len(missing):
        candidates = []
        for cluster in clusters:
            scored = sorted(
                ((len(cluster["caption_tokens"] & action["caption_tokens"]), action)
                 for action in actions),
                key=lambda pair: (-pair[0], THIRD_PARTY_ORDINALS.index(pair[1]["ordinal"])),
            )
            if scored and scored[0][0] >= 2 and (
                len(scored) == 1 or scored[0][0] > scored[1][0]
            ):
                candidates.append((scored[0][0], cluster, scored[0][1]))
        if not candidates:
            raise PreGenerationGateError(
                "ambiguous_third_party_action_identity",
                "multiple_unlabeled_complaints",
            )
        _, cluster, action = max(
            candidates,
            key=lambda item: (item[0], item[1]["complaint"]["filename"].casefold()),
        )
        for complaint in cluster["complaints"]:
            attach(action, complaint)
        clusters.remove(cluster)

    if len(clusters) != len(missing):
        raise PreGenerationGateError("noncontiguous_third_party_actions")
    if len(clusters) > 1:
        sequences = [filing_sequence(cluster["complaint"]) for cluster in clusters]
        if None in sequences or len(set(sequences)) != len(sequences):
            raise PreGenerationGateError(
                "ambiguous_third_party_action_identity",
                "multiple_unlabeled_complaints",
            )
        clusters = [cluster for _, cluster in sorted(zip(sequences, clusters))]
    for ordinal, cluster in zip(missing, clusters):
        cluster["ordinal"] = ordinal
        actions.append(cluster)
        used.add(ordinal)

    expected = set(THIRD_PARTY_ORDINALS[:len(actions)])
    if used != expected:
        raise PreGenerationGateError("noncontiguous_third_party_actions")

    for answer in [item for item in filings if item["kind"] == "answer"]:
        candidates = actions
        answer_sequence = filing_sequence(answer)
        sequence_action = None
        if answer_sequence is not None and len(action_summonses) > 1:
            preceding = []
            for action in actions:
                summons_sequences = [
                    filing_sequence(complaint)
                    for complaint in action["complaints"]
                    if complaint.get("action_summons")
                ]
                summons_sequences = [
                    sequence for sequence in summons_sequences
                    if sequence is not None and sequence < answer_sequence
                ]
                if summons_sequences:
                    preceding.append((max(summons_sequences), action))
            if preceding:
                sequence_action = max(preceding, key=lambda item: item[0])[1]
                candidates = [sequence_action]
        if answer["ordinal"]:
            ordinal_candidates = [
                action for action in candidates
                if action["ordinal"] == answer["ordinal"]
            ]
            all_ordinal_candidates = [
                action for action in actions
                if action["ordinal"] == answer["ordinal"]
            ]
            if sequence_action is not None and all_ordinal_candidates:
                ordinal_sequences = [
                    filing_sequence(complaint)
                    for complaint in all_ordinal_candidates[0]["complaints"]
                    if complaint.get("action_summons")
                ]
                ordinal_sequences = [value for value in ordinal_sequences if value is not None]
                # Synthetic or expressly numbered paired filings may share a
                # sequence. Otherwise the most recent preceding summons is
                # the operative chronological identity.
                if ordinal_sequences and answer_sequence == max(ordinal_sequences):
                    candidates = all_ordinal_candidates
            elif ordinal_candidates or answer_sequence is None:
                candidates = ordinal_candidates
        if not candidates:
            raise PreGenerationGateError("unmatched_third_party_answer")
        scored = sorted(
            ((len(answer["caption_tokens"] & a["caption_tokens"]), a) for a in candidates),
            key=lambda pair: (-pair[0], THIRD_PARTY_ORDINALS.index(pair[1]["ordinal"])),
        )
        if answer["ordinal"] is None and (not scored or scored[0][0] == 0):
            raise PreGenerationGateError("unmatched_third_party_answer")
        if answer["ordinal"] is None and len(scored) > 1 and scored[0][0] == scored[1][0]:
            raise PreGenerationGateError("ambiguous_third_party_answer")
        scored[0][1]["answers"].append(answer)
    return sorted(actions, key=lambda a: THIRD_PARTY_ORDINALS.index(a["ordinal"]))


def select_third_party_action_pages(documents):
    """Select and validate each successive third-party action independently."""
    actions = third_party_action_slices(documents)
    selected = []
    action_audit = []
    for action in actions:
        candidates = []
        for filing in [*action["complaints"], *action["answers"]]:
            pages = filing["pages"]
            for index, (page_number, text) in enumerate(pages):
                opening = index == 0
                claim = bool(PLEADING_CLAIM_TEXT_RE.search(text))
                defense = bool(AFFIRMATIVE_DEFENSES_RE.search(text))
                relief = bool(PLEADING_RELIEF_TEXT_RE.search(text))
                closing = index == len(pages) - 1
                if opening or claim or defense or relief or closing:
                    candidates.append({
                        "filing": filing, "page_number": page_number, "text": text,
                        "opening": opening, "claim": claim, "defense": defense,
                        "relief": relief, "closing": closing,
                    })
        chosen = []
        seen = set()
        def reserve(rows, limit=None):
            kept = 0
            for row in sorted(rows, key=lambda item: (
                item["filing"]["filename"].casefold(), item["page_number"]
            )):
                filing = row["filing"]
                page_id = (filing["source"], filing["filename"], row["page_number"])
                if page_id in seen or len(chosen) >= THIRD_PARTY_ACTION_PAGE_LIMIT:
                    continue
                chosen.append(row)
                seen.add(page_id)
                kept += 1
                if limit is not None and kept >= limit:
                    break
        # Required roles first, then a bounded claim set, then each answer's
        # defenses and both sides' prayers. Remaining operative pages fill the
        # slice without allowing a long complaint to crowd out its answer.
        reserve([row for row in candidates if row["opening"]])
        reserve([
            row for row in candidates
            if row["filing"]["kind"] == "complaint" and row["claim"]
        ], limit=4)
        for answer in action["answers"]:
            reserve([
                row for row in candidates
                if row["filing"] is answer and row["defense"]
            ], limit=1)
        reserve([row for row in candidates if row["relief"]])
        reserve([row for row in candidates if row["closing"]])
        reserve(candidates)
        if not any(row["filing"]["kind"] == "complaint" for row in chosen):
            raise PreGenerationGateError("incomplete_third_party_action_slice")
        action_pages = [{
            "source_sha256": row["filing"]["source"],
            "filename": row["filing"]["filename"],
            "page_number": row["page_number"],
            "text": row["text"][:MERITS_PLEADING_PAGE_CHARS],
        } for row in chosen]
        selected.extend(action_pages)
        action_audit.append({
            "ordinal": action["ordinal"],
            "complaint_filename": action["complaint"]["filename"],
            "complaint_filenames": sorted(
                complaint["filename"] for complaint in action["complaints"]
            ),
            "answer_filenames": sorted(a["filename"] for a in action["answers"]),
            "answer_present": bool(action["answers"]),
            "citations": [
                {key: page[key] for key in ("source_sha256", "filename", "page_number")}
                for page in action_pages
            ],
            "unresolved": [] if action["answers"] else ["No corresponding answer was identified in the verified corpus."],
        })
    if len(selected) > MAX_PAGES or sum(len(page["text"]) for page in selected) > MAX_CONTEXT_CHARS:
        raise PreGenerationGateError("third_party_action_slices_exceed_context")
    return selected, action_audit


def valid_case_id(value: str) -> bool:
    """Accept verified active-matter identifiers and the fixed Case-00 benchmark."""
    return value == CASE00_BENCHMARK_ID or bool(CASE_RE.fullmatch(value))


def normalized_filename(value: str) -> str:
    """Make generated archive filenames safe for procedural classification."""
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def deduplicate_exact_documents(documents):
    """Keep one citable copy of each byte-independent page-text sequence."""
    unique = {}
    seen_signatures = set()
    for identity, pages in sorted(
        documents.items(),
        key=lambda item: (normalized_filename(item[0][1]), item[0][0]),
    ):
        signature_payload = [
            (page, " ".join(text.casefold().split()))
            for page, text in sorted(pages)
        ]
        signature = hashlib.sha256(
            json.dumps(
                signature_payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        unique[identity] = pages
    return unique


def client():
    return boto3.client("s3", endpoint_url=os.environ["B2_ENDPOINT"].rstrip("/"), region_name=os.environ["B2_REGION"], aws_access_key_id=os.environ["B2_KEY_ID"], aws_secret_access_key=os.environ["B2_APPLICATION_KEY"])

def key(case_id: str, request_id: str, name: str) -> str:
    return f"cases/{case_id}/derived/internal-drafts/{request_id}/{name}"

def put(s3, case_id, request_id, name, value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    s3.put_object(Bucket=os.environ["B2_BUCKET"], Key=key(case_id, request_id, name), Body=raw, ContentType="application/json", Metadata={"sha256": hashlib.sha256(raw).hexdigest()})


def failure_diagnostics(exc, stage):
    """Return secret-safe, actionable failure metadata for status and logs."""
    if isinstance(exc, PreGenerationGateError):
        code = "pre_generation_gate"
    elif stage == "model_request" and isinstance(exc, urllib.error.HTTPError):
        code = "model_http_error"
    elif stage == "model_request" and isinstance(exc, (TimeoutError, socket.timeout)):
        code = "model_timeout"
    elif stage == "model_request" and isinstance(exc, urllib.error.URLError):
        code = "model_url_error"
    elif stage in {"model_request", "model_validation"} and isinstance(exc, ValueError):
        code = "model_output_validation"
    elif stage in {"request_load", "evidence_retrieval", "layer_composition", "authority_selection"}:
        code = "retrieval_error"
    elif stage in {"draft_write", "audit_write", "ready_write"}:
        code = "persistence_error"
    else:
        code = "internal_error"
    details = {
        "failure_code": code,
        "failure_stage": stage,
        "exception_type": exc.__class__.__name__.lower(),
    }
    if isinstance(exc, PreGenerationGateError):
        gate_reason = str(exc)
        details["gate_reason"] = (
            gate_reason
            if gate_reason in PRE_GENERATION_GATE_REASONS
            else "unspecified_pre_generation_gate"
        )
        if exc.detail in PRE_GENERATION_GATE_DETAILS:
            details["gate_detail"] = exc.detail
        gate_metrics = {
            key: value
            for key, value in exc.metrics.items()
            if key in PRE_GENERATION_GATE_METRICS
            and isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
        }
        if gate_metrics:
            details["gate_metrics"] = gate_metrics
    elif code == "model_output_validation":
        validation_reason = str(exc).strip().casefold().replace("-", " ").replace(" ", "_")
        if validation_reason.startswith("strategic_evidence_categories_not_analyzed:"):
            validation_reason = "strategic_evidence_categories_not_analyzed"
        if validation_reason.startswith("strategic_direct_agency_records_not_analyzed:"):
            validation_reason = "strategic_direct_agency_records_not_analyzed"
        details["validation_reason"] = (
            validation_reason
            if validation_reason in MODEL_VALIDATION_REASONS
            else "unspecified_model_validation"
        )
    if isinstance(exc, urllib.error.HTTPError):
        details["http_status"] = int(exc.code)
    elif isinstance(exc, urllib.error.URLError):
        details["reason_type"] = exc.reason.__class__.__name__.lower()
    return details


def log_failure(case_id, request_id, diagnostics):
    """Emit one JSON line without exception text, source text, or credentials."""
    print(json.dumps({
        "event": "internal_draft_failed",
        "case_id": case_id,
        "request_id": request_id,
        **diagnostics,
    }, sort_keys=True, separators=(",", ":")), file=sys.stderr, flush=True)

def words(value: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9]{3,}", value.casefold()) if x not in {"what","with","from","that","this","about","record","verified","case"}}

def read_request(s3, case_id, request_id):
    raw = s3.get_object(Bucket=os.environ["B2_BUCKET"], Key=f"cases/{case_id}/derived/draft-requests/{request_id}.json")["Body"].read()
    item = json.loads(raw.decode())
    if not isinstance(item, dict) or item.get("schema_version") != "legalai-draft-request.v1" or item.get("case_id") != case_id or item.get("external_communication") is not False:
        raise ValueError("invalid request")
    question = item.get("question")
    if not isinstance(question, str) or not question.strip() or len(question) > 1000: raise ValueError("invalid question")
    return question

def request_status(s3, case_id, request_id):
    """Return durable status; a newly created request has no status object."""
    try:
        raw = s3.get_object(Bucket=os.environ["B2_BUCKET"], Key=key(case_id, request_id, "status.json"))["Body"].read()
    except Exception:
        return "QUEUED"
    try:
        value = json.loads(raw.decode())
    except (UnicodeDecodeError, ValueError):
        return "FAILED"
    status = value.get("status") if isinstance(value, dict) else None
    return status if status in {"QUEUED", "RUNNING", "READY", "FAILED", "CANCELLED"} else "FAILED"


def diagnose_failed_retrieval(s3, case_id, request_id):
    """Replay evidence selection only and backfill a safe gate reason."""
    raw = s3.get_object(
        Bucket=os.environ["B2_BUCKET"],
        Key=key(case_id, request_id, "status.json"),
    )["Body"].read()
    status = json.loads(raw.decode("utf-8"))
    if (
        not isinstance(status, dict)
        or status.get("status") != "FAILED"
        or status.get("failure_code") != "pre_generation_gate"
        or status.get("failure_stage") != "evidence_retrieval"
    ):
        raise ValueError("request is not a failed pre-generation retrieval")
    question = read_request(s3, case_id, request_id)
    try:
        evidence(s3, case_id, question)
    except PreGenerationGateError as exc:
        diagnostics = failure_diagnostics(exc, "evidence_retrieval")
        gate_reason = diagnostics["gate_reason"]
        gate_detail = diagnostics.get("gate_detail")
        gate_metrics = diagnostics.get("gate_metrics")
    else:
        gate_reason = "retrieval_replay_passed_current_code"
        gate_detail = None
        gate_metrics = None
    put(s3, case_id, request_id, "status.json", {
        **status,
        "gate_reason": gate_reason,
        **({"gate_detail": gate_detail} if gate_detail else {}),
        **({"gate_metrics": gate_metrics} if gate_metrics else {}),
        "retrieval_diagnosed_at": datetime.now(timezone.utc).isoformat(),
    })
    return gate_reason, gate_detail, gate_metrics


def listed_objects(s3, **kwargs):
    """Yield every B2 list result, including pages after the provider's object limit."""
    continuation_token = None
    while True:
        request = dict(kwargs)
        if continuation_token:
            request["ContinuationToken"] = continuation_token
        result = s3.list_objects_v2(**request)
        yield from result.get("Contents", [])
        if not result.get("IsTruncated"):
            return
        continuation_token = result.get("NextContinuationToken")
        if not continuation_token:
            raise RuntimeError("truncated B2 listing without continuation token")


def read_json_object(s3, object_key):
    raw = s3.get_object(Bucket=os.environ["B2_BUCKET"], Key=object_key)["Body"].read()
    value = json.loads(raw.decode())
    if not isinstance(value, dict):
        raise ValueError("invalid stored json object")
    return value


def one_edit_apart(left: str, right: str) -> bool:
    """Return whether two same-case words differ by one insertion/deletion/substitution."""
    left, right = left.casefold(), right.casefold()
    if abs(len(left) - len(right)) > 1 or left == right:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) == 1
    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    index = mismatches = 0
    for char in longer:
        if index < len(shorter) and char == shorter[index]:
            index += 1
        else:
            mismatches += 1
            if mismatches > 1:
                return False
    return True


def clean_composed_finding(finding):
    """Apply source-bound presentation cleanup without changing legal substance."""
    cleaned = json.loads(json.dumps(finding))
    statement = cleaned.get("statement", "")
    filename_tokens = {
        token for cite in cleaned.get("citations", [])
        for token in re.findall(r"[A-Za-z]{4,}", str(cite.get("filename", "")))
    }
    # A caption-derived person name has a constrained shape. Correct a given
    # name only when exactly one cited-filename token is one edit away.
    def canonical_given_name(match):
        word = match.group(1)
        choices = sorted({token for token in filename_tokens if one_edit_apart(word, token)})
        return (choices[0] if len(choices) == 1 else word) + match.group(2)
    statement = re.sub(
        r"\b([A-Z][a-z]{3,})(\s+[A-Z]\.\s+[A-Z][A-Za-z]+)",
        canonical_given_name,
        statement,
    )
    # Drop only a terminal, visibly incomplete boilerplate fragment. Never
    # synthesize the missing words or alter an enumerated relief category.
    statement = re.sub(r",\s*other\s+just\.\s*$", ".", statement, flags=re.IGNORECASE)
    cleaned["statement"] = statement
    return cleaned


def compose_validated_layers(s3, case_id, question):
    """Compose separately READY and validated litigation-map layers without a model call."""
    prefix = f"cases/{case_id}/derived/internal-drafts/"
    draft_keys = sorted(
        (
            str(item.get("Key", ""))
            for item in listed_objects(
                s3, Bucket=os.environ["B2_BUCKET"], Prefix=prefix, MaxKeys=1000
            )
            if str(item.get("Key", "")).endswith("/draft.json")
        ),
        reverse=True,
    )
    candidates = {section: [] for section in LITIGATION_MAP_SECTIONS}
    for draft_key in draft_keys:
        request_id = draft_key.removeprefix(prefix).split("/", 1)[0]
        if not re.fullmatch(r"draft-[0-9]+-[0-9a-f]{12}", request_id):
            continue
        if request_status(s3, case_id, request_id) != "READY":
            continue
        draft = read_json_object(s3, draft_key)
        findings = draft.get("findings")
        if (
            draft.get("schema_version") != "legalai-internal-draft.v1"
            or draft.get("case_id") != case_id
            or draft.get("external_communication") is not False
            or not isinstance(findings, list)
        ):
            continue
        sections = [item.get("section") for item in findings if isinstance(item, dict)]
        draft_question = str(draft.get("question", ""))
        if sections == ["Main case"] and not CONSOLIDATED_LITIGATION_MAP_RE.search(draft_question):
            candidates["Main case"].append((request_id, draft))
        if sections == ["Counterclaims and cross-claims"] and not CONSOLIDATED_LITIGATION_MAP_RE.search(draft_question):
            candidates["Counterclaims and cross-claims"].append((request_id, draft))
        if sections == ["Third-party claims"] and THIRD_PARTY_ONLY_QUESTION_RE.search(draft_question):
            try:
                audit = read_json_object(s3, key(case_id, request_id, "input_audit.json"))
            except Exception:
                continue
            actions = audit.get("coverage", {}).get("third_party_actions", [])
            if [action.get("ordinal") for action in actions if isinstance(action, dict)] == list(THIRD_PARTY_ORDINALS):
                candidates["Third-party claims"].append((request_id, draft, audit))
    if candidates["Third-party claims"]:
        third_party_present = True
    else:
        try:
            evidence(s3, case_id, RETRIEVAL_VALIDATION_PROFILES["third-party"])
        except PreGenerationGateError as exc:
            if str(exc) != "missing_third_party_complaint":
                raise
            third_party_present = False
        else:
            third_party_present = True
    required_sections = ["Main case", "Counterclaims and cross-claims"]
    if third_party_present:
        required_sections.append("Third-party claims")
    if any(not candidates[section] for section in required_sections):
        raise PreGenerationGateError("missing_validated_layer")

    main_request, main_draft = candidates["Main case"][0]
    counter_request, counter_draft = candidates["Counterclaims and cross-claims"][0]
    source_drafts = {
        "Main case": (main_request, main_draft),
        "Counterclaims and cross-claims": (counter_request, counter_draft),
    }
    third_audit = None
    if third_party_present:
        third_request, third_draft, third_audit = candidates["Third-party claims"][0]
        source_drafts["Third-party claims"] = (third_request, third_draft)
    findings = []
    citations = []
    for section in required_sections:
        _source_request, source_draft = source_drafts[section]
        finding = clean_composed_finding(next(
            item for item in source_draft["findings"] if item.get("section") == section
        ))
        findings.append(finding)
        citations.extend(finding.get("citations", []))
    unique_citations = {
        (cite.get("source_sha256"), cite.get("filename"), cite.get("page_number")): cite
        for cite in citations
        if isinstance(cite, dict)
    }
    pages = [{**cite, "text": ""} for cite in unique_citations.values()]
    coverage = {"composition_sources": {
        section: source_drafts[section][0] for section in required_sections
    }}
    if third_audit:
        coverage["third_party_actions"] = third_audit["coverage"]["third_party_actions"]
    result = {
        "summary": (
            "The verified pleadings map main-action claims, counterclaims and cross-claims"
            + (", and the validated third-party actions." if third_party_present else ".")
        ),
        "findings": findings,
        "missing_information": [],
        "limitations": [
            "This consolidated draft deterministically reuses separately validated layer findings and citations."
        ],
    }
    return validate(result, pages, question=question, coverage=coverage), pages, coverage

def pending_requests(s3, case_id=None):
    """Yield queued verified-case requests in stable order without retrying failures."""
    if case_id is None:
        cases = [item.get("Prefix", "").removeprefix("cases/").rstrip("/") for item in s3.list_objects_v2(Bucket=os.environ["B2_BUCKET"], Prefix="cases/", Delimiter="/").get("CommonPrefixes", [])]
    else:
        cases = [case_id]
    for current_case_id in sorted(cases):
        if not valid_case_id(current_case_id):
            continue
        objects = listed_objects(s3, Bucket=os.environ["B2_BUCKET"], Prefix=f"cases/{current_case_id}/derived/draft-requests/", MaxKeys=1000)
        request_ids = sorted(str(item.get("Key", "")).rsplit("/", 1)[-1].removesuffix(".json") for item in objects if str(item.get("Key", "")).endswith(".json"))
        for request_id in request_ids:
            if re.fullmatch(r"draft-[0-9]+-[0-9a-f]{12}", request_id) and request_status(s3, current_case_id, request_id) == "QUEUED":
                yield current_case_id, request_id

def verified_sources(s3, case_id):
    """Read the canonical immutable-original/additive source-set pointer."""
    identity_key = f"cases/{case_id}/intake/case_identity.json"
    identity = json.loads(s3.get_object(Bucket=os.environ["B2_BUCKET"], Key=identity_key)["Body"].read().decode())
    original = identity.get("source_sha256") if isinstance(identity, dict) else None
    if not isinstance(original, str) or not SHA256_RE.fullmatch(original):
        raise ValueError("invalid verified source identity")
    try:
        source_set = json.loads(s3.get_object(Bucket=os.environ["B2_BUCKET"], Key=f"cases/{case_id}/intake/source_set.json")["Body"].read().decode())
    except Exception:
        return [original]
    sources = source_set.get("sources") if isinstance(source_set, dict) and source_set.get("case_id") == case_id else None
    digests = [item.get("source_sha256") for item in sources] if isinstance(sources, list) else []
    if not digests or any(not isinstance(digest, str) or not SHA256_RE.fullmatch(digest) for digest in digests) or len(set(digests)) != len(digests) or original not in digests:
        raise ValueError("invalid verified source set")
    return digests


@dataclass(frozen=True)
class ReviewedAuthority:
    """A case-specific authority admitted only after independent review in B2."""
    authority_id: str
    citation: str
    official_primary_source: str
    exact_holding: str
    filing_proposition: str
    filing_record_citation: str
    sha256: str

    def as_canonical_dict(self):
        return {
            "authority_id": self.authority_id, "citation": self.citation,
            "official_primary_source": self.official_primary_source,
            "exact_holding": self.exact_holding,
            "filing_proposition": self.filing_proposition,
            "filing_record_citation": self.filing_record_citation,
        }


def _reviewed_authority_hash(value):
    payload = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_reviewed_authorities(s3, case_id):
    """Load only complete, hash-verified authorities scoped to this case source.

    Missing review objects yield no authority. A present but changed/incomplete
    object is a hard failure: party citations must never become governing law.
    """
    authorities = []
    for source_sha256 in verified_sources(s3, case_id):
        object_key = f"cases/{case_id}/{REVIEWED_AUTHORITY_KEY}/{source_sha256}.json"
        try:
            raw = s3.get_object(Bucket=os.environ["B2_BUCKET"], Key=object_key)["Body"].read()
        except ClientError as exc:
            # A missing review record simply means no independently reviewed
            # authority exists for that source. Do not fall back to registry data.
            if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404", "NotFound"}:
                continue
            raise
        except KeyError:  # synthetic/local B2 test transport: absent key
            continue
        try:
            value = json.loads(raw.decode())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid reviewed-authority record") from exc
        required = {"schema_version", "case_id", "source_sha256", "records", "sha256"}
        if (not isinstance(value, dict) or set(value) != required
                or value.get("schema_version") != "legalai-reviewed-authorities.v1"
                or value.get("case_id") != case_id or value.get("source_sha256") != source_sha256
                or not isinstance(value.get("sha256"), str) or not SHA256_RE.fullmatch(value["sha256"])
                or value["sha256"] != _reviewed_authority_hash(value)):
            raise ValueError("reviewed-authority hash mismatch")
        records = value.get("records")
        fields = {"authority_id", "citation", "official_primary_source", "exact_holding", "filing_proposition", "filing_record_citation"}
        if not isinstance(records, list) or not records:
            raise ValueError("reviewed-authority record is incomplete")
        for record in records:
            if (not isinstance(record, dict) or set(record) != fields
                    or not all(isinstance(record.get(key), str) and record[key].strip() for key in fields)
                    or not record["official_primary_source"].startswith((
                        "https://www.nycourts.gov/",
                        "https://www.nysenate.gov/",
                        "https://oysterbaytown.com/",
                        "https://ecode360.com/",
                    ))
                    or not re.search(r"\bp\.\s*[1-9][0-9]*\b", record["filing_record_citation"], re.I)):
                raise ValueError("reviewed-authority record is incomplete")
            authorities.append(ReviewedAuthority(**record, sha256=value["sha256"]))
    ids = [authority.authority_id for authority in authorities]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate reviewed authority")
    return tuple(authorities)


def attack_surface_first_hand_page(filename: str, text: str) -> bool:
    """Return whether a v4 factual source is first-hand rather than advocacy."""
    combined = f"{filename} {text[:1200]}"
    if ATTACK_SURFACE_NON_FIRST_HAND_RE.search(combined):
        return False
    normalized = normalized_filename(filename)
    if "affidavit or affirm" in normalized:
        return bool(re.search(r"\b(?:i,|i am|personally|deponent|sworn)\b", text, re.IGNORECASE))
    return bool(
        ATTACK_SURFACE_PRIMARY_FILENAME_RE.search(normalized)
        or ATTACK_SURFACE_PRIMARY_TEXT_RE.search(text)
        or (
            ATTACK_SURFACE_EXHIBIT_FILENAME_RE.search(normalized)
            and ATTACK_SURFACE_PARTY_EVIDENCE_TEXT_RE.search(text)
        )
    )


def verified_page_records(s3, case_id, source_sha256):
    """Read the immutable index plus an optional, additive OCR replacement.

    The OCR object is a derived sidecar, never a replacement for the verified
    filing or its base index.  When present, it may replace only the matching
    page text for that same verified source, preserving all other base pages.
    """
    prefix = f"cases/{case_id}/intake/source/{source_sha256}/"
    base_key = prefix + "page_records.jsonl"
    raw = s3.get_object(Bucket=os.environ["B2_BUCKET"], Key=base_key)["Body"].read()
    rows = {}

    def absorb(payload):
        for line in payload.decode().splitlines():
            item = json.loads(line)
            text = " ".join(str(item.get("text", "")).split())
            filename = item.get("filename")
            page = item.get("page_number")
            if text and isinstance(filename, str) and isinstance(page, int) and page >= 1:
                rows[(filename, page)] = text

    absorb(raw)
    try:
        absorb(s3.get_object(
            Bucket=os.environ["B2_BUCKET"], Key=prefix + OCR_PAGE_RECORDS_SUFFIX
        )["Body"].read())
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {"NoSuchKey", "404", "NotFound"}:
            raise
    except KeyError:  # synthetic/local B2 transport: absent OCR sidecar
        pass
    return [
        {"filename": filename, "page_number": page, "text": text}
        for (filename, page), text in sorted(rows.items(), key=lambda item: (item[0][0].casefold(), item[0][1]))
    ]


def evidence(s3, case_id, question):
    """Select bounded evidence with filing- and section-level pleading coverage."""
    rows=[]; terms=words(question); party_role_candidates=set()
    broad_record_question = len(BROAD_RECORD_TERMS.intersection(terms)) >= 2
    # A targeted pleading question can have only one of the broad map terms
    # (for example, "affirmative defenses"), but still requires the same
    # filing-led coverage before contract exhibits are considered.
    pleading_focused_question = bool(PLEADING_FOCUSED_QUESTION_RE.search(question))
    attack_surface_question = TOP_ATTACK_SURFACES_MARKER in question.casefold()
    strategic_analysis_question = (
        bool(STRATEGIC_ANALYSIS_QUESTION_RE.search(question))
        and not litigation_map_question(question)
        and not attack_surface_question
    )
    procedural_posture_question = bool(
        PROCEDURAL_POSTURE_QUESTION_RE.search(question)
    )
    consolidated_question = bool(CONSOLIDATED_LITIGATION_MAP_RE.search(question))
    third_party_only_question = bool(THIRD_PARTY_ONLY_QUESTION_RE.search(question))
    cross_claim_only_question = (
        bool(CROSS_CLAIM_ONLY_QUESTION_RE.search(question))
        and not third_party_only_question
        and not consolidated_question
    )
    main_action_only_question = (
        bool(MAIN_ACTION_ONLY_QUESTION_RE.search(question))
        and not cross_claim_only_question
        and not third_party_only_question
        and not consolidated_question
    )
    # The v4 report is intentionally filing-led even though its prompt uses
    # analytical terms rather than a pleading's exact title.
    filing_led_question = (
        broad_record_question
        or pleading_focused_question
        or attack_surface_question
        or strategic_analysis_question
    )
    targeted_third_party_complaint = bool(
        THIRD_PARTY_COMPLAINT_QUESTION_RE.search(question)
    ) and not third_party_only_question
    documents={}
    for source in verified_sources(s3, case_id):
        for item in verified_page_records(s3, case_id, source):
            text=item["text"]; filename=item["filename"]; page=item["page_number"]
            documents.setdefault((source, filename), []).append((page, text))
    if third_party_only_question:
        selected, action_audit = select_third_party_action_pages(documents)
        coverage = {
            "party_role_evidence": {
                "candidate_count": 0, "retrieved_count": 0,
                "outside_initial_slice": False,
                "outside_initial_slice_citations": [],
            },
            "pleading_operatives": {
                "claim_page_count": sum(
                    bool(PLEADING_CLAIM_TEXT_RE.search(page["text"])) for page in selected
                ),
                "relief_page_count": sum(
                    bool(PLEADING_RELIEF_TEXT_RE.search(page["text"])) for page in selected
                ),
                "claim_citations": [], "relief_citations": [],
            },
            "verified_pleading_inventory": verified_pleading_inventory(documents),
            "third_party_actions": action_audit,
        }
        return EvidenceSelection(selected, coverage)
    cross_claim_party_match = (
        CROSS_CLAIM_ASSERTING_PARTY_RE.search(question)
        if cross_claim_only_question
        else None
    )
    cross_claim_party = (
        " ".join(cross_claim_party_match.group(1).casefold().split())
        if cross_claim_party_match
        else ""
    )
    # A third-party complaint caption often names all parties while its claims
    # and prayer occur several pages later. Keep the bounded target pleading
    # together so page-ranking cannot retain only the caption and falsely call
    # the operative allegations missing.
    targeted_pages = []
    consolidated_action_audit = []
    if consolidated_question:
        targeted_pages, consolidated_action_audit = select_third_party_action_pages(documents)
        if any(action.get("unresolved") for action in consolidated_action_audit):
            raise PreGenerationGateError("unresolved_third_party_action")
    if targeted_third_party_complaint:
        candidates = []
        for (source, filename), document_pages in documents.items():
            normalized = normalized_filename(filename)
            is_complaint = (
                "third party" in normalized
                and ("complaint" in normalized or "summons" in normalized)
                and "answer" not in normalized
            )
            if not is_complaint:
                continue
            joined = " ".join(text.casefold() for _, text in document_pages)
            matched_terms = sum(1 for term in terms if term in joined)
            if matched_terms:
                candidates.append((matched_terms, source, filename, document_pages))
        if candidates:
            _, source, filename, document_pages = max(
                candidates,
                key=lambda item: (item[0], -len(item[3]), item[2].casefold()),
            )
            targeted_pages = [
                {
                    "source_sha256": source,
                    "filename": filename,
                    "page_number": page,
                    "text": text[:MERITS_PLEADING_PAGE_CHARS],
                }
                for page, text in sorted(document_pages)[
                    :TARGETED_THIRD_PARTY_COMPLAINT_PAGE_LIMIT
                ]
            ]
    selection_documents = (
        deduplicate_exact_documents(documents)
        if main_action_only_question
        else documents
    )
    for (source, filename), document_pages in selection_documents.items():
        normalized_document_filename = normalized_filename(filename)
        document_identity = " ".join(
            [normalized_document_filename]
            + [text[:900].casefold() for _, text in sorted(document_pages)]
        )
        strategic_expert_document = bool(
            STRATEGIC_EXPERT_TEXT_RE.search(document_identity)
            or re.search(
                r"\b(?:expert|engineer|surveyor|technical[ _-]?report)\b",
                normalized_document_filename,
                re.IGNORECASE,
            )
        )
        counter_cross_filing = bool(COUNTER_CROSS_FILING_RE.search(document_identity))
        if third_party_only_question and re.search(
            r"\b(?:exhibit|affidavit|affirmation|notice|stipulation)\b",
            normalized_document_filename,
            re.IGNORECASE,
        ):
            # The corpus includes many exhibit copies of the same operative
            # third-party pleadings.  Requiring each duplicate copy exhausts
            # the bounded page budget before generation.  Keep the filed
            # summons/complaints and answers; exclude derivative copies.
            continue
        if main_action_only_question and re.search(
            r"\b(?:exhibit|affidavit|affirmation|notice|stipulation)\b",
            normalized_document_filename,
            re.IGNORECASE,
        ):
            # Main-action corpora can likewise contain dozens of motion
            # exhibits whose filenames embed copies of the complaint or
            # answers. Treating each copy as an operative pleading creates a
            # false mandatory-defense overflow before generation.
            continue
        if third_party_only_question and not re.search(
            r"\b(?:third[ -]?(?:party|par)|fourth[ -]?(?:party|par))\b",
            document_identity,
            re.IGNORECASE,
        ):
            continue
        if cross_claim_party:
            document_text = " ".join(text.casefold() for _, text in document_pages)
            if cross_claim_party not in document_text:
                continue
        if cross_claim_only_question and not counter_cross_filing:
            continue
        section_start = 1
        prior_page = None
        affirmative_defense_run_remaining = 0
        prayer_run_remaining = 0
        for page, text in sorted(document_pages):
            pleading_filename = normalized_filename(filename)
            merits_pleading = bool(PLEADING_FILENAME_RE.search(pleading_filename))
            if cross_claim_only_question and not merits_pleading:
                # A focused counterclaim/cross-claim request expressly limits
                # citations to operative pleadings and replies. Do not allow
                # exhibits, trial bundles, or other term-matching record pages
                # to re-enter through the general ranking pass.
                continue
            if cross_claim_only_question and merits_pleading:
                # Keep this layer independent from the main complaint/answer
                # and successive third-party pleadings. The filename or the
                # complete document must identify this layer. Once it does,
                # retain its caption/opening and operative pages even when an
                # individual page omits the words counterclaim/cross-claim.
                # Causes of action and prayers commonly do exactly that.
                if not counter_cross_filing:
                    continue
            if main_action_only_question and merits_pleading:
                # A main-action request must not make every successive
                # third-party/cross-claim pleading mandatory. Those layers are
                # separate retrieval questions and otherwise exhaust the
                # bounded 45-page budget before generation.
                filing_identity = f"{pleading_filename} {text[:700]}"
                if re.search(
                    r"\b(?:third[ -]?(?:party|par)|fourth[ -]?(?:party|par)|"
                    r"cross[ -]?(?:claim|c)|counter[ -]?(?:claim|c)|"
                    r"bills? of particulars)\b",
                    filing_identity,
                    re.IGNORECASE,
                ):
                    # Exclude the page altogether, not merely from mandatory
                    # reservations. Otherwise it can re-enter through the
                    # general ranking pass and consume almost the entire
                    # context window despite being outside the requested layer.
                    continue
            # Some archive PDFs concatenate an answer, demands, and a later
            # answer. A later answer heading starts a separate filing section.
            if (
                merits_pleading and page > 1
                and PLEADING_SECTION_START_RE.search(text[:700])
            ):
                section_start = page
            affirmative_defenses = bool(AFFIRMATIVE_DEFENSES_RE.search(text))
            affirmative_defense_continuation = (
                affirmative_defense_run_remaining > 0
                and prior_page is not None
                and page == prior_page + 1
            )
            if affirmative_defenses:
                # Retain the heading plus its next two pages. Defense lists
                # commonly span three page-records in a single pleading.
                affirmative_defense_run_remaining = 2
            elif affirmative_defense_continuation:
                affirmative_defense_run_remaining -= 1
            else:
                affirmative_defense_run_remaining = 0
            lowered=text.casefold(); score=sum(lowered.count(term) for term in terms)
            score += 2 if any(term in filename.casefold() for term in terms) else 0
            candidate_text_limit = (
                MERITS_PLEADING_PAGE_CHARS
                if filing_led_question and merits_pleading
                else MAX_PAGE_CHARS
            )
            candidate={"source_sha256":source,"filename":filename,"page_number":page,"text":text[:candidate_text_limit]}
            coverage_score = 0
            operational_pleading = bool(PLEADING_OPERATIONAL_TEXT_RE.search(text))
            claim_pleading = bool(PLEADING_CLAIM_TEXT_RE.search(text))
            relief_pleading = bool(PLEADING_RELIEF_TEXT_RE.search(text))
            strategic_expert = bool(
                STRATEGIC_EXPERT_TEXT_RE.search(text)
                or strategic_expert_document
            )
            strategic_measurement = bool(
                STRATEGIC_MEASUREMENT_TEXT_RE.search(text)
            )
            strategic_law = bool(STRATEGIC_LAW_TEXT_RE.search(text))
            strategic_position = bool(STRATEGIC_POSITION_TEXT_RE.search(text))
            # Require direct issuer/permit signals, so an expert or brief
            # discussing DEC is not elevated to an agency record.
            strategic_regulatory = bool(
                DIRECT_REGULATORY_RECORD_RE.search(text)
                and not strategic_expert
                and not STRATEGIC_ADVOCACY_FILENAME_RE.search(pleading_filename)
            )
            strategic_procedural = bool(
                STRATEGIC_PROCEDURAL_RECORD_RE.search(text)
                or STRATEGIC_PROCEDURAL_RECORD_RE.search(pleading_filename)
            )
            prayer_continuation = (
                prayer_run_remaining > 0
                and prior_page is not None
                and page == prior_page + 1
            )
            if PLEADING_PRAYER_START_RE.search(text):
                # Multi-part prayers often continue for several pages without
                # repeating WHEREFORE. Preserve the bounded continuation so
                # later relief categories are not silently dropped.
                prayer_run_remaining = 4
            elif prayer_continuation:
                prayer_run_remaining -= 1
            else:
                prayer_run_remaining = 0
            if filing_led_question and merits_pleading:
                # Retain a filing-led record map: each section's caption plus
                # claim, defense, or prayer pages.
                if page == section_start:
                    coverage_score += 8
                if affirmative_defenses:
                    coverage_score += 12
                if affirmative_defense_continuation:
                    coverage_score += 10
                if operational_pleading:
                    coverage_score += 6
                # A substantive cause-of-action heading or prayer page is
                # independently operative even when it shares no literal
                # terms with the user's broad litigation-map question.
                if claim_pleading:
                    coverage_score += 12
                if relief_pleading:
                    coverage_score += 12
                if prayer_continuation:
                    coverage_score += 10
                # Party role and ownership allegations may sit between the
                # caption and formal causes of action. Retain them for a
                # party/claims/defenses request rather than inferring a role
                # from an incomplete pleading slice.
                if PLEADING_PARTY_ROLE_TEXT_RE.search(text):
                    coverage_score += 7
            if attack_surface_question:
                # First surface party-identified pleadings; then court orders
                # and sworn/testimonial materials; only then substantive
                # exhibits. Generic contract excerpts get no v4 preference.
                if merits_pleading:
                    coverage_score += 40
                elif (
                    attack_surface_first_hand_page(filename, text)
                ):
                    coverage_score += 32
                elif (
                    ATTACK_SURFACE_EXHIBIT_FILENAME_RE.search(pleading_filename)
                    and ATTACK_SURFACE_PARTY_EVIDENCE_TEXT_RE.search(text)
                ):
                    coverage_score += 20
                if operational_pleading:
                    coverage_score += 10
                if ATTACK_SURFACE_PRIMARY_FILENAME_RE.search(pleading_filename) and V4_PROCEDURAL_ORDER_TEXT_RE.search(text):
                    coverage_score += 45
            elif strategic_analysis_question:
                # Analytical questions need a balanced case-theory packet,
                # even when the attorney's natural-language question contains
                # only generic words such as "weakest issues." Reserve expert
                # opinions, concrete physical facts, law cited in the record,
                # and both sides' positions by source type and text signals.
                if STRATEGIC_SOURCE_FILENAME_RE.search(pleading_filename):
                    coverage_score += 18
                if strategic_expert:
                    coverage_score += 45
                if strategic_measurement:
                    coverage_score += 36
                if strategic_law:
                    coverage_score += 34
                if strategic_position:
                    coverage_score += 30
                if strategic_regulatory:
                    coverage_score += 42
                if strategic_procedural:
                    coverage_score += 44
            elif (
                procedural_posture_question
                and ATTACK_SURFACE_PRIMARY_FILENAME_RE.search(pleading_filename)
                and V4_PROCEDURAL_ORDER_TEXT_RE.search(text)
            ):
                # Questions about death, substitution, jurisdiction, or a
                # dispositive motion require the controlling procedural record
                # alongside the pleadings. This is filing-type and text based,
                # never case-name based.
                coverage_score += 45
            # A party/claims question can require a non-pleading record page
            # that directly addresses ownership, residence, or control. Keep
            # this narrow so advocacy alone is not elevated into a fact.
            party_role_evidence = (
                filing_led_question
                and PLEADING_PARTY_ROLE_TEXT_RE.search(text)
                and PARTY_ROLE_FACT_TEXT_RE.search(text)
                and any(term in lowered for term in terms)
            )
            if party_role_evidence:
                party_role_candidates.add((source, filename, page))
                coverage_score += 14
                if re.search(r"\b(?:joint|co[- ]?)owner(?:ship)?\b", text, re.IGNORECASE):
                    coverage_score += 30
            if score or coverage_score:
                rows.append((
                    score + coverage_score, filename, page, source, candidate,
                    merits_pleading, operational_pleading, section_start,
                    affirmative_defenses, affirmative_defense_continuation,
                    claim_pleading, relief_pleading,
                    prayer_continuation,
                    strategic_expert, strategic_measurement,
                    strategic_law, strategic_position, strategic_regulatory,
                    strategic_procedural,
                ))
            prior_page = page
    mandatory_ids=set()
    selected=[]; selected_ids=set(); total=0
    ranked = sorted(rows,key=lambda x:(-x[0],x[1].casefold(),x[2]))
    ordered = ranked
    if filing_led_question:
        merits=[]; merit_ids=set(); per_section={}
        merits_limit = (
            ATTACK_SURFACE_MERITS_PLEADING_PAGE_LIMIT
            if attack_surface_question
            else STRATEGIC_MERITS_PAGE_LIMIT
            if strategic_analysis_question
            else MERITS_PLEADING_PAGE_LIMIT
        )
        def reserve(row):
            item_id=(row[3],row[1],row[2])
            if item_id in merit_ids or len(merits) >= merits_limit:
                return False
            merits.append(row); merit_ids.add(item_id)
            section=(row[3],row[1],row[7])
            per_section[section]=per_section.get(section,0)+1
            return True
        def section_page_limit(row):
            normalized = normalized_filename(row[1])
            if cross_claim_only_question:
                # A counterclaim pleading commonly needs a caption, several
                # separately headed causes, defenses, and a prayer. The normal
                # three-page answer cap silently drops those operative pages.
                return MERITS_COMPLAINT_PAGES_PER_FILING
            if ("complaint" in normalized or "summons" in normalized) and "answer" not in normalized:
                return MERITS_COMPLAINT_PAGES_PER_FILING
            return MERITS_PLEADING_PAGES_PER_FILING
        # Reserve the first affirmative-defense heading in each pleading
        # section before later heading pages. A long defense list can contain
        # many headings; otherwise its later pages can fill the global budget
        # before another section's first defense page is reached.
        first_defense_page = {}
        for row in rows:
            section = (row[3], row[1], row[7])
            if row[5] and row[8]:
                first_defense_page[section] = min(
                    row[2], first_defense_page.get(section, row[2])
                )
        mandatory_ids = (
            {
                (section[0], section[1], page)
                for section, page in first_defense_page.items()
            }
            if not attack_surface_question and not strategic_analysis_question
            else set()
        )
        # First reserve every filing/section opening, then the first required
        # defense page. Claims and prayer pages follow. This ordering matches
        # the gate: optional operative pages must never consume a section's
        # allowance before a mandatory defense page.
        for row in ranked:
            if row[5] and row[2] == row[7] and reserve(row):
                if not attack_surface_question and not strategic_analysis_question:
                    mandatory_ids.add((row[3], row[1], row[2]))
        for row in ranked:
            section=(row[3],row[1],row[7])
            if (
                row[5] and row[8]
                and row[2] == first_defense_page.get(section)
                and per_section.get(section,0) < section_page_limit(row)
            ):
                if reserve(row):
                    if not attack_surface_question and not strategic_analysis_question:
                        mandatory_ids.add((row[3], row[1], row[2]))
        for signal_index in (10, 11):
            for row in sorted(ranked, key=lambda item: (item[1].casefold(), item[2], -item[0])):
                section=(row[3],row[1],row[7])
                if row[5] and row[signal_index] and per_section.get(section,0) < section_page_limit(row):
                    if reserve(row):
                        if not attack_surface_question and not strategic_analysis_question:
                            mandatory_ids.add((row[3], row[1], row[2]))
        for row in sorted(ranked, key=lambda item: (item[1].casefold(), item[2], -item[0])):
            section=(row[3],row[1],row[7])
            if row[5] and row[12] and per_section.get(section,0) < section_page_limit(row):
                if reserve(row):
                    if not attack_surface_question and not strategic_analysis_question:
                        mandatory_ids.add((row[3], row[1], row[2]))
        # Then reserve additional affirmative-defense headings and immediate
        # continuation pages, subject to the unchanged global budget.
        for row in ranked:
            section=(row[3],row[1],row[7])
            if row[5] and row[8] and per_section.get(section,0) < section_page_limit(row):
                reserve(row)
        for row in ranked:
            section=(row[3],row[1],row[7])
            if row[5] and row[9] and per_section.get(section,0) < section_page_limit(row):
                reserve(row)
        # Then retain remaining operative and party-role pages.
        for row in ranked:
            section=(row[3],row[1],row[7])
            if row[5] and (row[6] or PLEADING_PARTY_ROLE_TEXT_RE.search(row[4]["text"])) and per_section.get(section,0) < section_page_limit(row):
                reserve(row)
        if attack_surface_question:
            remaining = [row for row in ranked if (row[3], row[1], row[2]) not in merit_ids]
            primary = [
                row for row in remaining
                if (
                    attack_surface_first_hand_page(row[1], row[4]["text"])
                )
            ][:ATTACK_SURFACE_PRIMARY_PAGE_LIMIT]
            primary_ids = {(row[3], row[1], row[2]) for row in primary}
            exhibits = [
                row for row in remaining
                if (
                    (row[3], row[1], row[2]) not in primary_ids
                    and attack_surface_first_hand_page(row[1], row[4]["text"])
                )
            ][:ATTACK_SURFACE_EXHIBIT_PAGE_LIMIT]
            material_ids = primary_ids | {(row[3], row[1], row[2]) for row in exhibits}
            ordered = merits + primary + exhibits + [
                row for row in remaining
                if (row[3], row[1], row[2]) not in material_ids
            ]
        elif strategic_analysis_question:
            remaining = [
                row for row in ranked
                if (row[3], row[1], row[2]) not in merit_ids
            ]
            strategic_rows = []
            strategic_ids = set()

            def reserve_strategy(signal_index, *, limit=STRATEGIC_CATEGORY_PAGE_LIMIT, per_document=None):
                kept = 0
                document_counts = {}
                for row in remaining:
                    identity = (row[3], row[1], row[2])
                    if identity in strategic_ids or not row[signal_index]:
                        continue
                    document_identity = (row[3], row[1])
                    if (
                        per_document is not None
                        and document_counts.get(document_identity, 0) >= per_document
                    ):
                        continue
                    strategic_rows.append(row)
                    strategic_ids.add(identity)
                    document_counts[document_identity] = (
                        document_counts.get(document_identity, 0) + 1
                    )
                    kept += 1
                    if kept >= limit:
                        break

            # Preserve primary posture and agency material before opinions.
            # This ordering keeps the actual TRO and permit conditions in a
            # crowded record rather than relying only on expert descriptions.
            reserve_strategy(18, limit=STRATEGIC_PROCEDURAL_PAGE_LIMIT, per_document=2)
            # Preserve one direct record for each identified agency before
            # general regulatory ranking can fill the bounded packet.
            for agency in ("nysdec", "usace"):
                for row in remaining:
                    identity = (row[3], row[1], row[2])
                    if (
                        identity not in strategic_ids
                        and direct_agency_issuer(row[4]) == agency
                    ):
                        strategic_rows.append(row)
                        strategic_ids.add(identity)
                        break
            reserve_strategy(17, limit=STRATEGIC_REGULATORY_PAGE_LIMIT, per_document=2)
            # Preserve category diversity before general relevance ranking.
            reserve_strategy(
                13,
                limit=STRATEGIC_EXPERT_PAGE_LIMIT,
                per_document=STRATEGIC_EXPERT_PAGES_PER_DOCUMENT,
            )
            for signal_index in (14, 15, 16):
                reserve_strategy(signal_index)
            ordered = merits + strategic_rows + [
                row for row in remaining
                if (row[3], row[1], row[2]) not in strategic_ids
            ]
        else:
            procedural_rows = [
                row for row in ranked
                if (
                    procedural_posture_question
                    and (row[3], row[1], row[2]) not in merit_ids
                    and ATTACK_SURFACE_PRIMARY_FILENAME_RE.search(
                        normalized_filename(row[1])
                    )
                    and V4_PROCEDURAL_ORDER_TEXT_RE.search(row[4]["text"])
                )
            ]
            procedural_ids = {
                (row[3], row[1], row[2])
                for row in procedural_rows
            }
            ordered = merits + procedural_rows + [
                row for row in ranked
                if (
                    (row[3], row[1], row[2]) not in merit_ids
                    and (row[3], row[1], row[2]) not in procedural_ids
                )
            ]
    ordered_items = targeted_pages + [row[4] for row in ordered]
    for item in ordered_items:
        filename, page, source = item["filename"], item["page_number"], item["source_sha256"]
        item_id = (source, filename, page)
        if item_id in selected_ids:
            continue
        max_context_chars = (
            CONSOLIDATED_MAX_CONTEXT_CHARS
            if consolidated_question
            else MAX_CONTEXT_CHARS
        )
        max_pages = CONSOLIDATED_MAX_PAGES if consolidated_question else MAX_PAGES
        if total+len(item["text"])>max_context_chars or len(selected)>=max_pages:
            continue
        selected.append(item); selected_ids.add(item_id); total+=len(item["text"])
    if not selected:
        raise ValueError("no matching verified evidence")
    missing_mandatory = mandatory_ids.difference(selected_ids)
    if missing_mandatory:
        # Never spend a model call on a pleading map that dropped a required
        # first affirmative-defense page. The bounded details stay internal.
        raise PreGenerationGateError(
            "missing_first_affirmative_defense_page",
            metrics={
                "candidate_document_count": len(selection_documents),
                "candidate_section_count": len(first_defense_page),
                "context_character_count": total,
                "mandatory_page_count": len(mandatory_ids),
                "missing_mandatory_page_count": len(missing_mandatory),
                "selected_page_count": len(selected),
            },
        )
    selected_party_role_ids = party_role_candidates.intersection(selected_ids)
    outside_party_role_ids = party_role_candidates.difference(selected_ids)
    selected_claim_ids = {
        (source, filename, page)
        for _score, filename, page, source, _candidate, merits_pleading,
        _operational, _section_start, _defense, _continuation,
        claim_pleading, _relief_pleading, _prayer_continuation,
        _strategic_expert, _strategic_measurement, _strategic_law,
        _strategic_position, _strategic_regulatory, _strategic_procedural in rows
        if merits_pleading and claim_pleading
    }.intersection(selected_ids)
    selected_relief_ids = {
        (source, filename, page)
        for _score, filename, page, source, _candidate, merits_pleading,
        _operational, _section_start, _defense, _continuation,
        _claim_pleading, relief_pleading, _prayer_continuation,
        _strategic_expert, _strategic_measurement, _strategic_law,
        _strategic_position, _strategic_regulatory, _strategic_procedural in rows
        if merits_pleading and relief_pleading
    }.intersection(selected_ids)
    coverage = {
        "party_role_evidence": {"candidate_count": len(party_role_candidates), "retrieved_count": len(selected_party_role_ids), "outside_initial_slice": bool(outside_party_role_ids), "outside_initial_slice_citations": [{"source_sha256": source, "filename": filename, "page_number": page} for source, filename, page in sorted(outside_party_role_ids, key=lambda item: (item[1].casefold(), item[2], item[0]))[:12]]},
        "pleading_operatives": {
            "claim_page_count": len(selected_claim_ids),
            "relief_page_count": len(selected_relief_ids),
            "claim_citations": [
                {"source_sha256": source, "filename": filename, "page_number": page}
                for source, filename, page in sorted(selected_claim_ids, key=lambda item: (item[1].casefold(), item[2], item[0]))
            ],
            "relief_citations": [
                {"source_sha256": source, "filename": filename, "page_number": page}
                for source, filename, page in sorted(selected_relief_ids, key=lambda item: (item[1].casefold(), item[2], item[0]))
            ],
        },
        "verified_pleading_inventory": verified_pleading_inventory(documents),
    }
    if consolidated_action_audit:
        coverage["third_party_actions"] = consolidated_action_audit
    return EvidenceSelection(selected, coverage)

def pleading_map(pages):
    """Build a citation-only filing map from selected verified pages."""
    filings = {}
    for page in pages:
        filename = page["filename"]
        if not PLEADING_FILENAME_RE.search(normalized_filename(filename)):
            continue
        entry = filings.setdefault(filename, {"filename": filename, "citations": [], "signals": set()})
        entry["citations"].append({key: page[key] for key in ("source_sha256", "filename", "page_number")})
        for label, pattern in (("caption or filing opening", r"\b(supreme court|plaintiff|defendant)\b"), ("causes of action or relief", r"\b(cause of action|wherefore|prayer for relief)\b"), ("answer or denial", r"\b(answer|den(?:y|ies|ied))\b"), ("affirmative defense", r"\baffirmative\s+defen[cs]e"), ("cross-claim or counterclaim", r"\b(cross[ -]?claim|counter[ -]?claim)\b"), ("third-party pleading", r"\b(third[ -]?party|fourth[ -]?party)\b")):
            if re.search(pattern, page["text"], re.IGNORECASE):
                entry["signals"].add(label)
    return [{"filename": item["filename"], "citations": item["citations"], "signals": sorted(item["signals"])} for item in sorted(filings.values(), key=lambda item: item["filename"].casefold())]


CASE00_RUNTIME_CACHE_PREFIX = (
    "Benchmarks/Case-00-Triborough/derived/runtime-cache/"
)
CASE00_PAGE_CACHE_SUFFIX = "/derived/page-extraction/canonical_page_records.json"


def case00_cached_pages(s3):
    """Read the newest canonical Case-00 page cache without rebuilding PDFs."""
    objects = [
        item for item in listed_objects(
            s3,
            Bucket=os.environ["B2_BUCKET"],
            Prefix=CASE00_RUNTIME_CACHE_PREFIX,
            MaxKeys=1000,
        )
        if str(item.get("Key", "")).endswith(CASE00_PAGE_CACHE_SUFFIX)
    ]
    if not objects:
        return None
    newest = max(
        objects,
        key=lambda item: (str(item.get("LastModified", "")), item["Key"]),
    )
    payload = json.loads(
        s3.get_object(Bucket=os.environ["B2_BUCKET"], Key=newest["Key"])["Body"]
        .read()
        .decode()
    )
    pages = payload.get("pages") if isinstance(payload, dict) else None
    if not isinstance(pages, list) or not pages:
        raise ValueError("invalid Case-00 canonical page cache")
    return pages


def case00_evidence(question):
    """Load the immutable Case-00 corpus through its canonical legacy adapter."""
    from scripts import rebuild_case00_derived as rebuild

    root = Path(__file__).resolve().parents[1] / "data" / "case-00-triborough"
    source_prefix = "Benchmarks/Case-00-Triborough/original/Tribrough Full Docket/"
    cfg = rebuild.B2Config.from_env()
    b2 = rebuild.create_b2_client(cfg)
    pages = case00_cached_pages(b2)
    if pages is None:
        with tempfile.TemporaryDirectory(prefix="case00-retrieval-validation-") as temp:
            source = rebuild.materialize_b2_prefix(
                source_prefix, Path(temp), client=b2, config=cfg
            )
            docs = rebuild.ingest_source_directory(
                source, root / "nyscef_filing_inventory.json"
            )
            pages = rebuild.build_canonical_page_records(docs)["pages"]

    normalized_pages = []
    for page in pages:
        filename = page.get("source_filename")
        page_number = page.get("page_number")
        text = " ".join(str(page.get("text", "")).split())
        if text and isinstance(filename, str) and isinstance(page_number, int):
            normalized_pages.append({
                "source_sha256": CASE00_BENCHMARK_ID,
                "filename": filename,
                "page_number": page_number,
                "text": text,
            })
    return normalized_pages


def retrieval_evidence(s3, case_id, question):
    """Route every verified corpus through one model-free validation boundary."""
    if case_id == CASE00_BENCHMARK_ID:
        pages = case00_evidence(question)
        selected = []
        selected_ids = set()
        total = 0
        terms = words(question)
        ranked = sorted(
            pages,
            key=lambda page: (
                -sum(page["text"].casefold().count(term) for term in terms),
                page["filename"].casefold(),
                page["page_number"],
            ),
        )
        def reserve(page):
            nonlocal total
            identity = (page["filename"], page["page_number"])
            if identity in selected_ids:
                return
            text = page["text"][:MAX_PAGE_CHARS]
            if len(selected) >= MAX_PAGES or total + len(text) > MAX_CONTEXT_CHARS:
                return
            selected.append({**page, "text": text})
            selected_ids.add(identity)
            total += len(text)

        filings = {}
        for page in pages:
            if PLEADING_FILENAME_RE.search(normalized_filename(page["filename"])):
                filings.setdefault(page["filename"], []).append(page)
        for filename in sorted(filings, key=str.casefold):
            ordered = sorted(filings[filename], key=lambda page: page["page_number"])
            reserve(ordered[0])
            reserve(ordered[-1])
            kept = 0
            for page in ordered:
                if kept >= 4:
                    break
                if PLEADING_OPERATIONAL_TEXT_RE.search(page["text"]):
                    before = len(selected_ids)
                    reserve(page)
                    kept += len(selected_ids) > before
        for page in ranked:
            reserve(page)
        if not selected:
            raise ValueError("no matching verified evidence")
        return EvidenceSelection(selected, {
            "party_role_evidence": {},
            "pleading_operatives": {},
            "verified_pleading_inventory": verified_pleading_inventory({
                (CASE00_BENCHMARK_ID, filename): [
                    (page["page_number"], page["text"])
                    for page in pages if page["filename"] == filename
                ]
                for filename in {page["filename"] for page in pages}
            }),
        })
    return evidence(s3, case_id, question)


def validate_retrieval(s3, case_id, question):
    """Run the production evidence gate without a model call or B2 write."""
    try:
        pages = retrieval_evidence(s3, case_id, question)
    except PreGenerationGateError as exc:
        if (
            str(exc) == "missing_third_party_complaint"
            and THIRD_PARTY_ONLY_QUESTION_RE.search(question)
        ):
            # Absence is a valid result for a layer-existence check. Report it
            # explicitly without treating the case as broken or spending a
            # model call to narrate an empty layer.
            return {
                "case_id": case_id,
                "status": "PASSED",
                "model_called": False,
                "layer": "third-party",
                "layer_present": False,
                "gate_reason": "missing_third_party_complaint",
                "selected_page_count": 0,
                "context_character_count": 0,
                "selected_document_count": 0,
                "pleading_document_count": 0,
                "pleading_signal_counts": {},
                "coverage": {
                    "third_party_action_count": 0,
                    "third_party_answered_action_count": 0,
                    "third_party_unresolved_action_count": 0,
                },
            }
        raise
    coverage = getattr(pages, "coverage", {}) or {}
    filings = pleading_map(pages)
    party_roles = coverage.get("party_role_evidence", {})
    operatives = coverage.get("pleading_operatives", {})
    third_party_actions = coverage.get("third_party_actions", [])
    return {
        "case_id": case_id,
        "status": "PASSED",
        "model_called": False,
        "selected_page_count": len(pages),
        "context_character_count": sum(len(page["text"]) for page in pages),
        "selected_document_count": len({
            (page["source_sha256"], page["filename"]) for page in pages
        }),
        "pleading_document_count": len(filings),
        "pleading_signal_counts": {
            signal: sum(signal in filing["signals"] for filing in filings)
            for signal in (
                "caption or filing opening",
                "causes of action or relief",
                "answer or denial",
                "affirmative defense",
                "cross-claim or counterclaim",
                "third-party pleading",
            )
        },
        "coverage": {
            "party_role_candidate_count": party_roles.get("candidate_count", 0),
            "party_role_retrieved_count": party_roles.get("retrieved_count", 0),
            "party_role_outside_initial_slice": bool(
                party_roles.get("outside_initial_slice", False)
            ),
            "claim_page_count": operatives.get("claim_page_count", 0),
            "relief_page_count": operatives.get("relief_page_count", 0),
            "verified_pleading_inventory_count": len(
                coverage.get("verified_pleading_inventory", [])
            ),
            "third_party_action_count": len(third_party_actions),
            "third_party_answered_action_count": sum(
                bool(action.get("answer_present"))
                for action in third_party_actions
            ),
            "third_party_unresolved_action_count": sum(
                bool(action.get("unresolved"))
                for action in third_party_actions
            ),
        },
    }

def authority_prompt(authorities):
    """Return verified authority content suitable for model rule analysis."""
    return [authority.as_canonical_dict() | {"sha256": authority.sha256} for authority in authorities]


def authority_audit(authorities):
    """Return bounded authority identity metadata without proposition text."""
    return [{
        key: getattr(authority, key)
        for key in ("authority_id", "citation", "official_primary_source", "filing_record_citation", "sha256")
    } for authority in authorities]


ATTORNEY_ANSWER_SECTIONS = (
    "Legal standard",
    "Application",
    "Policy-by-policy analysis",
    "Bottom line",
)
STRATEGIC_ANALYSIS_SECTIONS = (
    "Case framework",
    "Evidence",
    "Competing positions",
    "Assessment",
)
MOTION_RECOMMENDATION_SECTIONS = (
    "Objective and posture",
    "Candidate motions",
    "Record support",
    "Likely opposition",
    "Gaps and prerequisites",
    "Recommendation",
)
MOTION_RESPONSE_SECTIONS = (
    "Motion and burden",
    "Opponent showing",
    "Response grounds",
    "Evidence to submit",
    "Procedural objections",
    "Recommendation",
)
LITIGATION_MAP_SECTIONS = (
    "Main case",
    "Counterclaims and cross-claims",
    "Third-party claims",
)
LITIGATION_MAP_QUESTION_RE = re.compile(
    r"\b(?:litigation\s+map|parties?.{0,80}(?:claims?|defen[cs]es?|relief)|"
    r"claims?.{0,80}(?:parties?|defen[cs]es?|relief))\b",
    re.IGNORECASE,
)
INCOMPLETE_SENTENCE_RE = re.compile(r"(?:[,;:]|\b(?:and|or|the|a|an|to|of|for|with|by|from))\s*$", re.IGNORECASE)
CLOSING_SENTENCE_MARK_RE = re.compile(r"[\'’\"”]\s*$")
TRUNCATED_TERMINAL_WORD_RE = re.compile(r"\b([a-z]{1,2})\.$", re.IGNORECASE)
VALID_SHORT_TERMINAL_WORDS = frozenset({
    "a", "an", "as", "at", "by", "do", "go", "he", "if", "in", "is",
    "it", "me", "my", "no", "of", "oh", "on", "or", "so", "to", "up",
    "us", "we",
})
UNSELECTED_PAGES_MISSING_RE = re.compile(
    r"\b(?:pages?|pp?\.)\s*\d+(?:\s*[-–—]\s*\d+)?\s+(?:was|were|is|are)?\s*"
    r"(?:not\s+supplied|not\s+provided|missing|absent|unavailable)\b",
    re.IGNORECASE,
)
PRESENT_PLEADING_MISSING_RE = re.compile(
    r"\b(?:complaints?|answers?|third[ -]?party\s+(?:summons|complaints?)|bill(?:s)?\s+of\s+particulars)\b.{0,80}\b"
    r"(?:missing|absent|not\s+supplied|not\s+provided|unavailable)\b",
    re.IGNORECASE,
)
ACTION_SPECIFIC_MISSING_ANSWER_RE = re.compile(
    r"\b(?:corresponding\s+answer|answer\s+for\s+the\s+"
    r"(?:first|second|third|fourth)\s+action)\b.{0,80}\b"
    r"(?:missing|absent|not\s+supplied|not\s+provided|unavailable)\b|"
    r"\bno\s+corresponding\s+answer\b",
    re.IGNORECASE,
)


def pleading_kind(filename: str, pages) -> str | None:
    """Classify a verified pleading using its filename and opening text."""
    combined = f"{normalized_filename(filename)} {' '.join(text for _, text in sorted(pages)[:2]).casefold()[:2400]}"
    if "bill of particulars" in combined or "bills of particulars" in combined:
        return "bill of particulars"
    if re.search(r"\b(?:third|fourth) party\b", combined):
        if "answer" in combined:
            return "third-party answer"
        if "complaint" in combined or "summons" in combined:
            return "third-party complaint"
    if "counterclaim" in combined:
        return "counterclaim"
    if "cross claim" in combined or "crossclaim" in combined:
        return "cross-claim"
    if "answer" in combined:
        return "answer"
    if "complaint" in combined:
        return "complaint"
    return None


def verified_pleading_inventory(documents):
    """Describe every verified pleading without copying full text into the prompt."""
    inventory = []
    for (source, filename), document_pages in documents.items():
        kind = pleading_kind(filename, document_pages)
        if not kind:
            continue
        page_numbers = sorted({page for page, _ in document_pages})
        inventory.append({"source_sha256": source, "filename": filename, "filing_kind": kind, "page_count": len(page_numbers), "first_page": page_numbers[0], "last_page": page_numbers[-1]})
    return sorted(inventory, key=lambda item: (item["filing_kind"], item["filename"].casefold(), item["source_sha256"]))


def litigation_map_question(question: str) -> bool:
    """Identify record-map requests that require ordered, concise sections."""
    terms = words(question)
    return bool(LITIGATION_MAP_QUESTION_RE.search(question)) or len(BROAD_RECORD_TERMS.intersection(terms)) >= 2


def finding_schema(page_citation_properties, *, attorney_sections=False, litigation_map=False, strategic_analysis=False, reasoning_mode="strategic_analysis", max_findings=8, statement_max_length=900):
    """Build the strict source-aware finding schema for either worker."""
    page_required = list(page_citation_properties)
    citation_schema = {
        "type": "array",
        "items": {
            "type": "object", "additionalProperties": False,
            "required": page_required, "properties": page_citation_properties,
        },
    }
    if not attorney_sections:
        # Record-only findings have no authority fallback. Enforce the same
        # citation invariant in the generation schema that validate() applies
        # afterward, preventing a paid response from being rejected solely for
        # an empty citations array.
        citation_schema["minItems"] = 1
    finding_properties = {"statement":{"type":"string","maxLength":statement_max_length},"citations":citation_schema,"authority_citations":{"type":"array","items":{"type":"string"}}}
    finding_required = ["statement", "citations", "authority_citations"]
    sections = (
        MOTION_RECOMMENDATION_SECTIONS
        if strategic_analysis and reasoning_mode == "motion_recommendation"
        else MOTION_RESPONSE_SECTIONS
        if strategic_analysis and reasoning_mode == "motion_response"
        else STRATEGIC_ANALYSIS_SECTIONS
        if strategic_analysis
        else ATTORNEY_ANSWER_SECTIONS
        if attorney_sections
        else LITIGATION_MAP_SECTIONS
        if litigation_map
        else ()
    )
    if sections:
        finding_properties = {"section":{"type":"string","enum":list(sections)}, **finding_properties}
        finding_required = ["section", *finding_required]
    return {"type":"object","additionalProperties":False,"required":["summary","findings","missing_information","limitations"],"properties":{"summary":{"type":"string","maxLength":800},"findings":{"type":"array","minItems":1,"maxItems":max_findings,"items":{"type":"object","additionalProperties":False,"required":finding_required,"properties":finding_properties}},"missing_information":{"type":"array","maxItems":8,"items":{"type":"string","maxLength":300}},"limitations":{"type":"array","maxItems":4,"items":{"type":"string","maxLength":300}}}}


def generate(question, pages, coverage=None, authorities=None):
    authorities = tuple(() if authorities is None else authorities)
    detected_reasoning_mode = question_mode(question)
    strategic_question = (
        bool(STRATEGIC_ANALYSIS_QUESTION_RE.search(question))
        or detected_reasoning_mode != "strategic_analysis"
    ) and not litigation_map_question(question) and TOP_ATTACK_SURFACES_MARKER not in question.casefold()
    map_question = litigation_map_question(question) and not authorities and not strategic_question and TOP_ATTACK_SURFACES_MARKER not in question.casefold()
    third_party_action_count = len((coverage or {}).get("third_party_actions", []))
    reasoning_mode = detected_reasoning_mode if strategic_question else ""
    reasoning_context = build_reasoning_context(question, pages) if strategic_question else None
    schema=finding_schema({"source_sha256":{"type":"string"},"filename":{"type":"string"},"page_number":{"type":"integer","minimum":1}}, attorney_sections=bool(authorities) and not strategic_question, litigation_map=map_question, strategic_analysis=strategic_question, reasoning_mode=reasoning_mode, max_findings=len(LITIGATION_MAP_SECTIONS) if map_question else 8, statement_max_length=2400 if third_party_action_count > 1 else 1200 if strategic_question else 900)
    instructions = "Use only the supplied verified excerpts and legal authorities. This is an internal attorney-review draft, not legal advice or a conclusion. Make no unsupported inference. Case-record facts cite only page citations in citations; legal rules cite only authority ids in authority_citations; application findings should cite both where appropriate. Do not overstate court level, controlling effect, or proposition scope. Every finding must have at least one verified source across those two arrays. Before stating that information is missing or calling something an open question, check the entire supplied record-wide excerpt set, including caption pages and operative pages from related pleadings. Never call a page range missing merely because it was not selected into the bounded retrieval slice; describe the bounded retrieval limitation instead. Use the filing map only as a navigation aid; verify every proposition against its cited pages. Treat pleaded alternatives, denials, and defenses as attributed litigation positions, not established facts or contradictions. For a question about parties, claims, defenses, or relief, return a compact litigation map, not a memo; it must be attorney-readable. The summary must be one sentence of no more than 28 words and may name only claim categories, counterclaim categories, and categories of missing material; do not include party roles, ownership, control, or other factual positions. Return at most one finding for each populated heading, in this exact order: (1) Main case; (2) counterclaims and cross-claims; (3) third-party claims. Put the exact heading in the section field. Each finding must use this one-line shape: '[expressly named parties and short roles]: [claim labels]; defenses: [short labels]; relief: [short label].' Use labels only (for example, breach, lien foreclosure, negligence, statute of limitations, payment); do not explain allegations, evidence, legal standards, or why a position may succeed. In the claims field, list only an expressly asserted cause-of-action label; do not place a plaintiff-side ownership position, party-role statement, necessary-party label, or other non-claim there. In the defenses field, list only a defense attributed to the responding party; do not place a plaintiff-side allegation, ownership position, necessary-party label, or other non-defense there. List no more than three material defense labels for each party. Collapse any additional routine defenses into the single label 'affirmative defenses'; do not enumerate waiver, estoppel, laches, unclean hands, comparative fault, or similar boilerplate separately unless one is the only material defense expressly identified in the supplied record. Omit an empty heading rather than narrating that it is empty. List only the parties named in the caption or operative pleading. Do not invent, infer, or call out an unnamed party from a missing or partial caption. List a John Doe, XYZ entity, or other placeholder only if a supplied verified pleading expressly names it. If a supplied order shows that a motion was disposed of because a party died and substitution is pending, label it a procedural disposition, not a merits decision; state only the procedural consequence shown by that order. Do not use dense narrative. End every summary, finding, missing-information item, and limitation with a complete sentence; never truncate text to fill a schema limit. End the Counterclaims and cross-claims finding with its relief label and a period, never with a quotation mark, dash, colon, semicolon, or conjunction. When supplied pages contain both an ownership assertion and a party's nonresidence or no-control statement, present both as attributed, competing record positions with citations; do not omit either or treat either as conclusively established. Do not portray a pleading typo or general denial as case-dispositive unless a supplied court ruling makes it so. Identify missing information only when it remains unsupported after that record-wide check."
    if TOP_ATTACK_SURFACES_MARKER in question.casefold():
        instructions += " For the v4.0 Top Attack Surfaces Report, do not prepend or return a claims-map summary. If a supplied order shows a motion was disposed of because a party died and substitution is pending, identify it as a procedural disposition, not a merits decision, and state only the procedural consequence shown by that order."
        instructions += " For the v4.0 Top Attack Surfaces Report, prioritize identified pleadings, orders, sworn testimony, and party-specific exhibits over generic contract excerpts. Use a generic contract provision only where it directly conflicts with, limits, or corroborates a party-identified filing or evidence in the supplied pages. Return no more than eight findings ordered from highest to lower materiality; return fewer when fewer qualify. Start every finding with 'Rank N — [Contradiction / Credibility / Procedural weakness] —'. For every finding, use this attorney-readable sequence in the statement: (1) identify the affected party or litigation position only when expressly named in the supplied pages; (2) state the specific record proposition on each side of the tension, including the source type or filing where useful; (3) explain why the two propositions create the asserted vulnerability; and (4) state any material limit. Never use a broad label such as 'causation record' or 'notice challenge' without the particular propositions that support it. A contradiction must cite each of the two conflicting verified propositions. A credibility vulnerability must identify the person or party and the concrete inconsistency, omission, or conflict; if the record does not identify one, do not call it a credibility issue. A procedural weakness must identify the party position, pleading, order, burden, remedy, notice, timing, preservation, or posture actually shown. Do not rank a defense merely because its factual proof, operative pleading, policy, or other supporting material is absent from the supplied excerpts. It qualifies only when the supplied pages show an affirmative mismatch with a contract, order, testimony, or other identified evidence, or when a court actually addressed the position. Do not invent a weakness from silence, characterize advocacy as fact, or convert alternative pleading or a denial into a contradiction. A pleading may establish procedural posture only. Do not make a factual or credibility finding from an attorney affirmation, counsel statement, service affidavit, or a party’s characterization of an absent exhibit, deposition, report, or other evidence. When the underlying first-hand material is not among the supplied pages, identify that limitation and omit the finding rather than treating advocacy as proof."
    elif strategic_question:
        instructions += " For this strategic-analysis question, the following instructions override the earlier compact litigation-map format. Give a direct attorney answer, not a source list. Treat the supplied litigation_reasoning_context as deterministic routing and classification metadata only, never as independent proof. Expert opinion is evidence, not law; distinguish design or technical experience from regulatory experience. Analyze supplied DEC or other regulatory material and supplied drawings, surveys, plans, photographs, and measurements instead of calling them missing. Weigh cases and rules cited in party filings as attributed positions unless independently supplied in legal_authorities. In the Evidence section, describe the source, its methodology or factual content, and its limits only; put both sides' allegations, denials, and advocacy in Competing positions. For each expert account of DEC or other agency material, state whether the underlying agency record itself is cited or whether the point rests only on the expert's description; never describe the latter as an agency finding or adjudication. When no direct agency-record citation supports that expert account, state exactly: 'Underlying agency record is not cited.'"
        if reasoning_mode == "motion_recommendation":
            instructions += " The attorney asks which motions to consider. Use every section in this exact order: Objective and posture; Candidate motions; Record support; Likely opposition; Gaps and prerequisites; Recommendation. Identify only motions supported by the verified posture and record. For each candidate, state the target, required showing only when verified authority supplies it, record support, strongest opposition, prerequisite proof or procedural step, and comparative reason to prioritize or reject it. When the supplied record includes expert opinion, a direct regulatory record, or drawing/measurement evidence, return three separate Record support findings before Likely opposition: one citing expert evidence, one citing the direct regulatory record, and one citing visual or measurement evidence. Do not combine or omit those categories, and do not put their analysis only in another section. When the supplied direct regulatory records identify more than one agency, cite and analyze each agency's record; an expert's account or a subpoena request cannot substitute for the direct record. If the exact signed TRO terms, duration, or current status are unresolved, do not recommend filing a TRO-modification motion now; instead identify the order as a prerequisite and limit any recommendation to preserving rights, obtaining the order, or seeking a record-supported conference or hearing. Do not recommend a motion merely because the record mentions its name. Keep each finding below 150 words and end it with a complete sentence; never end a finding with a connector, comma, colon, or semicolon. The summary must directly identify the best-supported motion option or state that the verified record is not yet sufficient to choose one."
        elif reasoning_mode == "motion_response":
            instructions += " The attorney asks how to answer an opponent's motion. Use every section in this exact order: Motion and burden; Opponent showing; Response grounds; Evidence to submit; Procedural objections; Recommendation. Identify the relief sought and procedural posture, test each asserted ground against the verified record, separate merits responses from procedural objections, identify admissible or first-hand proof to submit, and rank the strongest response. When supplied direct regulatory records identify more than one agency, cite and analyze each agency's record in the record-analysis sections; an expert's account or a subpoena request cannot substitute for a direct record. Do not invent a deadline, burden, element, or doctrine not supplied by verified authority."
        else:
            instructions += " Use all four sections in this order: Case framework; Evidence; Competing positions; Assessment. Each section must appear at least once; multiple findings within a section are allowed but sections must never move backward. First identify who is who and the material property, transaction, event, or physical layout. Then extract the concrete opinions and factual premises from each expert or fact witness, including measurements and regulatory constraints. Compare the parties' best arguments point by point, identifying the evidence and law each side cites. Rank the material weaknesses or strengths, explain why each affects the requested party, give the strongest counterargument, and state the unresolved fact or authority that could change the assessment."
        instructions += " Do not merely say that interference, breach, causation, or another element is shown; explain the specific evidence and competing position. The summary must answer the question directly in no more than 90 words. Return no more than eight findings and avoid repeating the same fact in multiple sections. Each missing_information item must be a self-contained, complete sentence describing one specific record, fact, or authority that could change the assessment. Before returning JSON, verify that every missing_information item ends with a period, question mark, or exclamation point and never ends with a connector such as and, or, but, because, or a comma."
    elif authorities:
        instructions += " For this authority-backed question, the following instructions override the earlier compact litigation-map format."
        instructions += " End the summary with a complete sentence; never truncate a sentence to fill the schema limit."
        instructions += " Produce a concise attorney answer, not a memorandum. The summary must be a two-sentence executive answer of no more than 70 words. Return no more than eight non-repetitive findings total, each no more than 110 words, using the section field in this order: Legal standard; Application; Policy-by-policy analysis; Bottom line. Use at most two findings per section. State each legal rule once; apply it by reference rather than repeating it. Distinguish primary and excess policies only where the supplied record permits. Put absent proof only in missing_information, as no more than eight short, prioritized bullets; do not repeat missing evidence in the findings or limitations. The Bottom line must give the present record-based assessment and the evidence that would most change it, without predicting an outcome unsupported by the sources."
    prompt={"question":question,"instructions":instructions,"pleading_map":pleading_map(pages),"pages":pages,"legal_authorities":authority_prompt(authorities)}
    if reasoning_context is not None:
        prompt["litigation_reasoning_context"] = reasoning_context
    if coverage and coverage.get("verified_pleading_inventory"):
        prompt["verified_pleading_inventory"] = coverage["verified_pleading_inventory"]
        prompt["instructions"] += " The verified_pleading_inventory is authoritative presence metadata for the complete verified corpus. A listed filing exists in the verified record even when only selected pages appear in pages. Never call a listed filing missing, absent, unavailable, not supplied, or not provided. If selected excerpts do not establish a requested detail, identify that exact detail as unresolved rather than claiming that the filing itself is missing."
    if coverage and coverage.get("third_party_actions"):
        prompt["third_party_actions"] = coverage["third_party_actions"]
        prompt["instructions"] += " The third_party_actions array is the deterministically validated action map. Address every listed action in ordinal order within the single Third-party claims finding. For each action identify the cited parties, claim labels, defense labels, requested relief, and any listed unresolved item. Do not merge parties or positions across actions."
    if coverage and coverage["party_role_evidence"]["outside_initial_slice"]:
        prompt["record_coverage"] = {"party_role_evidence_outside_initial_slice": True, "instruction": "Do not infer that party-role evidence is absent merely because it is not among the supplied excerpts; state that the bounded retrieval slice requires attorney follow-up before treating it as missing."}
    payload={"model":os.environ.get("LEGALAI_OPENAI_MODEL","gpt-5.6-sol"),"instructions":"Return only strict JSON matching the schema.","input":json.dumps(prompt),"text":{"format":{"type":"json_schema","name":"verified_internal_draft","strict":True,"schema":schema}}}
    request=urllib.request.Request("https://api.openai.com/v1/responses",data=json.dumps(payload).encode(),headers={"Authorization":f"Bearer {os.environ['OPENAI_API_KEY']}","Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen(request,timeout=int(os.environ.get("LEGALAI_MODEL_TIMEOUT_SECONDS","180"))) as response: body=json.loads(response.read().decode())
    texts=[c.get("text") for o in body.get("output",[]) if isinstance(o,dict) for c in o.get("content",[]) if isinstance(c,dict) and isinstance(c.get("text"),str)]
    for text in texts:
        try: result=json.loads(text)
        except json.JSONDecodeError: continue
        if isinstance(result,dict): return result
    raise ValueError("model response invalid")

def validate(result, pages, authorities=(), question="", coverage=None):
    allowed={(p["source_sha256"],p["filename"],p["page_number"]) for p in pages}
    allowed_authorities={authority.authority_id for authority in authorities}
    if not isinstance(result,dict) or not isinstance(result.get("findings"),list) or not result["findings"]: raise ValueError("invalid output")
    for finding in result["findings"]:
        if not isinstance(finding,dict) or not isinstance(finding.get("statement"),str) or not isinstance(finding.get("citations"),list) or not isinstance(finding.get("authority_citations"),list): raise ValueError("uncited output")
        if not finding["citations"] and not finding["authority_citations"]: raise ValueError("uncited output")
        for cite in finding["citations"]:
            if not isinstance(cite,dict) or (cite.get("source_sha256"),cite.get("filename"),cite.get("page_number")) not in allowed: raise ValueError("unverified citation")
        if any(not isinstance(authority_id, str) or authority_id not in allowed_authorities for authority_id in finding["authority_citations"]):
            raise ValueError("unverified authority citation")
    strategic_question = bool(STRATEGIC_ANALYSIS_QUESTION_RE.search(question)) and not litigation_map_question(question) and TOP_ATTACK_SURFACES_MARKER not in question.casefold()
    strict_output = litigation_map_question(question) or TOP_ATTACK_SURFACES_MARKER in question.casefold() or strategic_question
    if strict_output:
        # JSON-schema generation guarantees bounded strings but not terminal
        # punctuation. Normalize otherwise complete prose deterministically;
        # retain fail-closed behavior for empty, connector-ended, or dangling-
        # quote text that may actually be truncated.
        sentence_fields = [
            (result, "summary", "summary"),
            *[
                (
                    finding,
                    "statement",
                    {
                        "Main case": "main case",
                        "Counterclaims and cross-claims": "counterclaims and cross claims",
                        "Third-party claims": "third party claims",
                    }.get(finding.get("section"), "finding"),
                )
                for finding in result["findings"]
            ],
        ]
        for collection_name in ("missing_information", "limitations"):
            collection = result.get(collection_name, [])
            label = collection_name.replace("_", " ")
            sentence_fields.extend((collection, index, label) for index in range(len(collection)))
        for container, field, label in sentence_fields:
            item = container.get(field) if isinstance(container, dict) else container[field]
            if not isinstance(item, str) or not item.strip():
                raise ValueError(f"incomplete output {label} empty")
            cleaned = item.strip()
            if cleaned[-1] not in ".?!":
                if len(cleaned) >= 2350:
                    raise ValueError(f"incomplete output {label} near schema limit")
                unquoted = CLOSING_SENTENCE_MARK_RE.sub("", cleaned).rstrip()
                if not unquoted:
                    raise ValueError(f"incomplete output {label} invalid terminal")
                if INCOMPLETE_SENTENCE_RE.search(unquoted):
                    raise ValueError(f"incomplete output {label} connector ended")
                cleaned += "."
                if isinstance(container, dict):
                    container[field] = cleaned
                else:
                    container[field] = cleaned
        text_items = [result.get("summary", ""), *[item["statement"] for item in result["findings"]], *result.get("missing_information", []), *result.get("limitations", [])]
        for container, field, label in sentence_fields:
            item = container.get(field) if isinstance(container, dict) else container[field]
            if (
                not isinstance(item, str)
                or not item.strip()
                or item.strip()[-1] not in ".?!"
                or INCOMPLETE_SENTENCE_RE.search(item.strip())
                or (
                    (terminal_fragment := TRUNCATED_TERMINAL_WORD_RE.search(item.strip()))
                    and terminal_fragment.group(1).casefold()
                    not in VALID_SHORT_TERMINAL_WORDS
                )
            ):
                raise ValueError(f"incomplete output {label} invalid terminal")
        if any(UNSELECTED_PAGES_MISSING_RE.search(item) for item in text_items):
            raise ValueError("unverified missing-page claim")
        inventory = (coverage or {}).get("verified_pleading_inventory", [])
        present_kinds = {item.get("filing_kind") for item in inventory if isinstance(item, dict)}
        unresolved_action_answer = any(
            isinstance(action, dict) and not action.get("answer_present", False)
            for action in (coverage or {}).get("third_party_actions", [])
        )
        if present_kinds and any(
            PRESENT_PLEADING_MISSING_RE.search(item)
            and any(kind in item.casefold() for kind in present_kinds if isinstance(kind, str))
            and not (
                unresolved_action_answer
                and ACTION_SPECIFIC_MISSING_ANSWER_RE.search(item)
            )
            for item in text_items
        ):
            raise ValueError("verified pleading called missing")
        third_party_actions = (coverage or {}).get("third_party_actions", [])
        if third_party_actions:
            third_party_findings = [
                finding for finding in result["findings"]
                if finding.get("section") == "Third-party claims"
            ]
            if len(third_party_findings) != 1:
                raise ValueError("incomplete third-party actions")
            statement = third_party_findings[0]["statement"]
            positions = []
            for action in third_party_actions:
                ordinal = action.get("ordinal") if isinstance(action, dict) else None
                match = re.search(
                    rf"\b{re.escape(str(ordinal))}(?:\s+third[ -]?party)?\s+action\b",
                    statement,
                    re.IGNORECASE,
                ) if ordinal else None
                if match is None or (positions and match.start() <= positions[-1][1]):
                    raise ValueError("incomplete third-party actions")
                positions.append((action, match.start(), match.end()))
            for index, (action, _, start) in enumerate(positions):
                end = positions[index + 1][1] if index + 1 < len(positions) else len(statement)
                action_text = statement[start:end]
                if "defenses:" not in action_text.casefold() or "relief:" not in action_text.casefold():
                    raise ValueError("incomplete third-party actions")
                if not action.get("answer_present", False) and not re.search(
                    r"\bno corresponding answer was identified\b",
                    action_text,
                    re.IGNORECASE,
                ):
                    raise ValueError("incomplete third-party actions")
    if strategic_question:
        for finding in result["findings"]:
            if finding.get("section") != "Evidence":
                continue
            position_parties = {
                match.group("party").casefold()
                for match in STRATEGIC_PARTY_POSITION_RE.finditer(
                    str(finding.get("statement", ""))
                )
            }
            if ({"plaintiff", "plaintiffs"}.intersection(position_parties)
                    and {"defendant", "defendants"}.intersection(position_parties)):
                raise ValueError("party positions placed in evidence")
            cited_types = {
                classify_page(page)["source_type"]
                for cite in finding["citations"]
                for page in pages
                if (page["source_sha256"], page["filename"], page["page_number"])
                == (cite.get("source_sha256"), cite.get("filename"), cite.get("page_number"))
            }
            statement = str(finding.get("statement", ""))
            agency_terms = re.search(
                r"\b(?:DEC|Department of Environmental Conservation|agency|permit|regulatory)\b",
                statement,
                re.IGNORECASE,
            )
            expert_account = (
                "expert_opinion" in cited_types
                or re.search(r"\b(?:expert|engineer|P\.?E\.?)\b", statement, re.IGNORECASE)
            )
            if (
                agency_terms
                and expert_account
                and "regulatory_record" not in cited_types
                and not re.search(
                    r"\bunderlying agency record is not cited\b",
                    statement,
                    re.IGNORECASE,
                )
            ):
                raise ValueError("expert agency account lacks source-status disclosure")
        # A strategic answer cannot satisfy the attorney's request by merely
        # naming material record categories.  When the bounded record supplies
        # an expert opinion, an agency/regulatory record, or a drawing/
        # measurement source, the record-analysis sections must actually cite each
        # supplied category.  This remains record-bound and does not impose a
        # category that the retrieval did not return.
        citation_types = {
            (page["source_sha256"], page["filename"], page["page_number"]):
            classify_page(page)["source_type"]
            for page in pages
        }
        required_evidence_types = {
            source_type
            for source_type in citation_types.values()
            if source_type in {
                "expert_opinion",
                "regulatory_record",
                "visual_or_measurement_evidence",
            }
        }
        evidence_sections = (
            {"Record support"}
            if question_mode(question) == "motion_recommendation"
            else {"Opponent showing", "Response grounds", "Evidence to submit"}
            if question_mode(question) == "motion_response"
            else {"Evidence"}
        )
        evidence_types_used = {
            citation_types.get(
                (cite.get("source_sha256"), cite.get("filename"), cite.get("page_number"))
            )
            for finding in result["findings"]
            if finding.get("section") in evidence_sections
            for cite in finding["citations"]
        }
        missing_evidence_types = required_evidence_types - evidence_types_used
        if missing_evidence_types:
            raise ValueError(
                "strategic evidence categories not analyzed: "
                + ", ".join(sorted(missing_evidence_types))
            )
        if question_mode(question) in {"motion_recommendation", "motion_response"}:
            agency_sections = (
                {"Record support"}
                if question_mode(question) == "motion_recommendation"
                else {"Opponent showing", "Response grounds", "Evidence to submit"}
            )
            required_agencies = {
                issuer
                for page in pages
                if (issuer := direct_agency_issuer(page)) is not None
            }
            cited_agencies = {
                issuer
                for finding in result["findings"]
                if finding.get("section") in agency_sections
                for cite in finding["citations"]
                for page in pages
                if (page["source_sha256"], page["filename"], page["page_number"])
                == (cite.get("source_sha256"), cite.get("filename"), cite.get("page_number"))
                if (issuer := direct_agency_issuer(page)) is not None
            }
            missing_agencies = required_agencies - cited_agencies
            if missing_agencies:
                raise ValueError(
                    "strategic direct agency records not analyzed: "
                    + ", ".join(sorted(missing_agencies))
                )
        sections = [item.get("section") for item in result["findings"]]
        expected_sections = (
            MOTION_RECOMMENDATION_SECTIONS
            if question_mode(question) == "motion_recommendation"
            else MOTION_RESPONSE_SECTIONS
            if question_mode(question) == "motion_response"
            else STRATEGIC_ANALYSIS_SECTIONS
        )
        positions = {
            section: index
            for index, section in enumerate(expected_sections)
        }
        section_positions = [positions.get(section, -1) for section in sections]
        if (
            set(sections) != set(expected_sections)
            or any(position < 0 for position in section_positions)
            or section_positions != sorted(section_positions)
        ):
            raise ValueError("invalid strategic-analysis sections")
    if litigation_map_question(question) and not authorities and not strategic_question and TOP_ATTACK_SURFACES_MARKER not in question.casefold():
        sections = [item.get("section") for item in result["findings"]]
        expected = [section for section in LITIGATION_MAP_SECTIONS if section in sections]
        third_party_only = bool(THIRD_PARTY_ONLY_QUESTION_RE.search(question))
        consolidated = bool(CONSOLIDATED_LITIGATION_MAP_RE.search(question))
        # A third-party-only request commonly names counter/cross-claims only
        # to exclude them.  The positive third-party scope therefore wins over
        # the broader cross-claim detector.
        cross_claim_only = (
            bool(CROSS_CLAIM_ONLY_QUESTION_RE.search(question))
            and not third_party_only
            and not consolidated
        )
        consolidated_sections = list(
            (coverage or {}).get("composition_sources", LITIGATION_MAP_SECTIONS)
        )
        invalid_scope = (
            (cross_claim_only and sections != ["Counterclaims and cross-claims"])
            or (third_party_only and sections != ["Third-party claims"])
            or (consolidated and sections != consolidated_sections)
        )
        missing_main_case = (
            not cross_claim_only
            and not third_party_only
            and sections
            and sections[0] != "Main case"
        )
        if not sections or any(section not in LITIGATION_MAP_SECTIONS for section in sections) or len(sections) != len(set(sections)) or sections != expected or invalid_scope or missing_main_case:
            raise ValueError("invalid litigation-map sections")
    return result

def run_request(s3, case_id, request_id):
    # Cancellation is durable for every worker, including the Case-00 adapter.
    if request_status(s3, case_id, request_id) == "CANCELLED":
        return
    if case_id == CASE00_BENCHMARK_ID:
        try:
            from scripts import run_case00_internal_draft
        except ModuleNotFoundError:
            import run_case00_internal_draft
        return run_case00_internal_draft.run_request(s3, request_id)
    now=lambda: datetime.now(timezone.utc).isoformat()
    put(s3,case_id,request_id,"status.json",{"schema_version":"legalai-internal-draft-status.v1","case_id":case_id,"request_id":request_id,"status":"RUNNING","updated_at":now()})
    stage = "request_load"
    try:
        question=read_request(s3,case_id,request_id)
        if CONSOLIDATED_LITIGATION_MAP_RE.search(question):
            stage = "layer_composition"
            result, pages, coverage = compose_validated_layers(s3, case_id, question)
            authorities = ()
        else:
            stage = "evidence_retrieval"
            pages=evidence(s3,case_id,question)
            stage = "authority_selection"
            authorities=load_reviewed_authorities(s3, case_id)
            coverage=getattr(pages,"coverage",None)
            stage = "model_request"
            generated=generate(question,pages,coverage,authorities)
            stage = "model_validation"
            result=validate(generated,pages,authorities,question,coverage)
        # Generation may have started before cancellation.  Preserve the audit
        # trail but never publish a cancelled draft as READY.
        if request_status(s3, case_id, request_id) == "CANCELLED":
            return
        draft={"schema_version":"legalai-internal-draft.v1","case_id":case_id,"request_id":request_id,"question":question,"review_required":True,"external_communication":False,"generated_at":now(),**result}
        stage = "draft_write"
        put(s3,case_id,request_id,"draft.json",draft)
        stage = "audit_write"
        put(s3,case_id,request_id,"input_audit.json",{"schema_version":"legalai-internal-draft-audit.v1","case_id":case_id,"request_id":request_id,"question_sha256":hashlib.sha256(question.encode()).hexdigest(),"retrieval_citations":[{k:p[k] for k in ("source_sha256","filename","page_number")} for p in pages],"legal_authorities":authority_audit(authorities),"coverage":coverage or {},"generated_at":now()})
        stage = "ready_write"
        put(s3,case_id,request_id,"status.json",{"schema_version":"legalai-internal-draft-status.v1","case_id":case_id,"request_id":request_id,"status":"READY","updated_at":now()})
    except Exception as exc:
        if request_status(s3, case_id, request_id) == "CANCELLED":
            return
        diagnostics = failure_diagnostics(exc, stage)
        log_failure(case_id, request_id, diagnostics)
        put(s3,case_id,request_id,"status.json",{"schema_version":"legalai-internal-draft-status.v1","case_id":case_id,"request_id":request_id,"status":"FAILED",**diagnostics,"updated_at":now()})
        exc._legalai_failure_diagnostics = diagnostics
        raise

WORKER_STATUS_KEY = "operations/internal-draft-worker/status.json"

def write_worker_status(s3, status, **fields):
    value = {
        "schema_version": "legalai-internal-draft-worker-status.v1",
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **fields,
    }
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    s3.put_object(Bucket=os.environ["B2_BUCKET"], Key=WORKER_STATUS_KEY, Body=raw,
                  ContentType="application/json",
                  Metadata={"sha256": hashlib.sha256(raw).hexdigest()})

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--case-id"); parser.add_argument("--request-id"); parser.add_argument("--scan-pending", action="store_true"); parser.add_argument("--diagnose-retrieval", action="store_true"); parser.add_argument("--validate-retrieval", action="store_true"); parser.add_argument("--question"); parser.add_argument("--profile", choices=sorted(RETRIEVAL_VALIDATION_PROFILES)); args=parser.parse_args()
    if args.validate_retrieval:
        if args.scan_pending or args.diagnose_retrieval or args.request_id:
            raise SystemExit("retrieval validation cannot process or diagnose requests")
        if not valid_case_id(args.case_id or ""):
            raise SystemExit("invalid case identifier")
        if bool((args.question or "").strip()) == bool(args.profile):
            raise SystemExit("retrieval validation requires exactly one of --question or --profile")
        question = (
            RETRIEVAL_VALIDATION_PROFILES[args.profile]
            if args.profile
            else args.question.strip()
        )
        print(json.dumps(
            validate_retrieval(client(), args.case_id, question),
            sort_keys=True,
            separators=(",", ":"),
        ))
        return
    if args.diagnose_retrieval:
        if args.scan_pending: raise SystemExit("diagnostic mode cannot scan pending requests")
        if not valid_case_id(args.case_id or ""): raise SystemExit("invalid case identifier")
        if not re.fullmatch(r"draft-[0-9]+-[0-9a-f]{12}", args.request_id or ""): raise SystemExit("invalid request identifier")
        gate_reason, gate_detail, gate_metrics = diagnose_failed_retrieval(
            client(), args.case_id, args.request_id
        )
        print(json.dumps({
            "case_id": args.case_id,
            "request_id": args.request_id,
            "status": "FAILED",
            "failure_code": "pre_generation_gate",
            "failure_stage": "evidence_retrieval",
            "gate_reason": gate_reason,
            **({"gate_detail": gate_detail} if gate_detail else {}),
            **({"gate_metrics": gate_metrics} if gate_metrics else {}),
            "model_called": False,
        }, sort_keys=True, separators=(",", ":")))
        return
    if args.scan_pending:
        if args.request_id: raise SystemExit("scan mode does not accept a request identifier")
        if args.case_id and not valid_case_id(args.case_id): raise SystemExit("invalid case identifier")
        s3=client()
        write_worker_status(s3, "RUNNING", mode="scan_pending")
        next_request=next(pending_requests(s3, args.case_id), None)
        try:
            if next_request is None:
                write_worker_status(s3, "IDLE", mode="scan_pending", outcome="no_pending")
            else:
                run_request(s3, *next_request)
                write_worker_status(s3, "IDLE", mode="scan_pending", outcome="processed",
                                    case_id=next_request[0], request_id=next_request[1])
        except Exception as exc:
            diagnostics = getattr(exc, "_legalai_failure_diagnostics", failure_diagnostics(exc, "worker_scan"))
            write_worker_status(s3, "FAILED", mode="scan_pending", outcome="failed",
                                **diagnostics,
                                **({"case_id": next_request[0], "request_id": next_request[1]}
                                   if next_request else {}))
            # run_request already persisted the request-level FAILED state and
            # safe diagnostics. A rejected request must not crash the cron
            # container; the next scheduled invocation must remain available
            # to process the next queued request.
            return
        return
    if not valid_case_id(args.case_id or ""): raise SystemExit("invalid case identifier")
    s3=client()
    if not args.request_id:
        next_request = next(pending_requests(s3, args.case_id), None)
        args.request_id = next_request[1] if next_request else ""
    if not re.fullmatch(r"draft-[0-9]+-[0-9a-f]{12}", args.request_id or ""): raise SystemExit("invalid request identifier")
    run_request(s3,args.case_id,args.request_id)

if __name__ == "__main__": main()
