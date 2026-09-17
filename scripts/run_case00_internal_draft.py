#!/usr/bin/env python3
"""Generate one bounded internal-only draft from the verified Case-00 corpus.

This deliberately uses a new derived prefix and never reads or alters the
fixed Q1-Q5 attorney-review packets.
"""
from __future__ import annotations

import argparse, hashlib, json, os, re, tempfile
from datetime import datetime, timezone
from pathlib import Path

import boto3
try:
    from scripts import rebuild_case00_derived as rebuild
except ModuleNotFoundError:
    import rebuild_case00_derived as rebuild
try:
    from scripts.run_verified_case_draft import (
        MAX_CONTEXT_CHARS,
        MAX_PAGE_CHARS,
        MAX_PAGES,
        PLEADING_FILENAME_RE,
        PLEADING_OPERATIONAL_TEXT_RE,
        normalized_filename,
        authority_audit,
        authority_prompt,
        finding_schema,
        match_verified_authorities,
    )
except ModuleNotFoundError:
    from run_verified_case_draft import (
        MAX_CONTEXT_CHARS,
        MAX_PAGE_CHARS,
        MAX_PAGES,
        PLEADING_FILENAME_RE,
        PLEADING_OPERATIONAL_TEXT_RE,
        normalized_filename,
        authority_audit,
        authority_prompt,
        finding_schema,
        match_verified_authorities,
    )

CASE_ID = "Case-00-Triborough"
PREFIX = f"cases/{CASE_ID}/derived/internal-drafts"
SOURCE_PREFIX = "Benchmarks/Case-00-Triborough/original/Tribrough Full Docket/"
REQUEST_RE = re.compile(r"draft-[0-9]+-[0-9a-f]{12}$")
COMPOSITE_SECTIONS = (
    "Main action",
    "Counterclaims and cross-claims",
    "Third-party claims",
    "Rank 1",
    "Rank 2",
    "Rank 3",
    "Rank 4",
    "Rank 5",
)

def s3():
    return boto3.client("s3", endpoint_url=os.environ["B2_ENDPOINT"].rstrip("/"), region_name=os.environ["B2_REGION"], aws_access_key_id=os.environ["B2_KEY_ID"], aws_secret_access_key=os.environ["B2_APPLICATION_KEY"])

def key(request_id, name): return f"{PREFIX}/{request_id}/{name}"
def now(): return datetime.now(timezone.utc).isoformat()
def put(client, request_id, name, value):
    raw=json.dumps(value,sort_keys=True,separators=(",",":" )).encode()
    client.put_object(Bucket=os.environ["B2_BUCKET"],Key=key(request_id,name),Body=raw,ContentType="application/json",Metadata={"sha256":hashlib.sha256(raw).hexdigest()})
def request_status(client, request_id):
    try:
        raw=client.get_object(Bucket=os.environ["B2_BUCKET"],Key=key(request_id,"status.json"))["Body"].read()
        value=json.loads(raw.decode())
    except Exception:
        return "QUEUED"
    status=value.get("status") if isinstance(value,dict) else None
    return status if status in {"QUEUED","RUNNING","READY","FAILED","CANCELLED"} else "FAILED"
def words(q): return {x for x in re.findall(r"[a-z0-9]{3,}",q.casefold()) if x not in {"what","with","from","that","this","about","record","verified","case"}}

