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
  <img src="https://img.shields.io/badge/Session-5%20of%20N-red">
</p>

> **FOR NEXT SESSION — READ THIS FIRST**
> This README is the single source of truth. Read ✅ Completed and 🔧 Pending before touching anything.
>
> **🚀 ONE-SHOT DEPLOY** — All 4 pending steps are automated. From repo root, just run:
> ```powershell
> .\scripts\deploy-download-handler.ps1
> ```
> This creates the DDB table, deploys the Lambda, wires the API Gateway route, verifies email-sender,
> and runs a smoke test. Then do the end-to-end email link test and move to Sprint 1.5.

---

## Live URL
`https://d38ys5d9amc45p.cloudfront.net/app/index.html`

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
| `fv-email-sender` | v3 (token links) | ✅ Deployed | 512 MB | 60s |
| `fv-auth-handler` | v1 | ✅ Deployed | 256 MB | 30s |
| `vector_processor_lambda` | v2 | ✅ Deployed | 1024 MB | 305s |
| `fv-download-handler` | v1 | ❌ NOT DEPLOYED — run `scripts/deploy-download-handler.ps1` | 256 MB | 30s |

---

## DynamoDB Tables

| Table | PK | SK | Status |
|---|---|---|---|
| `DocumentMetadata` | `DOC#<uuid>` | — | ✅ Exists, 31 docs |
| `ChatSessions` | `USER#<sub>` | `SESSION#<sid>#TURN#<uuid>` | ✅ Exists |
| `UserProfiles` | `USER#<sub>` | — | ✅ Exists |
| `EmailSentLog` | `USER#<sub>` | `EMAIL#<uuid>` | ✅ Exists |
| `SecurityQuestions` | `USER#<sub>` | — | ✅ Exists |
| `DownloadTokens` | `TOKEN#<uuid>` | — | ❌ NOT CREATED — created by deploy script |

---

## 🚨 NEXT SESSION — START HERE

### Option A — One-shot script (recommended)
```powershell
# From repo root, with AWS CLI configured:
.\scripts\deploy-download-handler.ps1
```
The script handles all 4 steps: DDB table → Lambda → API Gateway route → email-sender verification → smoke test.

### Option B — Manual steps (if script fails)

#### Step 1 — Create DownloadTokens DynamoDB table
```powershell
aws dynamodb create-table `
  --table-name DownloadTokens `
  --attribute-definitions AttributeName=PK,AttributeType=S `
  --key-schema AttributeName=PK,KeyType=HASH `
  --billing-mode PAY_PER_REQUEST `
  --region eu-west-1

aws dynamodb update-time-to-live `
  --table-name DownloadTokens `
  --time-to-live-specification "Enabled=true,AttributeName=expires_epoch" `
  --region eu-west-1
```

#### Step 2 — Deploy fv-download-handler Lambda
```powershell
# Zip from lambdas/fv-download-handler/lambda_function.py
Compress-Archive -Path lambdas\fv-download-handler\lambda_function.py -DestinationPath fv-download-handler.zip

aws s3 cp fv-download-handler.zip s3://family-docs-raw/lambda-packages/ --region eu-west-1

aws lambda create-function `
  --function-name fv-download-handler `
  --runtime python3.11 `
  --role arn:aws:iam::141571819444:role/FamilyVaultLambdaRole `
  --handler lambda_function.lambda_handler `
  --code S3Bucket=family-docs-raw,S3Key=lambda-packages/fv-download-handler.zip `
  --timeout 30 --memory-size 256 `
  --environment "Variables={BUCKET=family-docs-raw,API_URL=https://1oj10740w0.execute-api.eu-west-1.amazonaws.com}" `
  --region eu-west-1

aws lambda add-permission `
  --function-name fv-download-handler `
  --statement-id apigw-invoke `
  --action lambda:InvokeFunction `
  --principal apigateway.amazonaws.com `
  --source-arn "arn:aws:execute-api:eu-west-1:141571819444:1oj10740w0/*" `
  --region eu-west-1
```

#### Step 3 — Wire /download route in API Gateway (NO auth — token is the credential)
```powershell
$LAMBDA_ARN = (aws lambda get-function-configuration `
  --function-name fv-download-handler --region eu-west-1 | ConvertFrom-Json).FunctionArn

