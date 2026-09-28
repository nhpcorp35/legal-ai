# LegalAI production Railway map (observed 2026-09-28)

The attorney site's public domain belongs to **Legal-AI**, not to the
`legal-ai-executor` service in **LegalAI Infrastructure**. Confirm service IDs
and domains with Railway before running checks or deploying changes.

| Railway project | Production service | Public domain | Role |
| --- | --- | --- | --- |
| Legal-AI (`f579aebf-53f3-4967-9656-758f8236b647`) | Legal Case Search (`13a58daf-40de-4db8-95d0-96853f4a16de`) | `www.serverdeath.com`, `serverdeath.com`, `legal-ai-production-2b06.up.railway.app` | Attorney workspace and protected PDFs; port 8080 |
| Legal-AI | case00-review-diagnostics | none | Internal diagnostics |
| LegalAI Infrastructure (`1af7b0c8-f363-4154-89f2-cd79a6dfaf5c`) | hal-legalai-gateway | `hal-legalai-gateway-production.up.railway.app` | Gateway |
| LegalAI Infrastructure | hal-github-actions-bridge | `hal-github-actions-bridge-production.up.railway.app` | GitHub Actions Bridge |
| LegalAI Infrastructure | legal-ai-mcp | `legal-ai-mcp-production.up.railway.app` | LegalAI MCP |
| LegalAI Infrastructure | legal-ai-executor | `legal-ai-executor-production.up.railway.app` | Separate executor; **not** the attorney site |
| LegalAI Infrastructure | mission-control | `mission-control-production-76ff.up.railway.app` | Mission Control |
| LegalAI Infrastructure | mission-control-mcp | `mission-control-mcp-production.up.railway.app` | Mission Control MCP |
| LegalAI Infrastructure | internal-draft-worker, hal-bridge-oauth-redis | none | Internal services |

Both projects have a production environment. The attorney site's environment
ID is `ee3b1190-8308-47bb-88fd-9ea7ebfbf464`; Infrastructure's is
`eccbb432-342b-415b-88e3-fc083d7cfe59`. This inventory does not itself
authorize a project migration.

## Protected workspace smoke check

The `Legal Case Search` service has an optional, read-only check at
`/internal/attorney-workspace-smoke`. It is inactive unless a random
`LEGALAI_WORKSPACE_SMOKE_TOKEN` is configured on that **attorney-site service**.
An operator with the Railway connection can set that temporary variable and
send `X-Workspace-Smoke-Token` on `POST`, then poll `GET ?run_id=<returned ID>`
with the same header. Clear the variable when the check finishes. Do not put
the token, Authorization header, or HTML response in logs or a PR.

The check uses that service's existing `LEGALAI_REVIEW_ALLEN_USERNAME` and
`LEGALAI_REVIEW_ALLEN_PASSWORD` internally. It requests three fixed HTTPS GET
paths on `www.serverdeath.com`: the workspace, Rennick attorney review packet,
and Kuzmicki cited-case research. It rejects redirects; confirms HTTP 200,
HTML MIME, and stable page markers; caps the read at 2 MB. The workspace GET
has a 45-second timeout, and the two matter GETs have 20 seconds each (at most
85 seconds of request time in one run). Output contains only check names, status codes, marker names, and
failure codes. It creates no draft, review, source, or B2 write. It runs in a
background thread so the site's single web worker remains free to answer the
public URLs. A process restart loses the in-memory run result; a multi-worker
deployment may return 404 when polling a different worker. Treat that as a
check failure to investigate, not as evidence the workspace is down.

This check exercises the public authenticated route as Allen's review account;
it does not prove John's credentials or visual layout. It is not a PDF hash
check. Use the separately verified source manifest for byte and SHA-256 checks.

Development status: code and deterministic tests only; production execution
must be recorded separately after merge and deployment.
