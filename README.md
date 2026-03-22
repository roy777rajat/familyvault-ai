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
</p>

---

## What Is FamilyVault AI?

FamilyVault AI is a personal document vault that lets you store, search, and chat with your family documents using AI. Upload a PDF, ask questions in plain English, and get precise answers grounded in your actual documents — with secure download links on demand.

**Live URL:** `https://d38ys5d9amc45p.cloudfront.net/app/index.html`

---

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────────┐
│                        Browser / Mobile                             │
│              CloudFront → S3 (family-docs-ui/app/)                  │
│              Vanilla JS SPA — single index.html                     │
└─────────────────┬───────────────────────┬───────────────────────── ┘
                  │ HTTPS (REST)          │ WSS (WebSocket)
                  ▼                       ▼
┌─────────────────────────┐  ┌──────────────────────────────────────┐
│  API Gateway HTTP API   │  │  API Gateway WebSocket API            │
│  fv-api (1oj10740w0)    │  │  (4hnchd4nrk / stage: production)     │
│  JWT Authorizer         │  │  $connect / $disconnect / $default    │
└──────────┬──────────────┘  └─────────────────────┬────────────────┘
           │                                        │
    ┌──────▼────────────────────────────────────────▼──────────┐
    │                  AWS Lambda (Python 3.11)                 │
    │  fv-upload-handler   fv-delete-handler   fv-chat-handler  │
    │  fv-memory-handler   fv-email-sender     fv-auth-handler  │
    └─────────────┬──────────────────────┬─────────────────── --┘
                  │                      │
     ┌────────────▼──────────┐   ┌───────▼──────────────────────────┐
     │    DynamoDB           │   │        Amazon Bedrock             │
     │  DocumentMetadata     │   │  Claude Haiku 4.5 (Planner)       │
     │  ChatSessions         │   │  Claude Haiku 4.5 (Answerer)      │
     │  UserProfiles         │   │  KB: PYV06IINGT (S3 Vectors)      │
     │  EmailSentLog         │   │  Titan Embed Text v2              │
     └───────────────────────┘   └──────────────────────────────────┘
                                          │
                  ┌───────────────────────▼──────────────────────────┐
                  │           S3 Buckets                              │
                  │  family-docs-raw    — raw uploaded docs           │
                  │  family-docs-vectors — Bedrock vector store       │
                  │  family-docs-ui     — SPA hosting                 │
                  └──────────────────────────────────────────────────┘
```

---

## AWS Infrastructure — Resource Reference

| Resource | Type | ID |
|---|---|---|
| Cognito User Pool | Auth | `eu-west-1_LUZKAYGwC` |
| Cognito App Client | Auth | `5j9s5557grmvt7gbuo8nopga8o` (no secret) |
| HTTP API | API Gateway | `1oj10740w0` |
| WebSocket API | API Gateway | `4hnchd4nrk` / stage: `production` |
| JWT Authorizer | API Gateway | `kj2taa` |
| Bedrock KB | Bedrock | `PYV06IINGT` |
| Bedrock Data Source | Bedrock | `JZ13ZYCSRL` |
| Vector Index | S3 Vectors | `family-docs-index` (1024-dim, cosine) |
| CloudFront Distribution | CDN | `E6U4KTUCXF1Q3` |
| CloudFront Domain | CDN | `d38ys5d9amc45p.cloudfront.net` |
| Raw Documents Bucket | S3 | `family-docs-raw` |
| Vector Store Bucket | S3 | `family-docs-vectors` |
| UI Hosting Bucket | S3 | `family-docs-ui` |
| Lambda Role | IAM | `FamilyVaultLambdaRole` |
| Bedrock KB Role | IAM | `FamilyVaultBedrockKBRole` |
| Vector Processor Role | IAM | `vector_processor_lambda-role-gc893i7i` |
| AWS Region | — | `eu-west-1` (Ireland) |

---

## Lambda Functions

| Function | Purpose | Trigger | Memory | Timeout |
|---|---|---|---|---|
| `fv-chat-handler` | AI chat — Planner→Orchestrator→Tools | WebSocket `$default` | 1024 MB | 300s |
| `fv-upload-handler` | Presigned URL generation, doc metadata | HTTP API | 256 MB | 30s |
| `fv-delete-handler` | Cascade delete: S3 + DynamoDB + KB resync | HTTP API | 256 MB | 60s |
| `fv-memory-handler` | Chat session list, delete, long-term memory | HTTP API | 256 MB | 30s |
| `fv-email-sender` | Email draft via Claude + SES send | HTTP API | 512 MB | 60s |
| `fv-auth-handler` | Post-confirmation, profile, security questions | HTTP API + Cognito | 256 MB | 30s |
| `vector_processor_lambda` | S3 trigger → Textract OCR → S3 Vectors PutVectors | S3 Event | 1024 MB | 305s |

---

## DynamoDB Tables

| Table | PK | SK | Purpose |
|---|---|---|---|
| `DocumentMetadata` | `DOC#<uuid>` | — | Document records, user ownership, S3 key, status |
| `ChatSessions` | `USER#<sub>` | `SESSION#<sid>#TURN#<uuid>` | Chat history, Q&A turns |
| `UserProfiles` | `USER#<sub>` | — | Last login, profile, role |
| `EmailSentLog` | `USER#<sub>` | `EMAIL#<uuid>` | SES send audit trail |
| `SecurityQuestions` | `USER#<sub>` | — | Recovery questions |
| `DownloadTokens` | `TOKEN#<uuid>` | — | Secure download tokens |