$INTEGRATION_ID = (aws apigatewayv2 create-integration `
  --api-id 1oj10740w0 `
  --integration-type AWS_PROXY `
  --integration-uri "arn:aws:apigateway:eu-west-1:lambda:path/2015-03-31/functions/$LAMBDA_ARN/invocations" `
  --payload-format-version 2.0 `
  --region eu-west-1 | ConvertFrom-Json).IntegrationId

aws apigatewayv2 create-route `
  --api-id 1oj10740w0 `
  --route-key "GET /download" `
  --target "integrations/$INTEGRATION_ID" `
  --region eu-west-1
```

#### Step 4 — Verify fv-email-sender v3 has API_URL env var
```powershell
aws lambda get-function-configuration `
  --function-name fv-email-sender --region eu-west-1 `
  --query "Environment.Variables"
# Must include API_URL. If missing, add it:
aws lambda update-function-configuration `
  --function-name fv-email-sender `
  --environment "Variables={...,API_URL=https://1oj10740w0.execute-api.eu-west-1.amazonaws.com}" `
  --region eu-west-1
```

### After deployment — verify end-to-end
```powershell
# 1. Smoke test: expect HTTP 400 (missing token)
curl -s -o /dev/null -w "%{http_code}" https://1oj10740w0.execute-api.eu-west-1.amazonaws.com/download
# → 400

# 2. Full test: open app, send email with a doc, click the link in Gmail
# → Should 302 redirect to S3 presigned URL → file downloads
```

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
  - Short-term: last 6 turns of current session → real Anthropic conversation history
  - Long-term: last 3 past sessions → compact summary injected into Answerer system prompt
  - Planner now memory-aware (resolves follow-ups like "download that one")
  - save_turn() now stores sources for richer long-term context
- [x] fv-email-sender v3: fixed 3 bugs (model ID, JWT claims path, CORS OPTIONS)
  - **NEW**: Token-based download links in email (prevents Gmail URL mangling)
- [x] fv-download-handler v1: coded, committed, **pending deployment**
  - Email contains clean `https://api.../download?token=uuid` (Gmail-safe)
  - Lambda resolves token from DownloadTokens DDB
  - Generates fresh 2-minute presigned URL on every click
  - 302 redirect → browser downloads directly from S3
- [x] UI download link fix: iframe injection + programmatic click fallback
- [x] Email UI improvements: validation, loading state, better draft context
- [x] SES email verified, sending works (sandbox mode)
- [x] `scripts/deploy-download-handler.ps1` — one-shot deploy script committed

### Session 5 (next)
- [ ] Run `scripts/deploy-download-handler.ps1`
- [ ] Verify email download links end-to-end
- [ ] Sprint 1.5: KB user_id isolation

---

## 🔧 Remaining Pending Work

### Immediate (Session 5 start)
- [ ] **Run `.\scripts\deploy-download-handler.ps1`** (fv-download-handler + DownloadTokens DDB + API route)
- [ ] **Verify email download links** end-to-end after deployment
- [ ] **fv-fix.html** (UI with download fix) — deploy to S3 + CloudFront invalidation

### Sprint 1.5 — Multi-User KB Isolation (BEFORE adding new users)
- [ ] Add `user_id` metadata filter to Bedrock KB `retrieve()` calls in fv-chat-handler
- [ ] `vector_processor_lambda` — stamp `user_id` in S3 Vectors metadata on write
- [ ] GSI on `DocumentMetadata`: `user_id-uploaded_at-index` (replace full table scan)
- [ ] Re-backfill old email-ingested docs to include user_id in vector metadata

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
     → DDB scan ChatSessions WHERE session_id=current
     → last 6 Q+A pairs as Anthropic messages format
     → passed to Planner AND Answerer as conversation history

  2. load_long_term_memory(uid, sid, max_sessions=3)
     → DDB scan ChatSessions WHERE session_id≠current
     → last 3 sessions summarised into plain text block
     → injected into Answerer system prompt as background context

  3. plan(query, short_term_history)
     → Planner sees conversation history → correctly handles follow-ups

  4. tool_answer_question(query, chunks, push_fn, short_term, long_term)
     → Answerer sees history + long-term context + RAG chunks
     → streams answer token by token via WebSocket

  5. save_turn(uid, sid, question, answer, sources=[...])
     → stores Q+A + source filenames for future long-term recall
```

## Email Download Token Architecture (v3)

```
send_email():
  for each doc_id:
    → lookup doc in DocumentMetadata
    → _store_download_token(uid, s3_key, filename)
      → uuid token → DownloadTokens DDB (expires 24h, TTL on expires_epoch)
    → email link = https://API/download?token=uuid   ← Gmail-safe short URL

User clicks link in Gmail:
  → GET /download?token=uuid
  → fv-download-handler Lambda
  → lookup token in DownloadTokens DDB
  → validate expiry
  → generate fresh presigned URL (2-min expiry)
  → 302 redirect → browser downloads file from S3

WHY: Gmail wraps all HTML email links in links.google.com/url?q=...
This breaks AWS HMAC signatures (URL changes = signature invalid = 403).
Token URL is a plain UUID — Gmail can wrap it all it wants.
```

## Deployment Quick Reference

```powershell
# Deploy any Lambda
aws s3 cp <file>.zip s3://family-docs-raw/lambda-packages/<file>.zip --region eu-west-1
aws lambda update-function-code --function-name <n> `
  --s3-bucket family-docs-raw --s3-key lambda-packages/<file>.zip --region eu-west-1

# Deploy UI
aws s3 cp index.html s3://family-docs-ui/app/index.html --content-type text/html --region eu-west-1
aws cloudfront create-invalidation --distribution-id E6U4KTUCXF1Q3 --paths "/app/*" --region us-east-1

# Check Lambda config
aws lambda get-function-configuration --function-name <n> --region eu-west-1
```

---

*Last updated: 31 March 2026 — Session 5 prep*
*Sessions: Mar 21 (infra) + Mar 22 (chat/UI) + Mar 31 (memory + email fixes + deploy script)*
*Next: Run deploy script → verify email links → Sprint 1.5 (KB isolation)*
