#!/usr/bin/env python3
"""Create one bounded, cited, internal-only draft from verified B2 page indexes."""
from __future__ import annotations

import argparse, hashlib, json, os, re, urllib.request
from datetime import datetime, timezone
from typing import Any

import boto3

MAX_PAGES, MAX_PAGE_CHARS, MAX_CONTEXT_CHARS = 30, 2200, 50000
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
PLEADING_SECTION_START_RE = re.compile(
    r"\b(?:verified\s+)?answer\b(?:\s+to\s+(?:verified\s+)?"
    r"(?:(?:second|third|fourth)\s+)?(?:third[ -]?party\s+)?complaint)?",
    re.IGNORECASE,
)
MERITS_PLEADING_PAGE_LIMIT = 45
MERITS_PLEADING_PAGES_PER_FILING = 3


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


def evidence(s3, case_id, question):
    """Select bounded evidence with filing- and section-level pleading coverage."""
    rows=[]; terms=words(question)
    broad_record_question = len(BROAD_RECORD_TERMS.intersection(terms)) >= 2
    documents={}
    for source in verified_sources(s3, case_id):
        object_key=f"cases/{case_id}/intake/source/{source}/page_records.jsonl"
        raw=s3.get_object(Bucket=s3.meta.client.meta.endpoint_url if False else B2_BUCKET,Key=object_key)["Body"].read().decode()
        for line in raw.splitlines():
            item=json.loads(line); text=" ".join(str(item.get("text","")).split()); filename=item.get("filename"); page=item.get("page_number")
            if not text or not isinstance(filename,str) or not isinstance(page,int) or page < 1:
                continue
            documents.setdefault((source, filename), []).append((page, text))
    for (source, filename), document_pages in documents.items():
        section_start = 1
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
            lowered=text.casefold(); score=sum(lowered.count(term) for term in terms)
            score += 2 if any(term in filename.casefold() for term in terms) else 0
            candidate={"source_sha256":source,"filename":filename,"page_number":page,"text":text[:MAX_PAGE_CHARS]}
            coverage_score = 0
            operational_pleading = bool(PLEADING_OPERATIONAL_TEXT_RE.search(text))
            if broad_record_question and merits_pleading:
                # Retain a filing-led record map: each section's caption plus
                # claim, defense, or prayer pages.
                if page == section_start:
                    coverage_score += 8
                if operational_pleading:
                    coverage_score += 6
            if score or coverage_score:
                rows.append((
                    score + coverage_score, filename, page, source, candidate,
                    merits_pleading, operational_pleading, section_start,
                ))
    selected=[]; selected_ids=set(); total=0
    ranked = sorted(rows,key=lambda x:(-x[0],x[1].casefold(),x[2]))
    ordered = ranked
    if broad_record_question:
        merits=[]; merit_ids=set(); per_section={}
        def reserve(row):
            item_id=(row[3],row[1],row[2])
            if item_id in merit_ids or len(merits) >= MERITS_PLEADING_PAGE_LIMIT:
                return False
            merits.append(row); merit_ids.add(item_id)
            section=(row[3],row[1],row[7])
            per_section[section]=per_section.get(section,0)+1
            return True
        # First reserve every actual filing/section opening page.
        for row in ranked:
            if row[5] and row[2] == row[7]:
                reserve(row)
        # Then retain its operative claim, defense, and prayer pages.
        for row in ranked:
            section=(row[3],row[1],row[7])
            if row[5] and row[6] and per_section.get(section,0) < MERITS_PLEADING_PAGES_PER_FILING:
                reserve(row)
        ordered = merits + [row for row in ranked if (row[3], row[1], row[2]) not in merit_ids]
    for _,filename,page,source,item,*_ in ordered:
        item_id = (source, filename, page)
        if item_id in selected_ids:
            continue
        if total+len(item["text"])>MAX_CONTEXT_CHARS or len(selected)>=MAX_PAGES:
            continue
        selected.append(item); selected_ids.add(item_id); total+=len(item["text"])
    if not selected:
        raise ValueError("no matching verified evidence")
    return selected

