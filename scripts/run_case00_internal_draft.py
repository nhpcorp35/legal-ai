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
from scripts import rebuild_case00_derived as rebuild
from scripts.run_verified_case_draft import MAX_CONTEXT_CHARS, MAX_PAGE_CHARS, MAX_PAGES, generate

CASE_ID = "Case-00-Triborough"
PREFIX = f"cases/{CASE_ID}/derived/internal-drafts"
SOURCE_PREFIX = "Benchmarks/Case-00-Triborough/original/Tribrough Full Docket/"
REQUEST_RE = re.compile(r"draft-[0-9]+-[0-9a-f]{12}$")

def s3():
    return boto3.client("s3", endpoint_url=os.environ["B2_ENDPOINT"].rstrip("/"), region_name=os.environ["B2_REGION"], aws_access_key_id=os.environ["B2_KEY_ID"], aws_secret_access_key=os.environ["B2_APPLICATION_KEY"])

def key(request_id, name): return f"{PREFIX}/{request_id}/{name}"
def now(): return datetime.now(timezone.utc).isoformat()
def put(client, request_id, name, value):
    raw=json.dumps(value,sort_keys=True,separators=(",",":" )).encode()
    client.put_object(Bucket=os.environ["B2_BUCKET"],Key=key(request_id,name),Body=raw,ContentType="application/json",Metadata={"sha256":hashlib.sha256(raw).hexdigest()})
def words(q): return {x for x in re.findall(r"[a-z0-9]{3,}",q.casefold()) if x not in {"what","with","from","that","this","about","record","verified","case"}}

def evidence(question):
    root=Path(__file__).resolve().parents[1] / "data" / "case-00-triborough"
    with tempfile.TemporaryDirectory(prefix="case00-question-") as temp:
        cfg=rebuild.B2Config.from_env(); client=rebuild.create_b2_client(cfg)
        source=rebuild.materialize_b2_prefix(SOURCE_PREFIX,Path(temp),client=client,config=cfg)
        docs=rebuild.ingest_source_directory(source,root / "nyscef_filing_inventory.json")
        pages=rebuild.build_canonical_page_records(docs)["pages"]
    terms=words(question); ranked=[]
    for p in pages:
        text=" ".join(str(p.get("text","")).split())
        filename=p.get("source_filename"); page=p.get("page_number")
        if not text or not isinstance(filename,str) or not isinstance(page,int): continue
        score=sum(text.casefold().count(t) for t in terms)
        ranked.append((score,filename,page,{"filename":filename,"page_number":page,"text":text[:MAX_PAGE_CHARS]}))
    selected=[]; total=0
    for _,_,_,p in sorted(ranked,key=lambda v:(-v[0],v[1].casefold(),v[2])):
        if len(selected)>=MAX_PAGES or total+len(p["text"])>MAX_CONTEXT_CHARS: continue
        selected.append(p); total+=len(p["text"])
    if not selected: raise ValueError("no verified evidence")
    return selected

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--request-id",required=True); args=parser.parse_args()
    if not REQUEST_RE.fullmatch(args.request_id): raise SystemExit("invalid request identifier")
    client=s3(); request=json.loads(client.get_object(Bucket=os.environ["B2_BUCKET"],Key=f"cases/{CASE_ID}/derived/draft-requests/{args.request_id}.json")["Body"].read())
    question=request.get("question") if isinstance(request,dict) else None
    if not isinstance(question,str) or not question.strip() or len(question)>1000: raise SystemExit("invalid request")
    put(client,args.request_id,"status.json",{"schema_version":"case00-internal-draft-status.v1","case_id":CASE_ID,"request_id":args.request_id,"status":"RUNNING","updated_at":now()})
    try:
        pages=evidence(question)
        schema={"type":"object","additionalProperties":False,"required":["summary","findings","missing_information","limitations"],"properties":{"summary":{"type":"string"},"findings":{"type":"array","minItems":1,"items":{"type":"object","additionalProperties":False,"required":["statement","citations"],"properties":{"statement":{"type":"string"},"citations":{"type":"array","minItems":1,"items":{"type":"object","additionalProperties":False,"required":["filename","page_number"],"properties":{"filename":{"type":"string"},"page_number":{"type":"integer","minimum":1}}}}}}},"missing_information":{"type":"array","items":{"type":"string"}},"limitations":{"type":"array","items":{"type":"string"}}}}
        # Reuse the bounded model transport, with Case-00's filename/page citation schema.
        import urllib.request
        payload={"model":os.environ.get("LEGALAI_OPENAI_MODEL","gpt-5.6-sol"),"instructions":"Return only strict JSON matching the schema.","input":json.dumps({"question":question,"instructions":"Use only supplied verified excerpts. Internal attorney-review draft only. Every finding must cite supplied filename and page.","pages":pages}),"text":{"format":{"type":"json_schema","name":"case00_internal_draft","strict":True,"schema":schema}}}
        req=urllib.request.Request("https://api.openai.com/v1/responses",data=json.dumps(payload).encode(),headers={"Authorization":f"Bearer {os.environ['OPENAI_API_KEY']}","Content-Type":"application/json"},method="POST")
        body=json.loads(urllib.request.urlopen(req,timeout=int(os.environ.get("LEGALAI_MODEL_TIMEOUT_SECONDS","180"))).read().decode())
        result=next(json.loads(c["text"]) for o in body.get("output",[]) for c in o.get("content",[]) if isinstance(c,dict) and isinstance(c.get("text"),str))
        allowed={(p["filename"],p["page_number"]) for p in pages}
        if not isinstance(result,dict) or not result.get("findings") or any((c.get("filename"),c.get("page_number")) not in allowed for f in result["findings"] for c in f.get("citations",[])): raise ValueError("uncited output")
        draft={"schema_version":"case00-internal-draft.v1","case_id":CASE_ID,"request_id":args.request_id,"question":question,"review_required":True,"external_communication":False,"generated_at":now(),**result}
        put(client,args.request_id,"draft.json",draft); put(client,args.request_id,"status.json",{"schema_version":"case00-internal-draft-status.v1","case_id":CASE_ID,"request_id":args.request_id,"status":"READY","updated_at":now()})
    except Exception as exc:
        put(client,args.request_id,"status.json",{"schema_version":"case00-internal-draft-status.v1","case_id":CASE_ID,"request_id":args.request_id,"status":"FAILED","failure_code":exc.__class__.__name__.lower(),"updated_at":now()}); raise
if __name__ == "__main__": main()