---

## API Routes

### HTTP API

| Method | Path | Auth | Handler |
|---|---|---|---|
| GET | `/documents` | JWT | fv-upload-handler |
| POST | `/upload/presign` | JWT | fv-upload-handler |
| POST | `/upload/complete` | JWT | fv-upload-handler |
| GET | `/upload/status` | JWT | fv-upload-handler |
| DELETE | `/documents/{id}` | JWT | fv-delete-handler |
| GET | `/memory/sessions` | JWT | fv-memory-handler |
| DELETE | `/memory/sessions/{id}` | JWT | fv-memory-handler |
| DELETE | `/memory/all` | JWT | fv-memory-handler |
| GET | `/memory/long-term` | JWT | fv-memory-handler |
| POST | `/auth/post-confirm` | Public | fv-auth-handler |
| GET | `/auth/profile` | JWT | fv-auth-handler |
| PUT | `/auth/profile` | JWT | fv-auth-handler |
| POST | `/email/draft` | JWT | fv-email-sender |
| POST | `/email/send` | JWT | fv-email-sender |

### WebSocket API

| Route | Handler |
|---|---|
| `$connect` | fv-chat-handler |
| `$disconnect` | fv-chat-handler |
| `$default` | fv-chat-handler |

---

## Chat Architecture — Planner → Orchestrator → Tools

```
User Query
    ↓
┌────────────────────────────────────────────────────┐
│  PLANNER (Claude Haiku)                             │
│  Reads query → produces JSON execution plan        │
│  Output: [{tool, query, filter, reason}, ...]      │
└──────────────────────┬─────────────────────────────┘
                       ↓
┌────────────────────────────────────────────────────┐
│  ORCHESTRATOR                                       │
│  Executes steps in order, accumulates context      │
│                                                    │
│  Step 1: search_documents                          │
│    → Bedrock KB retrieve (8 results)               │
│    → Score filter (≥ 0.50)                         │
│    → Dedup by content hash                         │
│    → Re-rank by score desc                         │
│    → Merge chunks into context                     │
│                                                    │
│  Step 2: answer_question                           │
│    → Build RAG context from chunks                 │
│    → Claude streams answer tokens                  │
│                                                    │
│  Step 3: download_document (if requested)          │
│    → Keyword-grounded matching                     │
│    → Presigned S3 GET URLs (24h)                   │
│    → Link cards pushed to UI                       │
└────────────────────────────────────────────────────┘
                       ↓
┌────────────────────────────────────────────────────┐
│  STREAMER (WebSocket)                               │
│  token → html → links → final → scratchpad         │
└────────────────────────────────────────────────────┘
```

### 5 Intent Tools

