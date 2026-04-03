# 🏠 FamilyVault AI

<!-- AWS Service Icons -->
<p align="center">
  <img src="https://img.shields.io/badge/Amazon%20Bedrock-FF9900?style=flat&logo=amazonaws&logoColor=white">
  <img src="https://img.shields.io/badge/Amazon%20S3-569A31?style=flat&logo=amazons3&logoColor=white">
  <img src="https://img.shields.io/badge/AWS%20Lambda-FF9900?style=flat&logo=awslambda&logoColor=white">
  <img src="https://img.shields.io/badge/Amazon%20DynamoDB-4053D6?style=flat&logo=amazondynamodb&logoColor=white">
  <img src="https://img.shields.io/badge/Amazon%20Cognito-FF9900?style=flat&logo=amazonaws&logoColor=white">
  <img src="https://img.shields.io/badge/API%20Gateway-FF4F8B?style=flat&logo=amazonaws&logoColor=white">
  <img src="https://img.shields.io/badge/Amazon%20SES-FF9900?style=flat&logo=amazonaws&logoColor=white">
  <img src="https://img.shields.io/badge/Status-Active-brightgreen">
  <img src="https://img.shields.io/badge/Session-6%20Complete-blue">
</p>

<p align="center">
  <strong>AWS-powered personal document intelligence platform</strong><br>
  Store, search, chat, and share your family documents securely using AI
</p>

## Live URL
`https://d38ys5d9amc45p.cloudfront.net/app/index.html`

---

> **FOR NEXT SESSION — READ THIS FIRST**
> Sessions 1–6 are complete. Start next session with **Sprint 1.5 — KB user_id isolation**.

---

## AWS Infrastructure

| Resource | ID |
|---|---|
| Cognito User Pool | `eu-west-1_LUZKAYGwC` |
| Cognito App Client | `5j9s5557grmvt7gbuo8nopga8o` (no secret) |
| HTTP API | `1oj10740w0` → `https://1oj10740w0.execute-api.eu-west-1.amazonaws.com` |
| WebSocket API | `4hnchd4nrk` → `wss://4hnchd4nrk.execute-api.eu-west-1.amazonaws.com/production` |
| JWT Authorizer | `kj2taa` |
| CloudFront | `E6U4KTUCXF1Q3` → `d38ys5d9amc45p.cloudfront.net` |
| S3 Buckets | `family-docs-raw`, `family-docs-vectors`, `family-docs-ui` |
| Bedrock KB | `PYV06IINGT`, Data Source: `JZ13ZYCSRL` |
| Lambda Role | `arn:aws:iam::141571819444:role/FamilyVaultLambdaRole` |
| Root User Sub | `f2558464-7001-7088-8818-16f339b84fb6` |
| Root Email | `roy777rajat@gmail.com` |
| Account | `141571819444` / Region: `eu-west-1` |

## API Gateway Routes

| Route | Integration | Auth |
|---|---|---|
| `GET /documents` | `cw000te` → fv-upload-handler | JWT |
| `POST /upload/presign` | `cw000te` → fv-upload-handler | JWT |
| `POST /upload/complete` | `cw000te` → fv-upload-handler | JWT |
| `GET /upload/status` | `cw000te` → fv-upload-handler | JWT |
| `GET /notifications` | `cw000te` → fv-upload-handler | JWT |
| `POST /notifications/read` | `cw000te` → fv-upload-handler | JWT |
| `GET /download` | `bllt1be` → fv-download-handler | NONE |

## Lambda Functions

| Function | Version | Memory | Timeout |
|---|---|---|---|
| `fv-chat-handler` | v13 | 1024 MB | 300s |
| `fv-upload-handler` | v4 (Session 6) | 256 MB | 30s |
| `fv-delete-handler` | v2 | 256 MB | 60s |
| `fv-memory-handler` | v3 | 256 MB | 30s |
| `fv-email-sender` | v4 (Session 6) | 512 MB | 60s |
| `fv-auth-handler` | v1 | 256 MB | 30s |
| `vector_processor_lambda` | v2+ddb_patch | 1024 MB | 305s |
| `fv-download-handler` | v1 | 256 MB | 30s |

## DynamoDB Tables

| Table | PK | SK | Notes |
|---|---|---|---|
| `DocumentMetadata` | `DOC#<uuid>` | — | ~34 docs |
| `ChatSessions` | `USER#<sub>` | `SESSION#<sid>#TURN#<uuid>` | |
| `EmailSentLog` | `USER#<sub>` | `EMAIL#<iso>` | `read` bool field |
| `DownloadTokens` | `TOKEN#<uuid>` | — | TTL on `expires_epoch` |
| `UserProfiles` | `USER#<sub>` | — | |
| `SecurityQuestions` | `USER#<sub>` | — | |

