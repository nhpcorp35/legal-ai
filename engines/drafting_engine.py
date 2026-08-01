# engines/drafting_engine.py
"""
Retrieval-grounded attorney Q&A reasoner.

Consumes canonical retrieval hits (and optional case-map / exhibit context)
and produces a structured, citation-bounded answer for attorney review.

Model calls go through the configured provider abstraction
(``resolve_model_provider`` / injectable ``model_call``). Generation is
opt-in; callers must request it explicitly.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from copy import deepcopy
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


ENGINE_VERSION = "Attorney QA Reasoner v1 — Retrieval Grounded"

# ---------------------------------------------------------------------------
# Classifications & constants
# ---------------------------------------------------------------------------

PROPOSITION_CLASSIFICATIONS = (
    "verified_record_fact",
    "party_allegation",
    "legal_position",
    "inference",
    "unknown",
)

ALLEATION_SOURCE_KINDS = frozenset(
    {
        "party_allegation",
        "allegation",
    }
)

LEGAL_POSITION_SOURCE_KINDS = frozenset(
    {
        "legal_position",
    }
)

STATUS_READY = "READY"
STATUS_NOT_READY = "NOT READY"

LEGALAI_MODEL_ENDPOINT_ENV = "LEGALAI_MODEL_ENDPOINT"
LEGALAI_MODEL_API_KEY_ENV = "LEGALAI_MODEL_API_KEY"
LEGALAI_MODEL_TIMEOUT_ENV = "LEGALAI_MODEL_TIMEOUT_SECONDS"

_POLICY_RE = re.compile(r"\b(?:POL(?:ICY)?[-\s]?)?\d{3,}[A-Z0-9-]*\b", re.I)
_DATE_RE = re.compile(
    r"\b(?:\d{1,2}/\d{1,2}/\d{2,4}|"
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},?\s+\d{4})\b",
    re.I,
)
_PARTY_LIKE_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9.&'-]+(?:\s+[A-Z][A-Za-z0-9.&'-]+){0,4}"
    r"\s+(?:LLC|Inc\.?|Corp\.?|Co\.?|Company|Ltd\.?))\b"
)


RECORD_ANALYSIS_SYSTEM_PROMPT = """You are a record-analysis assistant for New York civil litigation attorney review.

You answer ONLY from the supplied retrieval evidence packet. This workflow is record-only by default.

Hard rules:
1. Use only the provided retrieval hits, page excerpts, and optional case-map/exhibit context.
2. Do not add external statutes, case law, or doctrines unless they appear in the allowed_sources field.
3. Case-map nodes and review candidates are retrieval signals only — never independent proof.
4. Every substantive proposition must include: classification, nyscef_document_number, page_id, pdf_page, source_excerpt, confidence, rationale.
5. classification must be one of: verified_record_fact, party_allegation, legal_position, inference, unknown.
6. verified_record_fact is limited to procedural/documentary facts directly established by the cited page. Never promote party assertions or legal arguments to facts.
7. Preserve competing positions separately. Do not silently reconcile conflicts.
8. Claims of absence, completeness, chronology, conflict, or strongest evidence require an explained review_scope and must stay qualified when the retrieved record cannot establish completeness.
9. Cite only page_id / NYSCEF / pdf_page values present in the evidence packet. Quote minimally and preserve exact wording in source_excerpt.
10. Express uncertainty explicitly. Label any legal conclusion as legal_position or inference for attorney review. Do not give a final coverage conclusion unless the record and question clearly justify it.

Return a single JSON object with keys:
proposed_answer, propositions, supporting_evidence, contrary_evidence,
unresolved_questions, documents_pages_reviewed, confidence, attorney_review, review_scope.

propositions items: proposition_id, text, classification, nyscef_document_number,
page_id, pdf_page, source_excerpt, confidence, rationale, polarity
(polarity: supporting | contrary | unresolved).