def select_evidence_pages(pages, question):
    """Reserve operative pleading coverage before lexical ranking."""
    terms=words(question); candidates=[]
    for p in pages:
        text=" ".join(str(p.get("text","")).split())
        filename=p.get("source_filename"); page=p.get("page_number")
        if not text or not isinstance(filename,str) or not isinstance(page,int): continue
        score=sum(text.casefold().count(t) for t in terms)
        candidates.append((score,filename,page,{"filename":filename,"page_number":page,"text":text[:MAX_PAGE_CHARS]}))

    selected=[]; selected_ids=set(); total=0
    def reserve(item):
        nonlocal total
        item_id=(item["filename"],item["page_number"])
        if item_id in selected_ids or len(selected)>=MAX_PAGES or total+len(item["text"])>MAX_CONTEXT_CHARS:
            return
        selected.append(item); selected_ids.add(item_id); total+=len(item["text"])

    foundational=bool(re.search(
        r"\b(?:litigation|part(?:y|ies)|claims?|defenses?|relief|pleadings?|counterclaims?|cross[ -]?claims?|third[ -]?party)\b",
        question,
        re.IGNORECASE,
    ))
    if foundational:
        filings={}
        for _,filename,page,item in candidates:
            if PLEADING_FILENAME_RE.search(normalized_filename(filename)):
                filings.setdefault(filename,[]).append((page,item))
        # Reserve every pleading opening before lexical ranking so one large
        # exhibit cannot crowd out complaints, answers, or third-party filings.
        for filename in sorted(filings,key=str.casefold):
            reserve(min(filings[filename],key=lambda row:row[0])[1])
        # Pleading relief is ordinarily at the end, and OCR may not preserve a
        # reliable WHEREFORE marker. Reserve each filing's closing page before
        # collecting its operative claims and defenses.
        for filename in sorted(filings,key=str.casefold):
            reserve(max(filings[filename],key=lambda row:row[0])[1])
        # Then retain bounded operative pages for claims, defenses, and relief.
        for filename in sorted(filings,key=str.casefold):
            kept=0
            for _,item in sorted(filings[filename],key=lambda row:row[0]):
                if kept>=4: break
                if PLEADING_OPERATIONAL_TEXT_RE.search(item["text"]):
                    before=len(selected_ids); reserve(item)
                    if len(selected_ids)>before: kept+=1

    for _,_,_,item in sorted(candidates,key=lambda row:(-row[0],row[1].casefold(),row[2])):
        reserve(item)
    if not selected: raise ValueError("no verified evidence")
    return selected


def evidence(question):
    root=Path(__file__).resolve().parents[1] / "data" / "case-00-triborough"
    with tempfile.TemporaryDirectory(prefix="case00-question-") as temp:
        cfg=rebuild.B2Config.from_env(); client=rebuild.create_b2_client(cfg)
        source=rebuild.materialize_b2_prefix(SOURCE_PREFIX,Path(temp),client=client,config=cfg)
        docs=rebuild.ingest_source_directory(source,root / "nyscef_filing_inventory.json")
        pages=rebuild.build_canonical_page_records(docs)["pages"]
    return select_evidence_pages(pages, question)


def composite_schema(page_citation_properties):
    """Require three map findings followed by exactly five ranked findings."""
    page_required=list(page_citation_properties)
    finding={
        "type":"object",
        "additionalProperties":False,
        "required":["section","statement","citations","authority_citations"],
        "properties":{
            "section":{"type":"string","enum":list(COMPOSITE_SECTIONS)},
            "statement":{"type":"string","maxLength":1400},
            "citations":{"type":"array","items":{"type":"object","additionalProperties":False,"required":page_required,"properties":page_citation_properties}},
            "authority_citations":{"type":"array","items":{"type":"string"}},
        },
    }
    return {
        "type":"object",
        "additionalProperties":False,
        "required":["summary","findings","missing_information","limitations"],
        "properties":{
            "summary":{"type":"string","maxLength":500},
            "findings":{"type":"array","minItems":8,"maxItems":8,"items":finding},
            "missing_information":{"type":"array","maxItems":8,"items":{"type":"string","maxLength":300}},
            "limitations":{"type":"array","maxItems":4,"items":{"type":"string","maxLength":300}},
        },
    }