---

## Session 6 — What Was Fixed (Apr 2–3 2026)

### fv-upload-handler v4
- `list_documents()`: returns ALL user docs (no `uploaded_at` filter), sorted newest first
- `GET /notifications`: queries `EmailSentLog` using `Key("PK").eq(f"USER#{user_id}")` — correct boto3 Key() expression
- `POST /notifications/read`: marks emails as read in DynamoDB

### fv-email-sender v4
- `EmailSentLog.put_item()` now always sets `read=False` on every new email send

### vector_processor_lambda (patched)
- Injected `ddb_updater.py` — calls `mark_doc_indexed(s3_key)` after successful vector storage
- Added IAM policy `DynamoDBDocumentMetadataUpdate` to role `vector_processor_lambda-role-gc893i7i`
- Root cause: lambda was processing docs but never updating DDB status to INDEXED

### UI (index-final.html → S3)
- `buildNotifications()` completely rewritten to use `req('/notifications', {}, S.token)` — same pattern as `loadDocs()`
- `loadDocs()` now stores `S.allDocs` (all docs) AND `S.docs` (sorted by date)
- `buildDashboard()` uses `S.allDocs.length` for total counts
- Activity tab: two tabs — 📧 Emails Sent (real API) + 📂 Documents (with source info)
- Fixed: dashboard showing 0 docs (was filtering out old docs without `uploaded_at`)
- Fixed: emails tab empty (was using raw `fetch()` with wrong localStorage key)

---

## MCP Server Setup

```json
{
  "aws": {
    "command": "python",
    "args": ["-m", "uv", "tool", "run", "awslabs.aws-api-mcp-server@latest"],
    "env": { "AWS_REGION": "us-east-1" }
  },
  "github": {
    "command": "docker",
    "args": ["run", "-i", "--rm", "-e", "GITHUB_PERSONAL_ACCESS_TOKEN=YOUR_PAT_HERE", "ghcr.io/github/github-mcp-server"]
  },
  "postgres": {
    "command": "docker",
    "args": ["exec", "-i", "pg_mcp", "postgres-mcp", "--access-mode=unrestricted"],
    "env": { "DATABASE_URI": "postgresql://pguser:pgpassword@host.docker.internal:5432/finance" }
  }
}
```

> GitHub MCP uses `docker run -i --rm` — do NOT use sleep infinity (image has no shell).
> Neo4j AuraDB free tier pauses after inactivity — resume at console.neo4j.io if DNS fails.

## Deployment Commands

```powershell
# Lambda deploy (zip must be in E:\NEWTEMP\aws-api-mcp\workdir)
Compress-Archive -Path lambda_function.py -DestinationPath fv-xyz.zip -Force
aws lambda update-function-code --function-name fv-xyz --zip-file fileb://fv-xyz.zip --region eu-west-1

# UI deploy
aws s3 cp index.html s3://family-docs-ui/app/index.html --content-type text/html --region eu-west-1
aws cloudfront create-invalidation --distribution-id E6U4KTUCXF1Q3 --paths "/app/*" --region us-east-1
```

---

## 🔧 Pending — Next Session

### Sprint 1.5 — Multi-User KB Isolation (BEFORE adding new users)
- [ ] Add `user_id` metadata filter to Bedrock KB `retrieve()` in `fv-chat-handler`
- [ ] Stamp `user_id` in `vector_processor_lambda` S3 Vectors metadata
- [ ] GSI on `DocumentMetadata`: `user_id-uploaded_at-index`
- [ ] Backfill 34 existing docs with `user_id` in vector metadata

### Sprint 2 — Family Hierarchy Backend
- [ ] `FamilyTree` DynamoDB table, Cognito Groups, invite/accept endpoints, visibility resolver

### Sprint 3 — Guardrails
- [ ] `FamilyGuardrails` table, Bedrock Guardrails integration

---

## Architecture

```
Browser → CloudFront → S3 (SPA)
Browser → API Gateway HTTP (JWT) → Lambda → DynamoDB / S3 / Bedrock / SES
Browser → API Gateway WebSocket → fv-chat-handler → Bedrock KB + Claude Haiku
S3 upload → vector_processor_lambda → Textract → Titan Embed → S3 Vectors → ddb_updater → DDB INDEXED
Email click → /download?token → fv-download-handler → DDB → 302 → S3 presigned URL
```

*Last updated: 3 Apr 2026 — Session 6 complete*