| Tool | Trigger | Action |
|---|---|---|
| `document_list` | "list docs", "how many", filter by keyword | DynamoDB scan with optional keyword filter |
| `search_documents` | Content questions | Bedrock KB semantic search |
| `download_document` | "download", "link", "share" | Presigned S3 URLs for KB-matched docs only |
| `answer_question` | Any content query | Claude Haiku streams answer |
| `out_of_scope` | Unrelated query | Polite redirect |

---

## UI — Single Page Application

Vanilla JS SPA (zero framework) hosted on CloudFront.

### Screens

| Screen | Description |
|---|---|
| Dashboard | KPI cards, doc breakdown, recent docs, activity feed |
| My Documents | Document grid with category filters, delete |
| AI Chat | WebSocket chat with scratchpad, download cards, HTML tables |
| Upload | Drag-drop upload with pipeline progress |
| Email | AI-drafted email with SES send |
| Memory | Chat session history grouped by session |
| Activity | Notification feed |
| Profile | User profile and avatar |
| Family Vault | Family hierarchy tree with SVG (new) |
| Settings | App configuration |

### WebSocket Message Types

| Type | Description |
|---|---|
| `token` | Streaming text token |
| `html` | HTML table (document list) |
| `links` | Download link cards |
| `final` | End of response with scored sources |
| `status` | Status indicator text |
| `scratchpad` | Agent thinking stream |
| `clear_streaming` | Stop typing indicator |
| `error` | Error message |

---

## Document Processing Pipeline

```
Email → SES → email_ingestor Lambda → S3 (family-docs-raw)
    → S3 trigger → vector_processor_lambda
    → Textract OCR → chunk (1000 chars, 200 overlap)
    → Titan Embed Text v2 → 1024-dim embeddings
    → S3 Vectors PutVectors (family-docs-index)
    → DynamoDB status = INDEXED

Direct Upload (browser)
    → POST /upload/presign → Lambda → DynamoDB (PENDING) + presigned URL
    → Browser PUT directly to S3 (no Lambda bottleneck)
    → POST /upload/complete → DynamoDB (UPLOADED_PROCESSING)
    → S3 trigger → same vector pipeline above
```

---

## Family Hierarchy System (Designed — Sprint 2)

```
FamilyVault Account
├── 👑 Admin (Rajat Roy)       — full control, sees all nodes
│   ├── 🧑 Parent (Anindita)  — manages children, sees child docs
│   └── 🧒 Child (Aishiki)    — own vault only
└── 👤 Guest                   — read-only chat access
```

**Rule:** Parents see downward. Children never see upward. Admin sees all.

### Planned DynamoDB Table: `FamilyTree`

```
PK: FAMILY#<family_id>
SK: MEMBER#<user_sub>
Attributes:
  role:       admin | parent | child | guest
  parent_sub: <user_sub> or null (root)
  can_see:    [<child_sub_1>, <child_sub_2>]
  invited_by: <sub>
  created_at: ISO datetime
```

### Role Permissions Matrix

| Permission | Admin | Parent | Child | Guest |
|---|:---:|:---:|:---:|:---:|
| Upload Documents | ✓ | ✓ | ✓ | — |
| Delete Documents | ✓ | ✓ | — | — |
| Chat with AI | ✓ | ✓ | ✓ | ✓ |
| Download Links | ✓ | ✓ | ✓ | — |
| View Child Docs | ✓ | ✓ | — | — |
| Invite Members | ✓ | ✓ | — | — |
| Set Guardrails | ✓ | — | — | — |
| Change Roles | ✓ | — | — | — |

---

## Guardrails Framework (Sprint 3)

Admin sets system-wide rules. Parents can tighten but never loosen. Children inherit.

| Guardrail | Default | Scope |
|---|---|---|
| Max Doc Size | 10 MB | Admin sets |
| Allowed File Types | PDF, DOCX, JPG | Admin sets |
| Max Docs / User | 500 | Admin sets |
| Chat History Retention | 90 days | Admin sets |
| AI Content Filter | Standard | Admin sets |
| Download Link Expiry | 24 hours | Admin sets |
| Bedrock Guardrail ARN | Coming Soon | Admin sets |

---

## Current State

