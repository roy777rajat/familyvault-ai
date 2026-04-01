<!-- AWS Service Icons -->
<p align="center">
  <img src="https://img.shields.io/badge/Amazon%20Bedrock-FF9900?style=flat&logo=amazonaws&logoColor=white" alt="Amazon Bedrock">
  <img src="https://img.shields.io/badge/Amazon%20S3-569A31?style=flat&logo=amazons3&logoColor=white" alt="Amazon S3">
  <img src="https://img.shields.io/badge/AWS%20Lambda-FF9900?style=flat&logo=awslambda&logoColor=white" alt="AWS Lambda">
  <img src="https://img.shields.io/badge/Amazon%20DynamoDB-4053D6?style=flat&logo=amazondynamodb&logoColor=white" alt="DynamoDB">
  <img src="https://img.shields.io/badge/Amazon%20Cognito-FF9900?style=flat&logo=amazonaws&logoColor=white" alt="Cognito">
  <img src="https://img.shields.io/badge/API%20Gateway-FF4F8B?style=flat&logo=amazonaws&logoColor=white" alt="API Gateway">
  <img src="https://img.shields.io/badge/Amazon%20CloudFront-FF9900?style=flat&logo=amazonaws&logoColor=white" alt="CloudFront">
  <img src="https://img.shields.io/badge/Amazon%20SES-FF9900?style=flat&logo=amazonaws&logoColor=white" alt="SES">
  <img src="https://img.shields.io/badge/Amazon%20Textract-FF9900?style=flat&logo=amazonaws&logoColor=white" alt="Textract">
  <img src="https://img.shields.io/badge/S3%20Vectors-569A31?style=flat&logo=amazons3&logoColor=white" alt="S3 Vectors">
</p>

<h1 align="center">🏠 FamilyVault AI</h1>

<p align="center">
  <strong>AWS-powered personal document intelligence platform</strong><br>
  Store, search, chat, and share your family documents securely using AI
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Status-Active%20Development-brightgreen">
  <img src="https://img.shields.io/badge/Region-eu--west--1-blue">
  <img src="https://img.shields.io/badge/Runtime-Python%203.11-blue">
  <img src="https://img.shields.io/badge/UI-Vanilla%20JS%20SPA-purple">
  <img src="https://img.shields.io/badge/AI-Claude%20Haiku%204.5-orange">
  <img src="https://img.shields.io/badge/Session-6%20of%20N-red">
</p>

> **FOR NEXT SESSION — READ THIS FIRST**
> This README is the single source of truth. Read ✅ Completed and 🔧 Pending before touching anything.
>
> **Session 5 is fully complete.** All Lambda functions are deployed and working.
> Start Session 6 with **Sprint 1.5 — KB user_id isolation** (see below).

---

## Live URL
`https://d38ys5d9amc45p.cloudfront.net/app/index.html`

---

## MCP Server Setup (Claude Desktop / claude.ai)

### docker-compose.yml MCP services
```yaml
  postgres-mcp:
    image: crystaldba/postgres-mcp
    container_name: pg_mcp
    entrypoint: ["sleep", "infinity"]
    environment:
      DATABASE_URI: postgresql://pguser:pgpassword@host.docker.internal:5432/finance
    restart: unless-stopped

  neo4j-mcp:
    image: mcp/neo4j-cypher
    container_name: neo4j_mcp
    environment:
      NEO4J_URL: neo4j+s://ced92892.databases.neo4j.io
      NEO4J_USERNAME: ced92892
      NEO4J_PASSWORD: rAQJKO0VFPNgCXMVf1RERJapaa7DQgBXIiYOFhdbXAk
      NEO4J_DATABASE: ced92892
    entrypoint: ["sleep", "infinity"]
    restart: unless-stopped

  # GitHub MCP: NO sleep infinity — use docker run -i --rm pattern instead (see JSON below)
```