def generate(question, pages):
    schema={"type":"object","additionalProperties":False,"required":["summary","findings","missing_information","limitations"],"properties":{"summary":{"type":"string"},"findings":{"type":"array","minItems":1,"items":{"type":"object","additionalProperties":False,"required":["statement","citations"],"properties":{"statement":{"type":"string"},"citations":{"type":"array","minItems":1,"items":{"type":"object","additionalProperties":False,"required":["source_sha256","filename","page_number"],"properties":{"source_sha256":{"type":"string"},"filename":{"type":"string"},"page_number":{"type":"integer","minimum":1}}}}}}},"missing_information":{"type":"array","items":{"type":"string"}},"limitations":{"type":"array","items":{"type":"string"}}}}
    prompt={"question":question,"instructions":"Use only the supplied verified excerpts. This is an internal attorney-review draft, not legal advice or a conclusion. Make no unsupported inference. Every finding must cite supplied pages exactly. Before stating that information is missing or calling something an open question, check the entire supplied record-wide excerpt set, including caption pages and operative pages from related pleadings. Treat pleaded alternatives, denials, and defenses as attributed litigation positions, not established facts or contradictions. For a question about parties, claims, defenses, or relief, make the summary a concise party-by-party and pleading-by-pleading map: identify the party, procedural role, pleading, opposing/target party when expressly shown, and the pleaded claim, defense, or relief; do not use dense narrative. Identify missing information only when it remains unsupported after that record-wide check.","pages":pages}
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

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--case-id",required=True); parser.add_argument("--request-id"); args=parser.parse_args()
    if not CASE_RE.fullmatch(args.case_id): raise SystemExit("invalid case identifier")
    s3=client(); now=lambda: datetime.now(timezone.utc).isoformat()
    if not args.request_id:
        keys = s3.list_objects_v2(Bucket=os.environ["B2_BUCKET"], Prefix=f"cases/{args.case_id}/derived/draft-requests/", MaxKeys=100).get("Contents", [])
        pending = [str(item.get("Key", "")).rsplit("/", 1)[-1].removesuffix(".json") for item in keys if str(item.get("Key", "")).endswith(".json")]
        args.request_id = sorted(pending)[-1] if pending else ""
    if not re.fullmatch(r"draft-[0-9]+-[0-9a-f]{12}", args.request_id or ""): raise SystemExit("invalid request identifier")
    put(s3,args.case_id,args.request_id,"status.json",{"schema_version":"legalai-internal-draft-status.v1","case_id":args.case_id,"request_id":args.request_id,"status":"RUNNING","updated_at":now()})
    try:
        question=read_request(s3,args.case_id,args.request_id); pages=evidence(s3,args.case_id,question); result=validate(generate(question,pages),pages)
        draft={"schema_version":"legalai-internal-draft.v1","case_id":args.case_id,"request_id":args.request_id,"question":question,"review_required":True,"external_communication":False,"generated_at":now(),**result}
        put(s3,args.case_id,args.request_id,"draft.json",draft)
        put(s3,args.case_id,args.request_id,"input_audit.json",{"schema_version":"legalai-internal-draft-audit.v1","case_id":args.case_id,"request_id":args.request_id,"question_sha256":hashlib.sha256(question.encode()).hexdigest(),"retrieval_citations":[{k:p[k] for k in ("source_sha256","filename","page_number")} for p in pages],"generated_at":now()})
        put(s3,args.case_id,args.request_id,"status.json",{"schema_version":"legalai-internal-draft-status.v1","case_id":args.case_id,"request_id":args.request_id,"status":"READY","updated_at":now()})
    except Exception as exc:
        # Persist only a bounded operational code, never source/model text.
        code = exc.__class__.__name__.lower()
        if code not in {"valueerror", "runtimeerror", "httperror", "urlerror", "clienterror"}:
            code = "internal_error"
        put(s3,args.case_id,args.request_id,"status.json",{"schema_version":"legalai-internal-draft-status.v1","case_id":args.case_id,"request_id":args.request_id,"status":"FAILED","failure_code":code,"updated_at":now()})
        raise

if __name__ == "__main__": main()