def validate(result, pages, authorities, *, composite=False):
    allowed_pages={(p["filename"],p["page_number"]) for p in pages}
    allowed_authorities={authority.authority_id for authority in authorities}
    if not isinstance(result,dict) or not isinstance(result.get("findings"),list) or not result["findings"]: raise ValueError("invalid output")
    if composite:
        if len(result["findings"]) != len(COMPOSITE_SECTIONS):
            raise ValueError("incomplete composite output")
        sections=tuple(finding.get("section") for finding in result["findings"] if isinstance(finding,dict))
        if sections != COMPOSITE_SECTIONS:
            raise ValueError("misordered composite output")
        if any(not re.search(r"[.!?)]$", finding.get("statement","").strip()) for finding in result["findings"]):
            raise ValueError("truncated composite output")
        if any(re.search(r"\bpages?\s+[0-9–—, -]+\s+(?:was|were)\s+not supplied\b", item, re.IGNORECASE) for item in result.get("missing_information",[]) if isinstance(item,str)):
            raise ValueError("bounded retrieval mislabeled as missing evidence")
    for finding in result["findings"]:
        if not isinstance(finding,dict) or not isinstance(finding.get("statement"),str) or not isinstance(finding.get("citations"),list) or not isinstance(finding.get("authority_citations"),list): raise ValueError("uncited output")
        if not finding["citations"] and not finding["authority_citations"]: raise ValueError("uncited output")
        for citation in finding["citations"]:
            if not isinstance(citation,dict) or (citation.get("filename"),citation.get("page_number")) not in allowed_pages: raise ValueError("unverified citation")
        if any(not isinstance(authority_id,str) or authority_id not in allowed_authorities for authority_id in finding["authority_citations"]):
            raise ValueError("unverified authority citation")
    return result