### Claude MCP JSON config
```json
{
  "neo4j-cypher": {
    "command": "docker",
    "args": ["exec", "-i", "neo4j_mcp", "mcp-neo4j-cypher"],
    "env": {
      "NEO4J_URL": "neo4j+s://ced92892.databases.neo4j.io",
      "NEO4J_USERNAME": "ced92892",
      "NEO4J_PASSWORD": "rAQJKO0VFPNgCXMVf1RERJapaa7DQgBXIiYOFhdbXAk",
      "NEO4J_DATABASE": "ced92892"
    }
  },
  "postgres": {
    "command": "docker",
    "args": ["exec", "-i", "pg_mcp", "postgres-mcp", "--access-mode=unrestricted"],
    "env": {
      "DATABASE_URI": "postgresql://pguser:pgpassword@host.docker.internal:5432/finance"
    }
  },
  "aws": {
    "command": "python",
    "args": ["-m", "uv", "tool", "run", "awslabs.aws-api-mcp-server@latest"],
    "env": { "AWS_REGION": "us-east-1" }
  },
  "github": {
    "command": "docker",
    "args": ["run", "-i", "--rm", "-e", "GITHUB_PERSONAL_ACCESS_TOKEN=YOUR_PAT_HERE", "ghcr.io/github/github-mcp-server"]
  }
}
```

> **Note:** GitHub MCP uses `docker run -i --rm` (spawned fresh each time). Do NOT use `sleep infinity` — the image has no shell.
> **Note:** Neo4j AuraDB free tier pauses after inactivity — resume at console.neo4j.io if DNS fails.

---

## AWS Infrastructure — All Resource IDs

| Resource | Type | ID |
|---|---|---|
| Cognito User Pool | Auth | `eu-west-1_LUZKAYGwC` |
| Cognito App Client | Auth | `5j9s5557grmvt7gbuo8nopga8o` (no secret) |
| HTTP API | API Gateway | `1oj10740w0` |
| HTTP API URL | — | `https://1oj10740w0.execute-api.eu-west-1.amazonaws.com` |
| WebSocket API | API Gateway | `4hnchd4nrk` / stage: `production` |
| WebSocket URL | — | `wss://4hnchd4nrk.execute-api.eu-west-1.amazonaws.com/production` |
| JWT Authorizer | API Gateway | `kj2taa` |
| API GW /download integration | API Gateway | `bllt1be` |
| API GW /download route | API Gateway | `u03v00v` |
| Bedrock KB | Bedrock | `PYV06IINGT` |
| Bedrock Data Source | Bedrock | `JZ13ZYCSRL` |
| Vector Index | S3 Vectors | `family-docs-index` (1024-dim, cosine) |
| CloudFront Distribution | CDN | `E6U4KTUCXF1Q3` |
| CloudFront Domain | CDN | `d38ys5d9amc45p.cloudfront.net` |
| Raw Documents Bucket | S3 | `family-docs-raw` |
| Vector Store Bucket | S3 | `family-docs-vectors` |
| UI Hosting Bucket | S3 | `family-docs-ui` |
| Lambda Execution Role | IAM | `arn:aws:iam::141571819444:role/FamilyVaultLambdaRole` |
| Root User Cognito Sub | — | `f2558464-7001-7088-8818-16f339b84fb6` |
| Root User Email | — | `roy777rajat@gmail.com` |
| AWS Account | — | `141571819444` |
| AWS Region | — | `eu-west-1` (Ireland) |

---

## Lambda Functions

| Function | Version | Status | Memory | Timeout |
|---|---|---|---|---|
| `fv-chat-handler` | v13 (memory-aware) | ✅ Deployed | 1024 MB | 300s |
| `fv-upload-handler` | v2 | ✅ Deployed | 256 MB | 30s |
| `fv-delete-handler` | v2 | ✅ Deployed | 256 MB | 60s |
| `fv-memory-handler` | v3 | ✅ Deployed | 256 MB | 30s |
| `fv-email-sender` | v3 (token links + API_URL fixed) | ✅ Deployed | 512 MB | 60s |
| `fv-auth-handler` | v1 | ✅ Deployed | 256 MB | 30s |
| `vector_processor_lambda` | v2 | ✅ Deployed | 1024 MB | 305s |
| `fv-download-handler` | v1 | ✅ Deployed (Session 5) | 256 MB | 30s |

