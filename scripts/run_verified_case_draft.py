#!/usr/bin/env python3
"""Create one bounded, cited, internal-only draft from verified B2 page indexes."""
from __future__ import annotations

import argparse, hashlib, json, os, re, urllib.request
from datetime import datetime, timezone
from typing import Any

import boto3

MAX_PAGES, MAX_PAGE_CHARS, MAX_CONTEXT_CHARS = 45, 2200, 75000
CASE_RE = re.compile(r"NY-[A-Za-z]+-[0-9]{6}-[0-9]{4}-[A-Za-z0-9-]{2,80}$")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
BROAD_RECORD_TERMS = frozenset({"parties", "claims", "causes", "defenses", "relief"})
PLEADING_FILENAME_RE = re.compile(
    r"\b(?:complaint|answer|cross[ _-]?claim|counter[ _-]?claim|"
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
# Every mandatory pleading page fits within MAX_CONTEXT_CHARS (45 × 1600).
MERITS_PLEADING_PAGE_CHARS = 1600
AFFIRMATIVE_DEFENSES_RE = re.compile(r"\baffirmative\s+defen[cs]es?\b", re.IGNORECASE)
PLEADING_FOCUSED_QUESTION_RE = re.compile(
    r"\b(?:affirmative\s+defen[cs]e|answer\s+to\s+(?:a\s+)?third[ -]?party|"
    r"third[ -]?party\s+complaint|cross[ -]?claim|counter[ -]?claim)\b",
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
    return status if status in {"QUEUED", "RUNNING", "READY", "FAILED"} else "FAILED"


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
        if not CASE_RE.fullmatch(current_case_id):
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
        section_start = 1
        prior_page = None
        affirmative_defense_run_remaining = 0
        for page, text in sorted(document_pages):
            pleading_filename = normalized_filename(filename)
            merits_pleading = bool(PLEADING_FILENAME_RE.search(pleading_filename))
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
        for row in ranked:
            section=(row[3],row[1],row[7])
            if (
                row[5] and row[8]
                and row[2] == first_defense_page.get(section)
                and per_section.get(section,0) < MERITS_PLEADING_PAGES_PER_FILING
            ):
                reserve(row)
        # Then reserve additional affirmative-defense headings and immediate
        # continuation pages, subject to the unchanged global budget.
        for row in ranked:
            section=(row[3],row[1],row[7])
            if row[5] and row[8] and per_section.get(section,0) < MERITS_PLEADING_PAGES_PER_FILING:
                reserve(row)
        for row in ranked:
            section=(row[3],row[1],row[7])
            if row[5] and row[9] and per_section.get(section,0) < MERITS_PLEADING_PAGES_PER_FILING:
                reserve(row)
        # Then reserve every actual filing/section opening page.
        for row in ranked:
            if row[5] and row[2] == row[7]:
                reserve(row)
        # Then retain its operative claim, defense, and prayer pages.
        for row in ranked:
            section=(row[3],row[1],row[7])
            if row[5] and (row[6] or PLEADING_PARTY_ROLE_TEXT_RE.search(row[4]["text"])) and per_section.get(section,0) < MERITS_PLEADING_PAGES_PER_FILING:
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
    coverage = {"party_role_evidence": {"candidate_count": len(party_role_candidates), "retrieved_count": len(selected_party_role_ids), "outside_initial_slice": bool(outside_party_role_ids), "outside_initial_slice_citations": [{"source_sha256": source, "filename": filename, "page_number": page} for source, filename, page in sorted(outside_party_role_ids, key=lambda item: (item[1].casefold(), item[2], item[0]))[:12]]}}
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

def generate(question, pages, coverage=None):
    schema={"type":"object","additionalProperties":False,"required":["summary","findings","missing_information","limitations"],"properties":{"summary":{"type":"string"},"findings":{"type":"array","minItems":1,"items":{"type":"object","additionalProperties":False,"required":["statement","citations"],"properties":{"statement":{"type":"string"},"citations":{"type":"array","minItems":1,"items":{"type":"object","additionalProperties":False,"required":["source_sha256","filename","page_number"],"properties":{"source_sha256":{"type":"string"},"filename":{"type":"string"},"page_number":{"type":"integer","minimum":1}}}}}}},"missing_information":{"type":"array","items":{"type":"string"}},"limitations":{"type":"array","items":{"type":"string"}}}}
    instructions = "Use only the supplied verified excerpts. This is an internal attorney-review draft, not legal advice or a conclusion. Make no unsupported inference. Every finding must cite supplied pages exactly. Before stating that information is missing or calling something an open question, check the entire supplied record-wide excerpt set, including caption pages and operative pages from related pleadings. Use the filing map only as a navigation aid; verify every proposition against its cited pages. Treat pleaded alternatives, denials, and defenses as attributed litigation positions, not established facts or contradictions. For a question about parties, claims, defenses, or relief, return a compact litigation map, not a memo. The summary must be one sentence of no more than 28 words and may name only claim categories, counterclaim categories, and categories of missing material; do not include party roles, ownership, control, or other factual positions. Return at most one finding for each populated heading, in this exact order: (1) Main case; (2) counterclaims and cross-claims; (3) third-party claims; (4) later-party claims. Each finding must use this one-line shape: '[Heading] — [expressly named parties]: [claim labels]; defenses: [short labels]; relief: [short label].' Use labels only (for example, breach, lien foreclosure, negligence, statute of limitations, payment); do not explain allegations, evidence, legal standards, or why a position may succeed. In the claims field, list only an expressly asserted cause-of-action label; do not place a plaintiff-side ownership position, party-role statement, necessary-party label, or other non-claim there. In the defenses field, list only a defense attributed to the responding party; do not place a plaintiff-side allegation, ownership position, necessary-party label, or other non-defense there. List no more than three material defense labels for each party. Collapse any additional routine defenses into the single label 'affirmative defenses'; do not enumerate waiver, estoppel, laches, unclean hands, comparative fault, or similar boilerplate separately unless one is the only material defense expressly identified in the supplied record. Omit an empty heading rather than narrating that it is empty. List only the parties named in the caption or operative pleading. Do not invent, infer, or call out an unnamed party from a missing or partial caption. List a John Doe, XYZ entity, or other placeholder only if a supplied verified pleading expressly names it. If a supplied order shows that a motion was disposed of because a party died and substitution is pending, label it a procedural disposition, not a merits decision; state only the procedural consequence shown by that order. Do not use dense narrative. When supplied pages contain both an ownership assertion and a party's nonresidence or no-control statement, present both as attributed, competing record positions with citations; do not omit either or treat either as conclusively established. Do not portray a pleading typo or general denial as case-dispositive unless a supplied court ruling makes it so. Identify missing information only when it remains unsupported after that record-wide check."
    if TOP_ATTACK_SURFACES_MARKER in question.casefold():
        instructions += " For the v4.0 Top Attack Surfaces Report, do not prepend or return a claims-map summary. If a supplied order shows a motion was disposed of because a party died and substitution is pending, identify it as a procedural disposition, not a merits decision, and state only the procedural consequence shown by that order."
        instructions += " For the v4.0 Top Attack Surfaces Report, prioritize identified pleadings, orders, sworn testimony, and party-specific exhibits over generic contract excerpts. Use a generic contract provision only where it directly conflicts with, limits, or corroborates a party-identified filing or evidence in the supplied pages. Return no more than eight findings ordered from highest to lower materiality; return fewer when fewer qualify. Start every finding with 'Rank N — [Contradiction / Credibility / Procedural weakness] —'. For every finding, use this attorney-readable sequence in the statement: (1) identify the affected party or litigation position only when expressly named in the supplied pages; (2) state the specific record proposition on each side of the tension, including the source type or filing where useful; (3) explain why the two propositions create the asserted vulnerability; and (4) state any material limit. Never use a broad label such as 'causation record' or 'notice challenge' without the particular propositions that support it. A contradiction must cite each of the two conflicting verified propositions. A credibility vulnerability must identify the person or party and the concrete inconsistency, omission, or conflict; if the record does not identify one, do not call it a credibility issue. A procedural weakness must identify the party position, pleading, order, burden, remedy, notice, timing, preservation, or posture actually shown. Do not rank a defense merely because its factual proof, operative pleading, policy, or other supporting material is absent from the supplied excerpts. It qualifies only when the supplied pages show an affirmative mismatch with a contract, order, testimony, or other identified evidence, or when a court actually addressed the position. Do not invent a weakness from silence, characterize advocacy as fact, or convert alternative pleading or a denial into a contradiction. A pleading may establish procedural posture only. Do not make a factual or credibility finding from an attorney affirmation, counsel statement, service affidavit, or a party’s characterization of an absent exhibit, deposition, report, or other evidence. When the underlying first-hand material is not among the supplied pages, identify that limitation and omit the finding rather than treating advocacy as proof."
    prompt={"question":question,"instructions":instructions,"pleading_map":pleading_map(pages),"pages":pages}
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

def validate(result, pages):
    allowed={(p["source_sha256"],p["filename"],p["page_number"]) for p in pages}
    if not isinstance(result,dict) or not isinstance(result.get("findings"),list) or not result["findings"]: raise ValueError("invalid output")
    for finding in result["findings"]:
        if not isinstance(finding,dict) or not isinstance(finding.get("statement"),str) or not isinstance(finding.get("citations"),list) or not finding["citations"]: raise ValueError("uncited output")
        for cite in finding["citations"]:
            if not isinstance(cite,dict) or (cite.get("source_sha256"),cite.get("filename"),cite.get("page_number")) not in allowed: raise ValueError("unverified citation")
    return result

def run_request(s3, case_id, request_id):
    now=lambda: datetime.now(timezone.utc).isoformat()
    put(s3,case_id,request_id,"status.json",{"schema_version":"legalai-internal-draft-status.v1","case_id":case_id,"request_id":request_id,"status":"RUNNING","updated_at":now()})
    try:
        question=read_request(s3,case_id,request_id); pages=evidence(s3,case_id,question); result=validate(generate(question,pages,getattr(pages,"coverage",None)),pages)
        draft={"schema_version":"legalai-internal-draft.v1","case_id":case_id,"request_id":request_id,"question":question,"review_required":True,"external_communication":False,"generated_at":now(),**result}
        put(s3,case_id,request_id,"draft.json",draft)
        put(s3,case_id,request_id,"input_audit.json",{"schema_version":"legalai-internal-draft-audit.v1","case_id":case_id,"request_id":request_id,"question_sha256":hashlib.sha256(question.encode()).hexdigest(),"retrieval_citations":[{k:p[k] for k in ("source_sha256","filename","page_number")} for p in pages],"coverage":getattr(pages,"coverage",{}),"generated_at":now()})
        put(s3,case_id,request_id,"status.json",{"schema_version":"legalai-internal-draft-status.v1","case_id":case_id,"request_id":request_id,"status":"READY","updated_at":now()})
    except Exception as exc:
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
        if args.case_id and not CASE_RE.fullmatch(args.case_id): raise SystemExit("invalid case identifier")
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
    if not CASE_RE.fullmatch(args.case_id or ""): raise SystemExit("invalid case identifier")
    s3=client()
    if not args.request_id:
        next_request = next(pending_requests(s3, args.case_id), None)
        args.request_id = next_request[1] if next_request else ""
    if not re.fullmatch(r"draft-[0-9]+-[0-9a-f]{12}", args.request_id or ""): raise SystemExit("invalid request identifier")
    run_request(s3,args.case_id,args.request_id)

if __name__ == "__main__": main()
