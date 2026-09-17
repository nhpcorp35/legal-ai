#!/usr/bin/env python3
"""Create one bounded, cited, internal-only draft from verified B2 page indexes."""
from __future__ import annotations

import argparse, hashlib, json, os, re, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3

# Railway executes this file by path, which otherwise exposes only ``scripts``
# on sys.path. Keep the repository-root package import identical in script and
# module execution modes.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines.verified_authority_registry import match_verified_authorities

MAX_PAGES, MAX_PAGE_CHARS, MAX_CONTEXT_CHARS = 45, 2200, 75000
CASE_RE = re.compile(r"NY-[A-Za-z]+-[0-9]{6}-[0-9]{4}-[A-Za-z0-9-]{2,80}$")
CASE00_BENCHMARK_ID = "Case-00-Triborough"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
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
    r"\bplaintiff(?:[\'’]s|s)?\s+claims\s+against\b|"
    r"\boperative\s+complaint\s+and\s+answer\s+pages\b",
    re.IGNORECASE,
)
CROSS_CLAIM_ONLY_QUESTION_RE = re.compile(
    r"\b(?:(?:all|every)\s+)?counterclaims?\s+and\s+cross[ -]?claims?\b|"
    r"\bcross[ -]?claims?\s+and\s+counterclaims?\b|"
    r"\bmain action\b.*\b(?:counterclaims?|cross[ -]?claims?)\b",
    re.IGNORECASE,
)
CROSS_CLAIM_ASSERTING_PARTY_RE = re.compile(
    r"\basserted\s+by\s+(.+?)(?=,\s+the\s+parties\b|,\s+each\b|\.\s|$)",
    re.IGNORECASE,
)
PLEADING_CLAIM_TEXT_RE = re.compile(
    r"\b(?:cause of action|cross[ -]?claim|counter[ -]?claim|"
    r"negligence|breach of contract|contractual indemnification|"
    r"common[ -]?law indemnification|contribution)\b|"
    r"\blabor\s+law\s*(?:§|section|sec\.?\s*)?\s*(?:200|240|241)\b",
    re.IGNORECASE,
)
PLEADING_RELIEF_TEXT_RE = re.compile(
    r"\b(?:wherefore|prayer for relief|demands? judgment|requests? judgment|"
    r"judgment (?:be )?(?:entered|granted)|dismiss(?:al|ing)|"
    r"damages(?:,|\s+and|\s+in)|costs? and disbursements)\b",
    re.IGNORECASE,
)
THIRD_PARTY_COMPLAINT_QUESTION_RE = re.compile(
    r"\bthird[ -]?party\s+complaint\b",
    re.IGNORECASE,
)
TARGETED_THIRD_PARTY_COMPLAINT_PAGE_LIMIT = 16
TOP_ATTACK_SURFACES_MARKER = "v4.0 top attack surfaces report"
V4_PROCEDURAL_ORDER_TEXT_RE = re.compile(r"\b(?:death|deceased|substitut(?:e|ion)|representative|jurisdiction)\b", re.IGNORECASE)
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


class PreGenerationGateError(ValueError):
    """Raised when mandatory pleading coverage cannot fit before a model call."""


class EvidenceSelection(list):
    """Selected pages plus bounded retrieval-coverage metadata for the audit."""

    def __init__(self, pages, coverage):
        super().__init__(pages)
        self.coverage = coverage


def valid_case_id(value: str) -> bool:
    """Accept verified active-matter identifiers and the fixed Case-00 benchmark."""
    return value == CASE00_BENCHMARK_ID or bool(CASE_RE.fullmatch(value))


def normalized_filename(value: str) -> str:
    """Make generated archive filenames safe for procedural classification."""
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def client():
    return boto3.client("s3", endpoint_url=os.environ["B2_ENDPOINT"].rstrip("/"), region_name=os.environ["B2_REGION"], aws_access_key_id=os.environ["B2_KEY_ID"], aws_secret_access_key=os.environ["B2_APPLICATION_KEY"])