def run_request(client, request_id):
    """Process one Case-00 request using the canonical benchmark corpus."""
    if request_status(client, request_id) == "CANCELLED":
        return
    request=json.loads(client.get_object(Bucket=os.environ["B2_BUCKET"],Key=f"cases/{CASE_ID}/derived/draft-requests/{request_id}.json")["Body"].read())
    question=request.get("question") if isinstance(request,dict) else None
    if not isinstance(question,str) or not question.strip() or len(question)>1000: raise SystemExit("invalid request")
    put(client,request_id,"status.json",{"schema_version":"legalai-internal-draft-status.v1","case_id":CASE_ID,"request_id":request_id,"status":"RUNNING","updated_at":now()})
    try:
        pages=evidence(question)
        authorities=match_verified_authorities(question)
        foundational=bool(re.search(
            r"\b(?:litigation|part(?:y|ies)|claims?|defenses?|relief|pleadings?|counterclaims?|cross[ -]?claims?|third[ -]?party)\b",
            question,
            re.IGNORECASE,
        ))
        attack_surfaces=bool(re.search(r"\battack\s+surfaces?\b", question, re.IGNORECASE))
        composite=foundational and attack_surfaces and not authorities
        citation_properties={"filename":{"type":"string"},"page_number":{"type":"integer","minimum":1}}
        schema=composite_schema(citation_properties) if composite else finding_schema(
            citation_properties,
            attorney_sections=bool(authorities),
        )
        # Reuse the bounded model transport, with Case-00's filename/page citation schema.
        import urllib.request
        instructions="Use only supplied verified excerpts and legal authorities. Internal attorney-review draft only. Case-record facts cite only page citations in citations; legal rules cite only authority ids in authority_citations; application findings should cite both where appropriate. Do not overstate court level, controlling effect, or proposition scope. Every finding must have at least one verified source across those two arrays. Before calling information missing, check all supplied pleading openings, operative pages, and closing pages."
        if composite:
            instructions += " Return exactly eight findings in the schema's section order. Findings 1–3 are the litigation map: Main action; Counterclaims and cross-claims; Third-party claims. Each map statement must begin with its section label and identify expressly named parties and roles, short claim labels, short defense labels, and requested relief. If a category is not established by the supplied pages, say only that the bounded excerpt does not establish it; do not invent a claim and do not call corpus pages or pleadings missing. Findings 4–8 must be sectioned Rank 1 through Rank 5 and contain the five most consequential source-supported attack surfaces. Each ranked statement must distinguish verified fact, attributed party allegation, legal inference, and unresolved uncertainty where applicable, explain why the issue matters, and cite exact pages. Every statement must be a complete, concise sentence or paragraph ending in punctuation; never truncate to fill a length limit. The summary is only a short executive overview and must not contain the litigation map. The input is a bounded retrieval slice from a 102-PDF verified corpus. Never describe an unselected page as 'not supplied' or list page ranges as missing information; describe only genuinely absent evidence, or state the bounded-retrieval limitation under limitations."
        if authorities:
            instructions += " End the summary with a complete sentence; never truncate a sentence to fill the schema limit."
            instructions += " Produce a concise attorney answer, not a memorandum. The summary must be a two-sentence executive answer of no more than 70 words. Return no more than eight non-repetitive findings total, each no more than 110 words, using the section field in this order: Legal standard; Application; Policy-by-policy analysis; Bottom line. Use at most two findings per section. State each legal rule once; apply it by reference rather than repeating it. Distinguish primary and excess policies only where the supplied record permits. Put absent proof only in missing_information, as no more than eight short, prioritized bullets; do not repeat missing evidence in the findings or limitations. The Bottom line must give the present record-based assessment and the evidence that would most change it, without predicting an outcome unsupported by the sources."
        payload={"model":os.environ.get("LEGALAI_OPENAI_MODEL","gpt-5.6-sol"),"instructions":"Return only strict JSON matching the schema.","input":json.dumps({"question":question,"instructions":instructions,"pages":pages,"legal_authorities":authority_prompt(authorities)}),"text":{"format":{"type":"json_schema","name":"case00_internal_draft","strict":True,"schema":schema}}}
        req=urllib.request.Request("https://api.openai.com/v1/responses",data=json.dumps(payload).encode(),headers={"Authorization":f"Bearer {os.environ['OPENAI_API_KEY']}","Content-Type":"application/json"},method="POST")
        body=json.loads(urllib.request.urlopen(req,timeout=int(os.environ.get("LEGALAI_MODEL_TIMEOUT_SECONDS","180"))).read().decode())
        result=next(json.loads(c["text"]) for o in body.get("output",[]) for c in o.get("content",[]) if isinstance(c,dict) and isinstance(c.get("text"),str))
        validate(result,pages,authorities,composite=composite)
        if request_status(client, request_id) == "CANCELLED":
            return
        draft={"schema_version":"legalai-internal-draft.v1","case_id":CASE_ID,"request_id":request_id,"question":question,"review_required":True,"external_communication":False,"generated_at":now(),**result}
        put(client,request_id,"draft.json",draft)
        put(client,request_id,"input_audit.json",{"schema_version":"legalai-internal-draft-audit.v1","case_id":CASE_ID,"request_id":request_id,"question_sha256":hashlib.sha256(question.encode()).hexdigest(),"retrieval_citations":[{key:p[key] for key in ("filename","page_number")} for p in pages],"legal_authorities":authority_audit(authorities),"generated_at":now()})
        put(client,request_id,"status.json",{"schema_version":"legalai-internal-draft-status.v1","case_id":CASE_ID,"request_id":request_id,"status":"READY","updated_at":now()})
    except Exception as exc:
        if request_status(client, request_id) == "CANCELLED":
            return
        put(client,request_id,"status.json",{"schema_version":"legalai-internal-draft-status.v1","case_id":CASE_ID,"request_id":request_id,"status":"FAILED","failure_code":exc.__class__.__name__.lower(),"updated_at":now()}); raise

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--request-id",required=True); args=parser.parse_args()
    if not REQUEST_RE.fullmatch(args.request_id): raise SystemExit("invalid request identifier")
    run_request(s3(), args.request_id)
if __name__ == "__main__": main()