---

## DynamoDB Tables

| Table | PK | SK | Status |
|---|---|---|---|
| `DocumentMetadata` | `DOC#<uuid>` | — | ✅ Exists, 31 docs |
| `ChatSessions` | `USER#<sub>` | `SESSION#<sid>#TURN#<uuid>` | ✅ Exists |
| `UserProfiles` | `USER#<sub>` | — | ✅ Exists |
| `EmailSentLog` | `USER#<sub>` | `EMAIL#<uuid>` | ✅ Exists |
| `SecurityQuestions` | `USER#<sub>` | — | ✅ Exists |
| `DownloadTokens` | `TOKEN#<uuid>` (actual key: `token`) | — | ✅ Exists, PAY_PER_REQUEST, TTL on `expires_epoch` |

---

## 🚨 NEXT SESSION (6) — START HERE

### What was just completed (Session 5 — Apr 1 2026)
- ✅ `fv-download-handler` Lambda deployed (Python 3.11, 256MB, 30s)
- ✅ `GET /download` route wired in API Gateway (integration `bllt1be`, route `u03v00v`, auth=NONE)
- ✅ `fv-email-sender` env var `API_URL` added (was missing — tokens couldn't build correct URLs)
- ✅ Smoke test passed: `GET /download` → 400 (missing token) — Lambda responding correctly
- ✅ End-to-end email download flow verified working
- ✅ MCP server stack fixed:
  - GitHub MCP: switched to `docker run -i --rm` (image has no shell, sleep infinity fails)
  - Neo4j MCP: healthy but AuraDB DNS issue — needs resume at console.neo4j.io
  - PostgreSQL MCP: healthy (10+ days uptime)
  - AWS + Bedrock MCP: fully verified

### Session 6 start — Sprint 1.5: KB user_id isolation
This is the **most important thing before adding any new users**.
Currently all 31 docs are visible to any authenticated user in KB search.

**Step 1 — Add user_id metadata filter to fv-chat-handler**
In `search_documents` tool, add `filter={"user_id": uid}` to Bedrock KB `retrieve()` call.

**Step 2 — Stamp user_id in vector_processor_lambda**
When indexing docs into S3 Vectors, include `user_id` in metadata payload.

**Step 3 — GSI on DocumentMetadata**
Add GSI `user_id-uploaded_at-index` to replace the full table scan in `document_list` tool.

**Step 4 — Backfill old docs**
31 existing docs need `user_id` stamped in their S3 Vectors metadata entries.

---

## ✅ Work Completed (All Sessions)

### Session 1-2 (Mar 21)
- [x] Full AWS infrastructure provisioned (Cognito, API GW, Lambda x7, DynamoDB x5, S3 x3, CloudFront, SES)
- [x] Bedrock KB with S3 Vectors backend (1024-dim, cosine)
- [x] vector_processor_lambda: Textract OCR → Titan Embed → S3 Vectors
- [x] All 31 documents indexed (stamped with user_id, status=INDEXED)
- [x] Cognito JWT auth end-to-end working

### Session 3 (Mar 22)
- [x] fv-chat-handler v12: Planner→Orchestrator→Tools→Streamer
- [x] 5-intent tool system (document_list, search_documents, download_document, answer_question, out_of_scope)
- [x] Smart document_list with keyword filter from Planner
- [x] KB semantic search: score filter + dedup + reranking
- [x] Keyword-grounded download links
- [x] Agent scratchpad streaming (collapsible panel)
- [x] UI v8: 10-screen SPA, mobile responsive, dark/light theme
- [x] Family Vault hierarchy screen with interactive SVG tree
- [x] Family hierarchy business logic + role permissions designed

### Session 4 (Mar 31)
- [x] fv-chat-handler v13: short-term + long-term memory
- [x] fv-email-sender v3: token-based download links (Gmail-safe)
- [x] fv-download-handler v1: coded and committed
- [x] UI download link fix, email UI improvements
- [x] SES verified, sending works (sandbox mode)

### Session 5 (Apr 1 2026)
- [x] MCP stack debugged and fixed (GitHub crash-loop → docker run -i --rm)
- [x] fv-download-handler deployed via AWS MCP tools
- [x] GET /download route wired in API Gateway (auth=NONE, integration bllt1be)
- [x] fv-email-sender API_URL env var added
- [x] Smoke test + end-to-end email download verified working

---

## 🔧 Remaining Pending Work

### Sprint 1.5 — Multi-User KB Isolation (BEFORE adding new users)
- [ ] Add `user_id` metadata filter to Bedrock KB `retrieve()` calls in fv-chat-handler
- [ ] `vector_processor_lambda` — stamp `user_id` in S3 Vectors metadata on write
- [ ] GSI on `DocumentMetadata`: `user_id-uploaded_at-index` (replace full table scan)
- [ ] Re-backfill old docs to include user_id in vector metadata

### Sprint 2 — Family Hierarchy Backend
- [ ] Create `FamilyTree` DynamoDB table (PK=FAMILY#id, SK=MEMBER#sub)
- [ ] Cognito Groups: `fv-admin`, `fv-parent`, `fv-child`
- [ ] `/auth/invite` + `/auth/accept-invite` endpoints in fv-auth-handler
- [ ] Visibility resolver in all Lambda queries (expand user_id to subtree)
- [ ] KB query: filter `user_id IN [visible_subs]`
- [ ] UI: Family Members invite/accept flow (screen exists, needs backend wiring)

### Sprint 3 — Guardrails
- [ ] `FamilyGuardrails` DynamoDB table
- [ ] Guardrail inheritance resolver (tighten-only logic)
- [ ] Admin UI to configure guardrails
- [ ] AWS Bedrock Guardrails native integration in fv-chat-handler

### Other
- [ ] Deduplicate documents (3x PolicyKit, 3x Passport uploaded multiple times)
- [ ] fv-auth-handler CORS headers review
- [ ] Chat history pagination (currently Limit=100 turns per scan)
- [ ] SES production access request (currently sandbox)
- [ ] fv-fix.html UI — deploy to S3 + CloudFront invalidation

---

## Known Issues & All Fixes Applied

| Issue | Root Cause | Fix Applied | Session |
|---|---|---|---|
| Chat button always disabled | `S.chatInput` cleared before `sendChat()` reads it | Pass query as param: `sendChat(val)` | 3 |
| User messages not appearing | `row-reverse` with wrong DOM order | Explicit: `[bubble, avatar]` for user messages | 3 |
| Document list blank in chat | Recursive `push()` + `streaming=true` blocking render | `clear_streaming` message type | 3 |
| All docs get download links | KB scores 0.61±0.02 — threshold useless | Keyword-grounding via Planner query keywords | 3 |
| Delete not working | fv-delete-handler missing Lambda invoke permission | Added `lambda:InvokeFunction` for API GW | 3 |
| Sidebar hamburger broken | Sidebar re-rendered on repaint, losing `sb-open` | Persistent `#app-sidebar` outside `#root` | 3 |
| Old docs had null user_id | Email ingestion before user system | Batch DynamoDB update for all 31 docs | 3 |
| JWT auth SECRET_HASH error | Old Cognito client had secret | New no-secret client `5j9s5557...` | 2 |
| Wrong Bedrock model ID | Missing EU cross-region prefix | `eu.anthropic.claude-haiku-4-5-20251001-v1:0` | 2 |
| Browser upload blocked | No CORS on S3 bucket | S3 CORS: `AllowedMethods=[GET,PUT,POST,DELETE,HEAD]` | 2 |
| Chat has no memory | save_turn() wrote to DDB but was never read back | v13: load_short_term_memory + load_long_term_memory | 4 |
| Email AI draft failing | Wrong Bedrock model ID (no `eu.` prefix) | Fixed model ID in fv-email-sender | 4 |
| Email auth failing | JWT claims at `.claims` not `.jwt.claims` | Fixed claims path in get_uid() | 4 |
| Email CORS blocked | No OPTIONS handler before auth | Added OPTIONS check at top of lambda_handler | 4 |
| Email download links broken | Gmail wraps presigned URLs → breaks HMAC signature | Token-based redirect: `/download?token=uuid` | 4 |
| GitHub MCP crash-loop | Image has no shell — sleep infinity fails with exit 1 | Use `docker run -i --rm` (no persistent container) | 5 |
| fv-email-sender tokens broken | API_URL env var missing → wrong download URLs built | Added API_URL to fv-email-sender env vars | 5 |
| AWS MCP file upload blocked | MCP workdir restriction — fileb:// outside workdir fails | Create zip in `E:\NEWTEMP\aws-api-mcp\workdir` | 5 |

---

## Architecture Overview

```
Browser → CloudFront → S3 (SPA)
Browser → API Gateway HTTP (JWT) → Lambda functions → DynamoDB / S3 / Bedrock / SES
Browser → API Gateway WebSocket → fv-chat-handler → Bedrock KB + Claude Haiku
S3 upload event → vector_processor_lambda → Textract → Titan Embed → S3 Vectors → Bedrock KB
Email click → /download?token → fv-download-handler → DDB lookup → 302 → S3 presigned URL
```

## Chat Memory Architecture (v13)

```
Every turn:
  1. load_short_term_memory(uid, sid, limit=6)
     → last 6 Q+A pairs as Anthropic messages format
     → passed to Planner AND Answerer as conversation history

  2. load_long_term_memory(uid, sid, max_sessions=3)
     → last 3 sessions summarised into plain text block
     → injected into Answerer system prompt as background context

  3. plan(query, short_term_history)
     → Planner sees conversation history → correctly handles follow-ups

  4. tool_answer_question(query, chunks, push_fn, short_term, long_term)
     → streams answer token by token via WebSocket

  5. save_turn(uid, sid, question, answer, sources=[...])
     → stores Q+A + source filenames for future long-term recall
```

## Email Download Token Architecture (v3)

```
send_email():
  for each doc_id:
    → _store_download_token(uid, s3_key, filename)
      → uuid token → DownloadTokens DDB (expires 24h, TTL on expires_epoch)
    → email link = https://API/download?token=uuid   ← Gmail-safe short URL

User clicks link in Gmail:
  → GET /download?token=uuid
  → fv-download-handler Lambda
  → lookup token in DownloadTokens DDB (Key: {PK: "TOKEN#<uuid>"})
  → validate expiry (expires_at field)
  → generate fresh presigned URL (2-min expiry)
  → 302 redirect → browser downloads file from S3
```

## Deployment Quick Reference

```powershell
# Deploy any Lambda (zip must be in E:\NEWTEMP\aws-api-mcp\workdir for AWS MCP)
Compress-Archive -Path lambda_function.py -DestinationPath fv-xyz.zip -Force
aws lambda update-function-code --function-name fv-xyz `
  --zip-file fileb://fv-xyz.zip --region eu-west-1

# Deploy UI
aws s3 cp index.html s3://family-docs-ui/app/index.html --content-type text/html --region eu-west-1
aws cloudfront create-invalidation --distribution-id E6U4KTUCXF1Q3 --paths "/app/*" --region us-east-1

# Check Lambda config
aws lambda get-function-configuration --function-name fv-xyz --region eu-west-1
```

---

*Last updated: 1 April 2026 — Session 5 complete*
*Sessions: Mar 21 (infra) + Mar 22 (chat/UI) + Mar 31 (memory+email) + Apr 1 (download handler + MCP fixes)*
*Next (Session 6): Sprint 1.5 — KB user_id isolation*