| Field | Value |
|---|---|
| Root User | Rajat Roy (`roy777rajat@gmail.com`) |
| Cognito Sub | `f2558464-7001-7088-8818-16f339b84fb6` |
| Documents Indexed | 31 |
| Vector Chunks | 50+ |
| Active Lambda Version | fv-chat-v12 |
| Active UI Version | fv-v8 |
| Sessions Built | 3 (Mar 21–22, 2026) |

---

## ✅ Work Completed

### Infrastructure
- [x] Cognito User Pool + App Client (no secret, JWT)
- [x] API Gateway HTTP API — 22 routes, JWT authorizer, CORS
- [x] API Gateway WebSocket API — 3 routes, production stage
- [x] 6 Lambda functions deployed (Python 3.11)
- [x] vector_processor_lambda v2 with S3 Vectors PutVectors
- [x] Bedrock KB (PYV06IINGT) with S3 Vectors backend, 50+ chunks
- [x] CloudFront + OAC + custom SPA error routing
- [x] S3 CORS on family-docs-raw for browser direct upload
- [x] All 31 documents stamped with `user_id` and `status=INDEXED`
- [x] Lambda invoke permissions for all API Gateway routes

### Chat System
- [x] WebSocket streaming architecture (token-by-token)
- [x] Planner → Orchestrator → Tools (v12 — current)
- [x] 5-intent system: document_list, search_documents, download_document, answer_question, out_of_scope
- [x] Smart `document_list` with keyword filter passed from Planner
- [x] KB semantic search: score filter + dedup + reranking
- [x] Keyword-grounded download links (not score-based — KB scores cluster at 0.61±0.02)
- [x] Agent scratchpad streaming (collapsible "Agent Thinking" panel)
- [x] HTML table for document list in chat (date desc, teal styled)
- [x] Relevance scores shown in source chips `filename (0.62)`
- [x] Presigned S3 GET URLs (24h expiry, attachment disposition)

### UI
- [x] 10-screen Vanilla JS SPA
- [x] Mobile responsive — hamburger sidebar, persistent outside `#root`
- [x] Dark / light theme toggle
- [x] WebSocket connect/disconnect/status pill
- [x] Download link cards in chat (teal, clickable)
- [x] HTML table rendering in chat
- [x] Agent scratchpad panel (collapsible, live streaming)
- [x] Family Vault hierarchy screen with interactive SVG tree
- [x] Drag-drop upload with 3-step pipeline progress
- [x] Chat history (memory) screen with session grouping

### Documents
- [x] 31 documents indexed across all categories
- [x] Category auto-detection: Identity, Academic, Employment, Financial, Insurance, Other

---

## 🔧 Pending Work

### Sprint 1.5 — Multi-User Isolation (High Priority — Before New Users)

- [ ] Add `user_id` metadata filter to Bedrock KB `retrieve()` calls
- [ ] `vector_processor_lambda` — stamp `user_id` in S3 Vectors metadata on write
- [ ] GSI on `DocumentMetadata`: `user_id-uploaded_at-index` (replace full table scan)
- [ ] Migrate old email-ingested S3 keys from `year=2026/...` to `user=<sub>/year=...`

### Sprint 2 — Family Hierarchy

- [ ] Create `FamilyTree` DynamoDB table
- [ ] Create Cognito Groups: `fv-admin`, `fv-parent`, `fv-child`
- [ ] `fv-auth-handler` — `/auth/invite` and `/auth/accept-invite` endpoints
- [ ] Visibility resolver: expand `user_id` to family subtree in all Lambda queries
- [ ] KB query: filter to `user_id IN [visible_subs]`
- [ ] UI — Family Members invite/accept flow (backend wiring of existing Family screen)

### Sprint 3 — Guardrails

- [ ] Create `FamilyGuardrails` DynamoDB table
- [ ] Guardrail inheritance resolver (tighten-only logic)
- [ ] Guardrail middleware in every Lambda (upload size check, type check, etc.)
- [ ] Admin UI to configure guardrails
- [ ] AWS Bedrock Guardrails native integration in fv-chat-handler

### Other Fixes

- [ ] Deduplicate documents (same file uploaded multiple times — 3x PolicyKit, 3x Passport)
- [ ] `fv-auth-handler` — review and add CORS headers
- [ ] Chat history pagination (currently `Limit=100` turns)
- [ ] Email sender — attach actual S3 files to outgoing emails
- [ ] Deploy `fv-chat-v12` and `fv-v8.html` (in this repo, not yet live)