def key(case_id: str, request_id: str, name: str) -> str:
    return f"cases/{case_id}/derived/internal-drafts/{request_id}/{name}"

def put(s3, case_id, request_id, name, value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    s3.put_object(Bucket=os.environ["B2_BUCKET"], Key=key(case_id, request_id, name), Body=raw, ContentType="application/json", Metadata={"sha256": hashlib.sha256(raw).hexdigest()})

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


def evidence(s3, case_id, question):
    """Select bounded evidence with filing- and section-level pleading coverage."""
    rows=[]; terms=words(question); party_role_candidates=set()
    broad_record_question = len(BROAD_RECORD_TERMS.intersection(terms)) >= 2
    # A targeted pleading question can have only one of the broad map terms
    # (for example, "affirmative defenses"), but still requires the same
    # filing-led coverage before contract exhibits are considered.
    pleading_focused_question = bool(PLEADING_FOCUSED_QUESTION_RE.search(question))
    attack_surface_question = TOP_ATTACK_SURFACES_MARKER in question.casefold()
    cross_claim_only_question = bool(CROSS_CLAIM_ONLY_QUESTION_RE.search(question))
    main_action_only_question = (
        bool(MAIN_ACTION_ONLY_QUESTION_RE.search(question))
        and not cross_claim_only_question
    )
    # The v4 report is intentionally filing-led even though its prompt uses
    # analytical terms rather than a pleading's exact title.
    filing_led_question = broad_record_question or pleading_focused_question or attack_surface_question
    targeted_third_party_complaint = bool(
        THIRD_PARTY_COMPLAINT_QUESTION_RE.search(question)
    )
    documents={}
    for source in verified_sources(s3, case_id):
        object_key=f"cases/{case_id}/intake/source/{source}/page_records.jsonl"
        raw=s3.get_object(Bucket=os.environ["B2_BUCKET"],Key=object_key)["Body"].read().decode()
        for line in raw.splitlines():
            item=json.loads(line); text=" ".join(str(item.get("text","")).split()); filename=item.get("filename"); page=item.get("page_number")
            if not text or not isinstance(filename,str) or not isinstance(page,int) or page < 1:
                continue
            documents.setdefault((source, filename), []).append((page, text))
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
    for (source, filename), document_pages in documents.items():
        if cross_claim_party:
            document_text = " ".join(text.casefold() for _, text in document_pages)
            if cross_claim_party not in document_text:
                continue
        section_start = 1
        prior_page = None
        affirmative_defense_run_remaining = 0
        for page, text in sorted(document_pages):
            pleading_filename = normalized_filename(filename)
            merits_pleading = bool(PLEADING_FILENAME_RE.search(pleading_filename))
            if cross_claim_only_question and merits_pleading:
                # Keep this layer independent from the main complaint/answer
                # and successive third-party pleadings. The filename or the
                # operative page text must expressly identify a counterclaim,
                # cross-claim, or a reply/answer directed to one.
                filing_identity = f"{pleading_filename} {text[:700]}"
                if not re.search(
                    r"\b(?:cross[ -]?(?:claims?|c)|counter[ -]?(?:claims?|c)|"
                    r"reply\s+to\s+(?:cross[ -]?claims?|counterclaims?)|"
                    r"answer\s+to\s+(?:cross[ -]?claims?|counterclaims?))\b",
                    filing_identity,
                    re.IGNORECASE,
                ):
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
            if not attack_surface_question
            else set()
        )
        # First reserve every filing/section opening, then each expressly
        # identified cause/cross-claim/counterclaim and prayer page. This keeps
        # captions, operative labels, and requested relief together before
        # defense continuations can consume a section's allowance.
        for row in ranked:
            if row[5] and row[2] == row[7] and reserve(row) and not attack_surface_question:
                mandatory_ids.add((row[3], row[1], row[2]))
        for signal_index in (10, 11):
            for row in sorted(ranked, key=lambda item: (item[1].casefold(), item[2], -item[0])):
                section=(row[3],row[1],row[7])
                if row[5] and row[signal_index] and per_section.get(section,0) < section_page_limit(row):
                    if reserve(row) and not attack_surface_question:
                        mandatory_ids.add((row[3], row[1], row[2]))
        for row in ranked:
            section=(row[3],row[1],row[7])
            if (
                row[5] and row[8]
                and row[2] == first_defense_page.get(section)
                and per_section.get(section,0) < section_page_limit(row)
            ):
                if reserve(row) and not attack_surface_question:
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
        else:
            ordered = merits + [row for row in ranked if (row[3], row[1], row[2]) not in merit_ids]
    ordered_items = targeted_pages + [row[4] for row in ordered]
    for item in ordered_items:
        filename, page, source = item["filename"], item["page_number"], item["source_sha256"]
        item_id = (source, filename, page)
        if item_id in selected_ids:
            continue
        if total+len(item["text"])>MAX_CONTEXT_CHARS or len(selected)>=MAX_PAGES:
            continue
        selected.append(item); selected_ids.add(item_id); total+=len(item["text"])
    if not selected:
        raise ValueError("no matching verified evidence")
    missing_mandatory = mandatory_ids.difference(selected_ids)
    if missing_mandatory:
        # Never spend a model call on a pleading map that dropped a required
        # first affirmative-defense page. The bounded details stay internal.
        raise PreGenerationGateError("missing_first_affirmative_defense_page")
    selected_party_role_ids = party_role_candidates.intersection(selected_ids)
    outside_party_role_ids = party_role_candidates.difference(selected_ids)
    selected_claim_ids = {
        (source, filename, page)
        for _score, filename, page, source, _candidate, merits_pleading,
        _operational, _section_start, _defense, _continuation,
        claim_pleading, _relief_pleading in rows
        if merits_pleading and claim_pleading
    }.intersection(selected_ids)
    selected_relief_ids = {
        (source, filename, page)
        for _score, filename, page, source, _candidate, merits_pleading,
        _operational, _section_start, _defense, _continuation,
        _claim_pleading, relief_pleading in rows
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
        for label, pattern in (("caption or filing opening", r"\\b(supreme court|plaintiff|defendant)\\b"), ("causes of action or relief", r"\\b(cause of action|wherefore|prayer for relief)\\b"), ("answer or denial", r"\\b(answer|den(?:y|ies|ied))\\b"), ("affirmative defense", r"\\baffirmative\\s+defen[cs]e"), ("cross-claim or counterclaim", r"\\b(cross[ -]?claim|counter[ -]?claim)\\b"), ("third-party pleading", r"\\b(third[ -]?party|fourth[ -]?party)\\b")):
            if re.search(pattern, page["text"], re.IGNORECASE):
                entry["signals"].add(label)
    return [{"filename": item["filename"], "citations": item["citations"], "signals": sorted(item["signals"])} for item in sorted(filings.values(), key=lambda item: item["filename"].casefold())]

def authority_prompt(authorities):
    """Return verified authority content suitable for model rule analysis."""
    return [authority.as_canonical_dict() | {"sha256": authority.sha256} for authority in authorities]


def authority_audit(authorities):
    """Return bounded authority identity metadata without proposition text."""
    return [{
        key: getattr(authority, key)
        for key in ("authority_id", "citation", "title", "source_url", "issuing_body", "date", "sha256")
    } for authority in authorities]


ATTORNEY_ANSWER_SECTIONS = (
    "Legal standard",
    "Application",
    "Policy-by-policy analysis",
    "Bottom line",
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


def finding_schema(page_citation_properties, *, attorney_sections=False, litigation_map=False, max_findings=8):
    """Build the strict source-aware finding schema for either worker."""
    page_required = list(page_citation_properties)
    finding_properties = {"statement":{"type":"string","maxLength":900},"citations":{"type":"array","items":{"type":"object","additionalProperties":False,"required":page_required,"properties":page_citation_properties}},"authority_citations":{"type":"array","items":{"type":"string"}}}
    finding_required = ["statement", "citations", "authority_citations"]
    sections = ATTORNEY_ANSWER_SECTIONS if attorney_sections else LITIGATION_MAP_SECTIONS if litigation_map else ()
    if sections:
        finding_properties = {"section":{"type":"string","enum":list(sections)}, **finding_properties}
        finding_required = ["section", *finding_required]
    return {"type":"object","additionalProperties":False,"required":["summary","findings","missing_information","limitations"],"properties":{"summary":{"type":"string","maxLength":800},"findings":{"type":"array","minItems":1,"maxItems":max_findings,"items":{"type":"object","additionalProperties":False,"required":finding_required,"properties":finding_properties}},"missing_information":{"type":"array","maxItems":8,"items":{"type":"string","maxLength":300}},"limitations":{"type":"array","maxItems":4,"items":{"type":"string","maxLength":300}}}}


def generate(question, pages, coverage=None, authorities=None):
    authorities = tuple(match_verified_authorities(question) if authorities is None else authorities)
    map_question = litigation_map_question(question) and not authorities and TOP_ATTACK_SURFACES_MARKER not in question.casefold()
    schema=finding_schema({"source_sha256":{"type":"string"},"filename":{"type":"string"},"page_number":{"type":"integer","minimum":1}}, attorney_sections=bool(authorities), litigation_map=map_question, max_findings=len(LITIGATION_MAP_SECTIONS) if map_question else 8)
    instructions = "Use only the supplied verified excerpts and legal authorities. This is an internal attorney-review draft, not legal advice or a conclusion. Make no unsupported inference. Case-record facts cite only page citations in citations; legal rules cite only authority ids in authority_citations; application findings should cite both where appropriate. Do not overstate court level, controlling effect, or proposition scope. Every finding must have at least one verified source across those two arrays. Before stating that information is missing or calling something an open question, check the entire supplied record-wide excerpt set, including caption pages and operative pages from related pleadings. Never call a page range missing merely because it was not selected into the bounded retrieval slice; describe the bounded retrieval limitation instead. Use the filing map only as a navigation aid; verify every proposition against its cited pages. Treat pleaded alternatives, denials, and defenses as attributed litigation positions, not established facts or contradictions. For a question about parties, claims, defenses, or relief, return a compact litigation map, not a memo; it must be attorney-readable. The summary must be one sentence of no more than 28 words and may name only claim categories, counterclaim categories, and categories of missing material; do not include party roles, ownership, control, or other factual positions. Return at most one finding for each populated heading, in this exact order: (1) Main case; (2) counterclaims and cross-claims; (3) third-party claims. Put the exact heading in the section field. Each finding must use this one-line shape: '[expressly named parties and short roles]: [claim labels]; defenses: [short labels]; relief: [short label].' Use labels only (for example, breach, lien foreclosure, negligence, statute of limitations, payment); do not explain allegations, evidence, legal standards, or why a position may succeed. In the claims field, list only an expressly asserted cause-of-action label; do not place a plaintiff-side ownership position, party-role statement, necessary-party label, or other non-claim there. In the defenses field, list only a defense attributed to the responding party; do not place a plaintiff-side allegation, ownership position, necessary-party label, or other non-defense there. List no more than three material defense labels for each party. Collapse any additional routine defenses into the single label 'affirmative defenses'; do not enumerate waiver, estoppel, laches, unclean hands, comparative fault, or similar boilerplate separately unless one is the only material defense expressly identified in the supplied record. Omit an empty heading rather than narrating that it is empty. List only the parties named in the caption or operative pleading. Do not invent, infer, or call out an unnamed party from a missing or partial caption. List a John Doe, XYZ entity, or other placeholder only if a supplied verified pleading expressly names it. If a supplied order shows that a motion was disposed of because a party died and substitution is pending, label it a procedural disposition, not a merits decision; state only the procedural consequence shown by that order. Do not use dense narrative. End every summary, finding, missing-information item, and limitation with a complete sentence; never truncate text to fill a schema limit. When supplied pages contain both an ownership assertion and a party's nonresidence or no-control statement, present both as attributed, competing record positions with citations; do not omit either or treat either as conclusively established. Do not portray a pleading typo or general denial as case-dispositive unless a supplied court ruling makes it so. Identify missing information only when it remains unsupported after that record-wide check."
    if TOP_ATTACK_SURFACES_MARKER in question.casefold():
        instructions += " For the v4.0 Top Attack Surfaces Report, do not prepend or return a claims-map summary. If a supplied order shows a motion was disposed of because a party died and substitution is pending, identify it as a procedural disposition, not a merits decision, and state only the procedural consequence shown by that order."
        instructions += " For the v4.0 Top Attack Surfaces Report, prioritize identified pleadings, orders, sworn testimony, and party-specific exhibits over generic contract excerpts. Use a generic contract provision only where it directly conflicts with, limits, or corroborates a party-identified filing or evidence in the supplied pages. Return no more than eight findings ordered from highest to lower materiality; return fewer when fewer qualify. Start every finding with 'Rank N — [Contradiction / Credibility / Procedural weakness] —'. For every finding, use this attorney-readable sequence in the statement: (1) identify the affected party or litigation position only when expressly named in the supplied pages; (2) state the specific record proposition on each side of the tension, including the source type or filing where useful; (3) explain why the two propositions create the asserted vulnerability; and (4) state any material limit. Never use a broad label such as 'causation record' or 'notice challenge' without the particular propositions that support it. A contradiction must cite each of the two conflicting verified propositions. A credibility vulnerability must identify the person or party and the concrete inconsistency, omission, or conflict; if the record does not identify one, do not call it a credibility issue. A procedural weakness must identify the party position, pleading, order, burden, remedy, notice, timing, preservation, or posture actually shown. Do not rank a defense merely because its factual proof, operative pleading, policy, or other supporting material is absent from the supplied excerpts. It qualifies only when the supplied pages show an affirmative mismatch with a contract, order, testimony, or other identified evidence, or when a court actually addressed the position. Do not invent a weakness from silence, characterize advocacy as fact, or convert alternative pleading or a denial into a contradiction. A pleading may establish procedural posture only. Do not make a factual or credibility finding from an attorney affirmation, counsel statement, service affidavit, or a party’s characterization of an absent exhibit, deposition, report, or other evidence. When the underlying first-hand material is not among the supplied pages, identify that limitation and omit the finding rather than treating advocacy as proof."
    elif authorities:
        instructions += " For this authority-backed question, the following instructions override the earlier compact litigation-map format."
        instructions += " End the summary with a complete sentence; never truncate a sentence to fill the schema limit."
        instructions += " Produce a concise attorney answer, not a memorandum. The summary must be a two-sentence executive answer of no more than 70 words. Return no more than eight non-repetitive findings total, each no more than 110 words, using the section field in this order: Legal standard; Application; Policy-by-policy analysis; Bottom line. Use at most two findings per section. State each legal rule once; apply it by reference rather than repeating it. Distinguish primary and excess policies only where the supplied record permits. Put absent proof only in missing_information, as no more than eight short, prioritized bullets; do not repeat missing evidence in the findings or limitations. The Bottom line must give the present record-based assessment and the evidence that would most change it, without predicting an outcome unsupported by the sources."
    prompt={"question":question,"instructions":instructions,"pleading_map":pleading_map(pages),"pages":pages,"legal_authorities":authority_prompt(authorities)}
    if coverage and coverage.get("verified_pleading_inventory"):
        prompt["verified_pleading_inventory"] = coverage["verified_pleading_inventory"]
        prompt["instructions"] += " The verified_pleading_inventory is authoritative presence metadata for the complete verified corpus. A listed filing exists in the verified record even when only selected pages appear in pages. Never call a listed filing missing, absent, unavailable, not supplied, or not provided. If selected excerpts do not establish a requested detail, identify that exact detail as unresolved rather than claiming that the filing itself is missing."
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
    strict_output = litigation_map_question(question) or TOP_ATTACK_SURFACES_MARKER in question.casefold()
    if strict_output:
        text_items = [result.get("summary", ""), *[item["statement"] for item in result["findings"]], *result.get("missing_information", []), *result.get("limitations", [])]
        if any(not isinstance(item, str) or not item.strip() or INCOMPLETE_SENTENCE_RE.search(item.strip()) for item in text_items):
            raise ValueError("incomplete output")
        if any(UNSELECTED_PAGES_MISSING_RE.search(item) for item in text_items):
            raise ValueError("unverified missing-page claim")
        inventory = (coverage or {}).get("verified_pleading_inventory", [])
        present_kinds = {item.get("filing_kind") for item in inventory if isinstance(item, dict)}
        if present_kinds and any(
            PRESENT_PLEADING_MISSING_RE.search(item)
            and any(kind in item.casefold() for kind in present_kinds if isinstance(kind, str))
            for item in text_items
        ):
            raise ValueError("verified pleading called missing")
    if litigation_map_question(question) and not authorities and TOP_ATTACK_SURFACES_MARKER not in question.casefold():
        sections = [item.get("section") for item in result["findings"]]
        expected = [section for section in LITIGATION_MAP_SECTIONS if section in sections]
        if not sections or any(section not in LITIGATION_MAP_SECTIONS for section in sections) or len(sections) != len(set(sections)) or sections != expected or sections[0] != "Main case":
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
    try:
        question=read_request(s3,case_id,request_id); pages=evidence(s3,case_id,question); authorities=match_verified_authorities(question); coverage=getattr(pages,"coverage",None); result=validate(generate(question,pages,coverage,authorities),pages,authorities,question,coverage)
        # Generation may have started before cancellation.  Preserve the audit
        # trail but never publish a cancelled draft as READY.
        if request_status(s3, case_id, request_id) == "CANCELLED":
            return
        draft={"schema_version":"legalai-internal-draft.v1","case_id":case_id,"request_id":request_id,"question":question,"review_required":True,"external_communication":False,"generated_at":now(),**result}
        put(s3,case_id,request_id,"draft.json",draft)
        put(s3,case_id,request_id,"input_audit.json",{"schema_version":"legalai-internal-draft-audit.v1","case_id":case_id,"request_id":request_id,"question_sha256":hashlib.sha256(question.encode()).hexdigest(),"retrieval_citations":[{k:p[k] for k in ("source_sha256","filename","page_number")} for p in pages],"legal_authorities":authority_audit(authorities),"coverage":getattr(pages,"coverage",{}),"generated_at":now()})
        put(s3,case_id,request_id,"status.json",{"schema_version":"legalai-internal-draft-status.v1","case_id":case_id,"request_id":request_id,"status":"READY","updated_at":now()})
    except Exception as exc:
        if request_status(s3, case_id, request_id) == "CANCELLED":
            return
        code = "pre_generation_gate" if isinstance(exc, PreGenerationGateError) else exc.__class__.__name__.lower()
        if code not in {"pre_generation_gate", "valueerror", "runtimeerror", "httperror", "urlerror", "clienterror"}: code = "internal_error"
        put(s3,case_id,request_id,"status.json",{"schema_version":"legalai-internal-draft-status.v1","case_id":case_id,"request_id":request_id,"status":"FAILED","failure_code":code,"updated_at":now()})
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
    parser=argparse.ArgumentParser(); parser.add_argument("--case-id"); parser.add_argument("--request-id"); parser.add_argument("--scan-pending", action="store_true"); args=parser.parse_args()
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
        except Exception:
            write_worker_status(s3, "FAILED", mode="scan_pending", outcome="failed",
                                **({"case_id": next_request[0], "request_id": next_request[1]}
                                   if next_request else {}))
            raise
        return
    if not valid_case_id(args.case_id or ""): raise SystemExit("invalid case identifier")
    s3=client()
    if not args.request_id:
        next_request = next(pending_requests(s3, args.case_id), None)
        args.request_id = next_request[1] if next_request else ""
    if not re.fullmatch(r"draft-[0-9]+-[0-9a-f]{12}", args.request_id or ""): raise SystemExit("invalid request identifier")
    run_request(s3,args.case_id,args.request_id)

if __name__ == "__main__": main()