attorney_review must include: requires_attorney_review (true), review_notes,
legal_conclusions_labeled, coverage_conclusion (null unless justified and qualified).
"""


ModelCall = Callable[[str, str], Any]


# ---------------------------------------------------------------------------
# Provider abstraction (generic; not vendor-parallel)
# ---------------------------------------------------------------------------


def _env_timeout_seconds(default: float = 60.0) -> float:
    raw = os.environ.get(LEGALAI_MODEL_TIMEOUT_ENV)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _http_model_call(endpoint: str, system_prompt: str, user_prompt: str) -> Any:
    """POST JSON to a configured model endpoint using stdlib only."""
    payload = {
        "system": system_prompt,
        "user": user_prompt,
        "response_format": "json",
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    api_key = os.environ.get(LEGALAI_MODEL_API_KEY_ENV)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(
        endpoint,
        data=data,
        headers=headers,
        method="POST",
    )
    timeout = _env_timeout_seconds()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def resolve_model_provider(
    model_call: Optional[ModelCall] = None,
) -> Optional[ModelCall]:
    """
    Resolve the configured model provider.

    Priority:
      1. Explicit injectable ``model_call`` (tests / host integration)
      2. ``LEGALAI_MODEL_ENDPOINT`` HTTP JSON endpoint (stdlib urllib)
      3. Unavailable (None) → caller must return structured NOT READY
    """
    if callable(model_call):
        return model_call

    endpoint = (os.environ.get(LEGALAI_MODEL_ENDPOINT_ENV) or "").strip()
    if endpoint:
        def _configured(system_prompt: str, user_prompt: str) -> Any:
            return _http_model_call(endpoint, system_prompt, user_prompt)

        return _configured
    return None


def model_provider_available(model_call: Optional[ModelCall] = None) -> bool:
    return resolve_model_provider(model_call) is not None


# ---------------------------------------------------------------------------
# Text / evidence helpers
# ---------------------------------------------------------------------------


def normalize_whitespace(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def excerpt_occurs_on_page(excerpt: Any, page_text: Any) -> bool:
    needle = normalize_whitespace(excerpt)
    hay = normalize_whitespace(page_text)
    if not needle or not hay:
        return False
    return needle in hay


def _page_lookup_from_documents(documents: Optional[Sequence[dict]]) -> Dict[str, dict]:
    lookup: Dict[str, dict] = {}
    for document in documents or []:
        if not isinstance(document, dict):
            continue
        nyscef = document.get("nyscef_document_number")
        filename = document.get("filename") or document.get("name") or ""
        doc_type = document.get("type") or document.get("document_type") or "other"
        for page in document.get("pages") or []:
            if not isinstance(page, dict):
                continue
            page_id = page.get("page_id")
            if not page_id:
                continue
            lookup[page_id] = {
                "page_id": page_id,
                "page_number": page.get("page_number"),
                "text": page.get("text") or "",
                "nyscef_document_number": nyscef,
                "filename": filename,
                "document_type": doc_type,
            }
    return lookup


def _evidence_index(retrieval_results: Sequence[dict]) -> Dict[str, dict]:
    """Index retrieval hits by page_id (first/highest-ranked wins)."""
    index: Dict[str, dict] = {}
    for hit in retrieval_results or []:
        if not isinstance(hit, dict):
            continue
        page_id = hit.get("page_id")
        if not page_id or page_id in index:
            continue
        index[page_id] = hit
    return index


def _hit_matches_citation(hit: dict, page_id, nyscef, pdf_page) -> bool:
    if not hit:
        return False
    if page_id and hit.get("page_id") != page_id:
        return False
    if nyscef is not None and hit.get("nyscef_document_number") != nyscef:
        return False
    if pdf_page is not None and hit.get("pdf_page") != pdf_page:
        return False
    return True


def _coerce_int(value) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_confidence(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number < 0:
        return 0.0
    if number > 1:
        # Allow 0-100 style scores.
        if number <= 100:
            return round(number / 100.0, 6)
        return 1.0
    return round(number, 6)


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _parse_model_payload(raw: Any) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        # Some providers wrap content.
        if "propositions" in raw or "proposed_answer" in raw:
            return raw
        for key in ("content", "answer", "result", "data", "json"):
            nested = raw.get(key)
            if isinstance(nested, dict):
                return nested
            if isinstance(nested, str):
                try:
                    parsed = json.loads(nested)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return parsed
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            # Try fenced JSON.
            match = re.search(r"\{.*\}", text, re.S)
            if not match:
                return {}
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


def build_evidence_packet(
    question: str,
    retrieval: Optional[dict],
    *,
    case_map: Optional[dict] = None,
    exhibit_context: Optional[Any] = None,
    allowed_sources: Optional[Sequence[str]] = None,
) -> dict:
    results = list((retrieval or {}).get("results") or [])
    compact_hits = []
    for hit in results:
        if not isinstance(hit, dict):
            continue
        compact_hits.append(
            {
                "result_id": hit.get("result_id"),
                "page_id": hit.get("page_id"),
                "nyscef_document_number": hit.get("nyscef_document_number"),
                "pdf_page": hit.get("pdf_page"),
                "source_filename": hit.get("source_filename"),
                "document_type": hit.get("document_type"),
                "excerpt": hit.get("excerpt"),
                "classifications": list(hit.get("classifications") or []),
                "assertion_kind": hit.get("assertion_kind"),
                "case_map_linkage": hit.get("case_map_linkage"),
                "exhibit_segment": hit.get("exhibit_segment"),
                "score": hit.get("score"),
            }
        )

    case_map_signals = None
    if isinstance(case_map, dict):
        # Provide only compact retrieval-signal summaries — not proof.
        case_map_signals = {
            "note": (
                "Case-map entries are retrieval signals only and are not "
                "independent proof."
            ),
            "validation": (case_map.get("validation") or {}),
            "counts": {
                collection: len(case_map.get(collection) or [])
                for collection in (
                    "parties",
                    "policies",
                    "claims",
                    "defenses",
                    "allegations",
                    "evidence",
                    "timeline_events",
                    "motions",
                    "court_orders",
                )
            },
        }

    return {
        "question": normalize_whitespace(question),
        "retrieval_query": (retrieval or {}).get("query"),
        "retrieval_hit_count": len(compact_hits),
        "retrieval_hits": compact_hits,
        "case_map_signals": case_map_signals,
        "exhibit_context": exhibit_context,
        "allowed_sources": list(allowed_sources or []),
        "record_only_default": True,
    }


def build_user_prompt(evidence_packet: dict) -> str:
    return (
        "Analyze the attorney question using only this evidence packet.\n"
        "Return the required JSON object and nothing else.\n\n"
        + _stable_json(evidence_packet)
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _source_flags_for_hit(hit: Optional[dict]) -> List[str]:
    if not hit:
        return []
    flags = [str(x) for x in (hit.get("classifications") or [])]
    kind = hit.get("assertion_kind")
    if kind:
        flags.append(str(kind))
    linkage = hit.get("case_map_linkage") or {}
    if linkage.get("assertion_kind"):
        flags.append(str(linkage["assertion_kind"]))
    return flags


def _looks_like_case_map_only_claim(prop: dict, hit: Optional[dict]) -> bool:
    rationale = normalize_whitespace(prop.get("rationale")).lower()
    text = normalize_whitespace(prop.get("text")).lower()
    joined = f"{rationale} {text}"
    if "case-map" in joined or "case map" in joined:
        if not hit or not hit.get("page_id"):
            return True
        # Explicit claim that case-map alone proves the point.
        if "case map alone" in joined or "case-map alone" in joined:
            return True
        if "independent proof" in joined and "case" in joined:
            return True
    # No retrieval hit but proposition claims a citation → invalid / map-only.
    if not hit:
        return True
    return False


def _detect_invented_tokens(prop_text: str, evidence_corpus: str) -> List[str]:
    invented: List[str] = []
    corpus_norm = normalize_whitespace(evidence_corpus).lower()
    if not corpus_norm:
        return invented

    for match in _DATE_RE.finditer(prop_text or ""):
        token = normalize_whitespace(match.group(0))
        if token.lower() not in corpus_norm:
            invented.append(f"date:{token}")

    for match in _POLICY_RE.finditer(prop_text or ""):
        token = normalize_whitespace(match.group(0))
        # Skip bare short numbers that are likely NYSCEF refs.
        if token.isdigit() and len(token) <= 4:
            continue
        if token.lower() not in corpus_norm:
            invented.append(f"policy_or_id:{token}")

    for match in _PARTY_LIKE_RE.finditer(prop_text or ""):
        token = normalize_whitespace(match.group(0))
        if token.lower() not in corpus_norm:
            invented.append(f"party:{token}")

    return invented


def _normalize_classification(value: Any) -> str:
    text = normalize_whitespace(value).lower().replace(" ", "_")
    aliases = {
        "verified_fact": "verified_record_fact",
        "fact": "verified_record_fact",
        "allegation": "party_allegation",
        "party_assertion": "party_allegation",
        "legal_argument": "legal_position",
        "argument": "legal_position",
        "position": "legal_position",
    }
    text = aliases.get(text, text)
    if text not in PROPOSITION_CLASSIFICATIONS:
        return "unknown"
    return text


def _documents_pages_reviewed_from_hits(hits: Sequence[dict]) -> List[dict]:
    reviewed = []
    seen = set()
    for hit in hits or []:
        if not isinstance(hit, dict):
            continue
        key = (
            hit.get("nyscef_document_number"),
            hit.get("page_id"),
            hit.get("pdf_page"),
        )
        if key in seen:
            continue
        seen.add(key)
        reviewed.append(
            {
                "nyscef_document_number": hit.get("nyscef_document_number"),
                "page_id": hit.get("page_id"),
                "pdf_page": hit.get("pdf_page"),
                "source_filename": hit.get("source_filename"),
                "document_type": hit.get("document_type"),
            }
        )
    reviewed.sort(
        key=lambda item: (
            item.get("nyscef_document_number") is None,
            item.get("nyscef_document_number")
            if item.get("nyscef_document_number") is not None
            else 10**9,
            item.get("pdf_page") or 0,
            item.get("page_id") or "",
        )
    )
    return reviewed


def _default_attorney_review(notes: str = "") -> dict:
    return {
        "requires_attorney_review": True,
        "review_notes": notes
        or (
            "Structured retrieval-grounded draft only. "
            "All legal conclusions are positions/inferences for attorney review."
        ),
        "legal_conclusions_labeled": True,
        "coverage_conclusion": None,
    }


def _empty_answer_shell(
    *,
    status: str,
    question: str,
    retrieval: Optional[dict],
    reason: str,
) -> dict:
    hits = list((retrieval or {}).get("results") or [])
    return {
        "status": status,
        "engine_version": ENGINE_VERSION,
        "question": normalize_whitespace(question),
        "proposed_answer": "",
        "propositions": [],
        "supporting_evidence": [],
        "contrary_evidence": [],
        "unresolved_questions": [],
        "documents_pages_reviewed": _documents_pages_reviewed_from_hits(hits),
        "confidence": 0.0,
        "attorney_review": _default_attorney_review(reason),
        "review_scope": {
            "retrieved_hit_count": len(hits),
            "completeness": "not_established",
            "qualification": (
                "Answer generation did not complete; retrieved evidence is "
                "returned for attorney review without a fabricated answer."
            ),
            "reason": reason,
        },
        "audit": {
            "removed_propositions": [],
            "rejection_reasons": [],
            "duplicate_proposition_ids": [],
            "provider_available": False,
            "notes": [reason],
        },
        "retrieved_evidence": hits,
    }


def validate_attorney_qa_response(
    raw_response: Any,
    *,
    question: str,
    retrieval: Optional[dict],
    documents: Optional[Sequence[dict]] = None,
    case_map: Optional[dict] = None,
) -> dict:
    """
    Deterministic post-generation validation.

    Identical structured model responses yield identical validated output.
    Unsupported propositions are removed from the attorney-facing answer and
    preserved in ``audit.removed_propositions``.
    """
    del case_map  # Case-map is never independent proof; page evidence required.
    payload = _parse_model_payload(raw_response)
    hits = list((retrieval or {}).get("results") or [])
    hit_index = _evidence_index(hits)
    page_lookup = _page_lookup_from_documents(documents)

    evidence_corpus_parts = []
    for hit in hits:
        evidence_corpus_parts.append(str(hit.get("excerpt") or ""))
        page = page_lookup.get(hit.get("page_id") or "")
        if page:
            evidence_corpus_parts.append(str(page.get("text") or ""))
    evidence_corpus = "\n".join(evidence_corpus_parts)

    raw_props = payload.get("propositions")
    if not isinstance(raw_props, list):
        raw_props = []

    kept: List[dict] = []
    removed: List[dict] = []
    rejection_reasons: List[dict] = []
    seen_ids: Dict[str, int] = {}
    duplicate_ids: List[str] = []

    # Stable iteration order: original order, then proposition_id.
    indexed_props: List[Tuple[int, dict]] = []
    for index, prop in enumerate(raw_props):
        if isinstance(prop, dict):
            indexed_props.append((index, prop))
    indexed_props.sort(
        key=lambda item: (
            item[0],
            str(item[1].get("proposition_id") or ""),
        )
    )

    for index, prop in indexed_props:
        prop_id = normalize_whitespace(prop.get("proposition_id")) or f"P{index+1:03d}"
        if prop_id in seen_ids:
            duplicate_ids.append(prop_id)
            rejection_reasons.append(
                {
                    "proposition_id": prop_id,
                    "reason": "duplicate_proposition_id",
                    "detail": f"Duplicate of earlier proposition at index {seen_ids[prop_id]}",
                }
            )
            removed.append(
                {
                    **deepcopy(prop),
                    "proposition_id": prop_id,
                    "removal_reason": "duplicate_proposition_id",
                }
            )
            continue
        seen_ids[prop_id] = index

        text = normalize_whitespace(prop.get("text"))
        classification = _normalize_classification(prop.get("classification"))
        page_id = normalize_whitespace(prop.get("page_id")) or None
        nyscef = _coerce_int(prop.get("nyscef_document_number"))
        pdf_page = _coerce_int(prop.get("pdf_page"))
        excerpt = prop.get("source_excerpt")
        if excerpt is None:
            excerpt = prop.get("excerpt")
        excerpt_text = normalize_whitespace(excerpt)
        confidence = _coerce_confidence(prop.get("confidence"), 0.0)
        rationale = normalize_whitespace(prop.get("rationale"))
        polarity = normalize_whitespace(prop.get("polarity")).lower() or "supporting"
        if polarity not in {"supporting", "contrary", "unresolved"}:
            polarity = "supporting"

        # Unknown with no citation is allowed as unresolved.
        if classification == "unknown" and not page_id and not excerpt_text:
            kept.append(
                {
                    "proposition_id": prop_id,
                    "text": text or "Unresolved on the supplied record.",
                    "classification": "unknown",
                    "nyscef_document_number": None,
                    "page_id": None,
                    "pdf_page": None,
                    "source_excerpt": "",
                    "confidence": confidence,
                    "rationale": rationale or "Not established by retrieved evidence.",
                    "polarity": "unresolved",
                }
            )
            continue

        hit = hit_index.get(page_id) if page_id else None
        if hit and not _hit_matches_citation(hit, page_id, nyscef, pdf_page):
            # Try to locate a hit that matches all three provenance fields.
            hit = None
            for candidate in hits:
                if _hit_matches_citation(candidate, page_id, nyscef, pdf_page):
                    hit = candidate
                    break

        removal_reason = None
        detail = ""

        if not page_id or nyscef is None or pdf_page is None:
            removal_reason = "missing_provenance"
            detail = "Substantive proposition requires NYSCEF, page_id, and pdf_page."
        elif page_id not in hit_index and page_id not in page_lookup:
            removal_reason = "citation_not_in_retrieval_context"
            detail = f"page_id {page_id} is not present in retrieval context."
        elif hit is None and page_id not in page_lookup:
            removal_reason = "hallucinated_citation"
            detail = "Cited page/NYSCEF/PDF page combination not in retrieval context."
        elif hit is not None and not _hit_matches_citation(hit, page_id, nyscef, pdf_page):
            removal_reason = "provenance_mismatch"
            detail = "NYSCEF / page_id / pdf_page do not match a retrieval hit."
        elif _looks_like_case_map_only_claim(prop, hit):
            removal_reason = "case_map_only_not_proof"
            detail = (
                "Case-map inferences/review candidates are retrieval signals "
                "only and cannot independently prove a proposition."
            )

        page_text = ""
        if page_id and page_id in page_lookup:
            page_text = page_lookup[page_id].get("text") or ""
        elif hit is not None:
            page_text = hit.get("excerpt") or ""

        if removal_reason is None:
            if not excerpt_text:
                removal_reason = "missing_excerpt"
                detail = "Substantive proposition requires a short source excerpt."
            elif page_text and not excerpt_occurs_on_page(excerpt_text, page_text):
                # Also accept exact match against the retrieval excerpt window.
                hit_excerpt = (hit or {}).get("excerpt") or ""
                if not excerpt_occurs_on_page(excerpt_text, hit_excerpt):
                    removal_reason = "excerpt_mismatch"
                    detail = (
                        "source_excerpt does not occur on the cited page "
                        "(whitespace-normalized)."
                    )

        if removal_reason is None and classification == "verified_record_fact":
            flags = {f.lower() for f in _source_flags_for_hit(hit)}
            if flags & ALLEATION_SOURCE_KINDS or "allegation" in flags:
                removal_reason = "allegation_to_fact_promotion"
                detail = (
                    "Party allegation cannot be promoted to verified_record_fact."
                )
            elif flags & LEGAL_POSITION_SOURCE_KINDS or "legal_position" in flags:
                removal_reason = "legal_position_to_fact_promotion"
                detail = (
                    "Legal position cannot be promoted to verified_record_fact."
                )
            elif "inference" in flags and "verified_fact" not in flags:
                # Soft: inference-tagged sources cannot become verified facts.
                removal_reason = "inference_to_fact_promotion"
                detail = "Inference-tagged source cannot become verified_record_fact."

        if removal_reason is None and text:
            invented = _detect_invented_tokens(text, evidence_corpus)
            if invented:
                removal_reason = "invented_content"
                detail = "Invented tokens not present in retrieval evidence: " + ", ".join(
                    invented[:8]
                )

        if removal_reason is None and not text:
            removal_reason = "empty_proposition"
            detail = "Proposition text is empty."

        # If citation is in page_lookup but not retrieval hits, still reject —
        # model must be constrained to supplied retrieval evidence.
        if removal_reason is None and page_id and page_id not in hit_index:
            removal_reason = "citation_not_in_retrieval_context"
            detail = f"page_id {page_id} was not returned by retrieval."

        if removal_reason is not None:
            rejection_reasons.append(
                {
                    "proposition_id": prop_id,
                    "reason": removal_reason,
                    "detail": detail,
                }
            )
            removed.append(
                {
                    **deepcopy(prop),
                    "proposition_id": prop_id,
                    "classification": classification,
                    "removal_reason": removal_reason,
                    "removal_detail": detail,
                }
            )
            continue

        # Align provenance to the authoritative hit when present.
        final_nyscef = nyscef
        final_pdf = pdf_page
        final_page_id = page_id
        if hit is not None:
            final_nyscef = hit.get("nyscef_document_number")
            final_pdf = hit.get("pdf_page")
            final_page_id = hit.get("page_id")

        kept.append(
            {
                "proposition_id": prop_id,
                "text": text,
                "classification": classification,
                "nyscef_document_number": final_nyscef,
                "page_id": final_page_id,
                "pdf_page": final_pdf,
                "source_excerpt": excerpt_text,
                "confidence": confidence,
                "rationale": rationale,
                "polarity": polarity,
            }
        )

    supporting = [p for p in kept if p.get("polarity") == "supporting"]
    contrary = [p for p in kept if p.get("polarity") == "contrary"]
    unresolved_props = [p for p in kept if p.get("polarity") == "unresolved"]

    # Merge model-provided unresolved questions with unknown props.
    unresolved_questions = []
    raw_unresolved = payload.get("unresolved_questions")
    if isinstance(raw_unresolved, list):
        for item in raw_unresolved:
            if isinstance(item, str) and normalize_whitespace(item):
                unresolved_questions.append(normalize_whitespace(item))
            elif isinstance(item, dict):
                q = normalize_whitespace(item.get("question") or item.get("text"))
                if q:
                    unresolved_questions.append(q)
    for prop in unresolved_props:
        if prop.get("text") and prop["text"] not in unresolved_questions:
            unresolved_questions.append(prop["text"])

    # Supporting / contrary evidence lists: prefer validated props, else model lists filtered.
    def _filter_evidence_list(raw_list, polarity_label):
        out = []
        if not isinstance(raw_list, list):
            return out
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            page_id = normalize_whitespace(item.get("page_id")) or None
            if page_id and page_id not in hit_index:
                continue
            out.append(
                {
                    "page_id": page_id,
                    "nyscef_document_number": _coerce_int(
                        item.get("nyscef_document_number")
                    ),
                    "pdf_page": _coerce_int(item.get("pdf_page")),
                    "excerpt": normalize_whitespace(
                        item.get("excerpt") or item.get("source_excerpt")
                    ),
                    "note": normalize_whitespace(item.get("note") or item.get("text")),
                    "polarity": polarity_label,
                }
            )
        return out

    supporting_evidence = [
        {
            "proposition_id": p["proposition_id"],
            "page_id": p["page_id"],
            "nyscef_document_number": p["nyscef_document_number"],
            "pdf_page": p["pdf_page"],
            "excerpt": p["source_excerpt"],
            "classification": p["classification"],
        }
        for p in supporting
    ] or _filter_evidence_list(payload.get("supporting_evidence"), "supporting")

    contrary_evidence = [
        {
            "proposition_id": p["proposition_id"],
            "page_id": p["page_id"],
            "nyscef_document_number": p["nyscef_document_number"],
            "pdf_page": p["pdf_page"],
            "excerpt": p["source_excerpt"],
            "classification": p["classification"],
        }
        for p in contrary
    ] or _filter_evidence_list(payload.get("contrary_evidence"), "contrary")

    reviewed = payload.get("documents_pages_reviewed")
    if not isinstance(reviewed, list) or not reviewed:
        reviewed = _documents_pages_reviewed_from_hits(hits)
    else:
        cleaned_reviewed = []
        for item in reviewed:
            if not isinstance(item, dict):
                continue
            page_id = normalize_whitespace(item.get("page_id")) or None
            if page_id and page_id not in hit_index and page_id not in page_lookup:
                continue
            cleaned_reviewed.append(
                {
                    "nyscef_document_number": _coerce_int(
                        item.get("nyscef_document_number")
                    ),
                    "page_id": page_id,
                    "pdf_page": _coerce_int(item.get("pdf_page")),
                    "source_filename": item.get("source_filename"),
                    "document_type": item.get("document_type"),
                }
            )
        reviewed = cleaned_reviewed or _documents_pages_reviewed_from_hits(hits)

    attorney_review = payload.get("attorney_review")
    if not isinstance(attorney_review, dict):
        attorney_review = _default_attorney_review()
    else:
        attorney_review = {
            "requires_attorney_review": True,
            "review_notes": normalize_whitespace(
                attorney_review.get("review_notes")
            )
            or _default_attorney_review()["review_notes"],
            "legal_conclusions_labeled": bool(
                attorney_review.get("legal_conclusions_labeled", True)
            ),
            "coverage_conclusion": attorney_review.get("coverage_conclusion"),
        }

    review_scope = payload.get("review_scope")
    if not isinstance(review_scope, dict):
        review_scope = {}
    review_scope = {
        "retrieved_hit_count": len(hits),
        "documents_pages_reviewed_count": len(reviewed),
        "completeness": review_scope.get("completeness") or "not_established",
        "qualification": normalize_whitespace(review_scope.get("qualification"))
        or (
            "Findings are limited to the supplied retrieval hits; absence or "
            "completeness is not established beyond that scope."
        ),
        "explanation": normalize_whitespace(review_scope.get("explanation")),
    }

    proposed = normalize_whitespace(payload.get("proposed_answer"))
    if not proposed and kept:
        proposed = kept[0]["text"]
    if removed and not proposed:
        proposed = (
            "No validated propositions remained after citation review; "
            "see unresolved questions and audit."
        )

    overall_confidence = _coerce_confidence(payload.get("confidence"), 0.0)
    if kept:
        overall_confidence = min(
            overall_confidence or 0.0,
            round(
                sum(p["confidence"] for p in kept) / max(len(kept), 1),
                6,
            )
            if overall_confidence == 0
            else overall_confidence,
        )

    status = STATUS_READY if kept or proposed else STATUS_NOT_READY
    if not hits and not kept:
        status = STATUS_NOT_READY

    return {
        "status": status,
        "engine_version": ENGINE_VERSION,
        "question": normalize_whitespace(question),
        "proposed_answer": proposed,
        "propositions": kept,
        "supporting_evidence": supporting_evidence,
        "contrary_evidence": contrary_evidence,
        "unresolved_questions": unresolved_questions,
        "documents_pages_reviewed": reviewed,
        "confidence": overall_confidence,
        "attorney_review": attorney_review,
        "review_scope": review_scope,
        "audit": {
            "removed_propositions": removed,
            "rejection_reasons": rejection_reasons,
            "duplicate_proposition_ids": sorted(set(duplicate_ids)),
            "provider_available": True,
            "notes": [],
            "validation_deterministic": True,
        },
        "retrieved_evidence": hits,
    }


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def answer_attorney_record_question(
    question: str,
    retrieval: Optional[dict],
    *,
    documents: Optional[Sequence[dict]] = None,
    case_map: Optional[dict] = None,
    exhibit_context: Optional[Any] = None,
    allowed_sources: Optional[Sequence[str]] = None,
    model_call: Optional[ModelCall] = None,
    system_prompt: Optional[str] = None,
) -> dict:
    """
    Produce a structured, citation-bounded attorney-review answer.

    If no model provider is available, returns structured NOT READY with the
    retrieved evidence packet (does not fabricate an answer).
    """
    question_text = normalize_whitespace(question)
    retrieval = retrieval or {"query": question_text, "results": []}

    provider = resolve_model_provider(model_call)
    if provider is None:
        result = _empty_answer_shell(
            status=STATUS_NOT_READY,
            question=question_text,
            retrieval=retrieval,
            reason=(
                "Model/provider capability unavailable. "
                "Configure LEGALAI_MODEL_ENDPOINT or pass model_call; "
                "retrieved evidence is attached for attorney review."
            ),
        )
        result["audit"]["provider_available"] = False
        return result

    evidence_packet = build_evidence_packet(
        question_text,
        retrieval,
        case_map=case_map,
        exhibit_context=exhibit_context,
        allowed_sources=allowed_sources,
    )
    user_prompt = build_user_prompt(evidence_packet)
    active_system = system_prompt or RECORD_ANALYSIS_SYSTEM_PROMPT

    try:
        raw = provider(active_system, user_prompt)
    except Exception as exc:  # noqa: BLE001 — surface as NOT READY, never fabricate
        result = _empty_answer_shell(
            status=STATUS_NOT_READY,
            question=question_text,
            retrieval=retrieval,
            reason=f"Model provider call failed: {type(exc).__name__}: {exc}",
        )
        result["audit"]["provider_available"] = True
        result["audit"]["provider_error"] = str(exc)
        return result

    validated = validate_attorney_qa_response(
        raw,
        question=question_text,
        retrieval=retrieval,
        documents=documents,
        case_map=case_map,
    )
    validated["audit"]["provider_available"] = True
    validated["evidence_packet_hit_count"] = evidence_packet["retrieval_hit_count"]
    return validated


def build_retrieval_grounded_qa(
    summary: Optional[dict],
    documents: Optional[Sequence[dict]],
    *,
    question: str,
    retrieval: Optional[dict] = None,
    case_map: Optional[dict] = None,
    exhibit_context: Optional[Any] = None,
    allowed_sources: Optional[Sequence[str]] = None,
    model_call: Optional[ModelCall] = None,
) -> dict:
    """Bridge used by matter_builder attorney-work-product orchestration."""
    del summary  # Reserved for future posture-aware prompting.
    return answer_attorney_record_question(
        question,
        retrieval,
        documents=documents,
        case_map=case_map,
        exhibit_context=exhibit_context,
        allowed_sources=allowed_sources,
        model_call=model_call,
    )