---

## Known Issues & Fixes Applied

| Issue | Root Cause | Fix |
|---|---|---|
| Chat button always disabled | `S.chatInput` cleared before `sendChat()` reads it | Pass query as param: `sendChat(val)` |
| User messages not appearing | `row-reverse` with wrong DOM order | Explicit: `[bubble, avatar]` for user messages |
| Document list blank in chat | Recursive `push()` call + `streaming=true` blocking render | Clean `push()`, `clear_streaming` message, `S.streaming=false` on html |
| All docs get download links | KB scores 0.61±0.02 — threshold useless | Keyword-grounding via Planner search query keywords |
| Delete not working | fv-delete-handler had no Lambda invoke permission | Added `lambda:InvokeFunction` for API Gateway |
| Sidebar hamburger not clickable | Sidebar re-rendered on repaint, losing `sb-open` class | Persistent `#app-sidebar` div outside `#root` |
| Old docs had null user_id | Email ingestion before user system | Stamped all 31 docs via DynamoDB batch update |
| JWT auth SECRET_HASH error | Old Cognito client had secret | New no-secret client `5j9s5557...` |
| Wrong Bedrock model ID | Missing EU cross-region prefix | `eu.anthropic.claude-haiku-4-5-20251001-v1:0` |
| Browser upload blocked | No CORS on `family-docs-raw` S3 bucket | S3 CORS: `AllowedMethods=[GET,PUT,POST,DELETE,HEAD]` |

---

## Deployment Quick Reference

```powershell
# Deploy Lambda
aws s3 cp fv-chat-v12.zip s3://family-docs-raw/lambda-packages/ --region eu-west-1
aws lambda update-function-code --function-name fv-chat-handler `
  --s3-bucket family-docs-raw --s3-key lambda-packages/fv-chat-v12.zip --region eu-west-1

# Deploy UI
aws s3 cp index.html s3://family-docs-ui/app/index.html --content-type text/html --region eu-west-1
aws cloudfront create-invalidation --distribution-id E6U4KTUCXF1Q3 --paths "/app/*" --region us-east-1

# Verify Lambda deployed
aws lambda get-function-configuration --function-name fv-chat-handler --region eu-west-1 --query "[CodeSize,LastModified]"
```

---

## Repository Structure

```
familyvault-ai/
├── README.md                              # This file
├── lambdas/
│   ├── fv-chat-handler/
│   │   └── lambda_function.py            # v12 — Planner+Orchestrator
│   ├── fv-upload-handler/
│   │   └── lambda_function.py            # Presign, complete, status
│   ├── fv-delete-handler/
│   │   └── lambda_function.py            # Cascade delete S3+DDB+KB
│   ├── fv-memory-handler/
│   │   └── lambda_function.py            # Chat session management
│   └── vector-processor/
│       └── lambda_function.py            # OCR → embed → S3 Vectors
├── ui/
│   └── index.html                        # Complete SPA (v8 — latest)
└── docs/
    ├── architecture.md                   # Detailed architecture notes
    ├── api-reference.md                  # All API endpoints
    └── deployment.md                     # Deployment runbook
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Runtime | Python 3.11 (Lambda) |
| AI Model | Claude Haiku 4.5 (EU cross-region inference) |
| Embeddings | Amazon Titan Embed Text v2 (1024-dim) |
| Vector Store | Amazon S3 Vectors (cosine similarity) |
| Knowledge Base | Amazon Bedrock KB |
| Auth | Amazon Cognito User Pool + JWT |
| Database | Amazon DynamoDB (PAY_PER_REQUEST) |
| Storage | Amazon S3 (3 buckets) |
| CDN | Amazon CloudFront + OAC |
| Email | Amazon SES |
| OCR | Amazon Textract |
| Frontend | Vanilla JS SPA, CSS custom properties, SVG |
| Fonts | Plus Jakarta Sans + JetBrains Mono |

---

*Last updated: 22 March 2026 — Session 3 of development*
*Next session: Sprint 1.5 (multi-user KB isolation) + Sprint 2 (family hierarchy backend)*
