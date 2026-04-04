# FamilyVault AI — Master Project Context

> **Last updated:** Session 8, Apr 4 2026  
> **Purpose:** Complete project state for future Claude sessions — read this first before doing anything  
> **⚠️ Security:** All sensitive IDs redacted. Real values are in AWS console / owner's secure notes only.

---

## 🌐 Live URLs
| Resource | URL |
|---|---|
| App | https://[CLOUDFRONT_DOMAIN]/app/index.html |
| API Base | https://[API_ID].execute-api.eu-west-1.amazonaws.com |
| WebSocket | wss://[WS_API_ID].execute-api.eu-west-1.amazonaws.com/production |

> To get real values: `aws apigatewayv2 get-apis --region eu-west-1`

---

## 🏗️ AWS Infrastructure

| Resource | How to find |
|---|---|
| Account ID | `aws sts get-caller-identity` |
| Primary Region | eu-west-1 |
| Cognito User Pool | `aws cognito-idp list-user-pools --max-results 10 --region eu-west-1` |
| Cognito Client ID | `aws cognito-idp list-user-pool-clients --user-pool-id <pool-id> --region eu-west-1` |
| HTTP API ID | `aws apigatewayv2 get-apis --region eu-west-1` |
| WebSocket API ID | `aws apigatewayv2 get-apis --region eu-west-1` |
| JWT Authorizer ID | `aws apigatewayv2 get-authorizers --api-id <api-id> --region eu-west-1` |
| CloudFront Dist ID | `aws cloudfront list-distributions` |
| Lambda Role ARN | `aws iam get-role --role-name FamilyVaultLambdaRole` |
| Bedrock KB ID | `aws bedrock-agent list-knowledge-bases --region eu-west-1` |

### S3 Buckets
| Bucket | Purpose |
|---|---|
| family-docs-raw | Raw uploaded documents |
| family-docs-vectors | Vector embeddings |
| family-docs-ui | Frontend (index.html) |

### DynamoDB Tables
| Table | Purpose |
|---|---|
| DocumentMetadata | Doc metadata, status, user_id |
| ConversationMemory | Chat memory per user |
| EmailSentLog | Email send history |
| FamilyVaultNotifications | Push notifications |

---

## 🔌 API Gateway Routes

| Route | Auth | Lambda |
|---|---|---|
| GET /documents | JWT | fv-upload-handler |
| GET /notifications | JWT | fv-upload-handler |
| POST /notifications/read | JWT | fv-upload-handler |
| GET /download | NONE | fv-download-handler |
| GET /costs | JWT | fv-cost-handler |
| POST /upload/presign | JWT | fv-upload-handler |
| POST /upload/complete | JWT | fv-upload-handler |
| POST /email/send | JWT | fv-email-sender |
| POST /email/draft | JWT | fv-email-sender |
| GET /auth/profile | JWT | fv-auth-handler |
| PUT /auth/profile | JWT | fv-auth-handler |
| PUT /auth/change-password | JWT | fv-auth-handler |
| GET /memory/sessions | JWT | fv-memory-handler |
| GET /memory/long-term | JWT | fv-memory-handler |

> To get integration IDs: `aws apigatewayv2 get-routes --api-id <api-id> --region eu-west-1`

---

## ⚡ Lambda Functions

| Function | Version | Memory | Timeout | Purpose |
|---|---|---|---|---|
| fv-chat-handler | v13 | 1024MB | 300s | AI chat via Bedrock KB |
| fv-upload-handler | v4 | 256MB | 30s | /documents + /notifications |
| fv-delete-handler | v2 | 256MB | 60s | Document deletion |
| fv-memory-handler | v3 | 256MB | 30s | Chat memory |
| fv-email-sender | v4 | 512MB | 60s | Email via SES |
| fv-auth-handler | v1 | 256MB | 30s | Auth helper |
| vector_processor_lambda | v2+ddb_patch | 1024MB | 305s | Vectorise docs |
| fv-download-handler | v1 | 256MB | 30s | Presigned URL download |
| fv-cost-handler | v1 | 256MB | 30s | Live AWS Cost Explorer |

### fv-cost-handler details
- **Route:** GET /costs (JWT auth)
- **Query params:** `?gran=DAILY|MONTHLY &from=YYYY-MM-DD &to=YYYY-MM-DD`
- **What it does:** Calls `ce.get_cost_and_usage()` live on every request
- **Response shape:**
  ```json
  {
    "daily": [{"date", "ai", "s3", "textract", "infra", "tax", "other", "total", "estimated"}],
    "services": [{"name", "cost"}],
    "monthly": [{"month", "total", "ai", "estimated"}],
    "grand_total": 0.0,
    "date_from": "YYYY-MM-DD",
    "date_to": "YYYY-MM-DD",
    "granularity": "DAILY",
    "generated_at": "ISO timestamp"
  }
  ```
- **IAM:** `CostExplorerReadAccess` inline policy on FamilyVaultLambdaRole
- **Note:** Cost Explorer API is in us-east-1 only — boto3 client hardcoded to us-east-1

---

## 🖥️ Frontend Architecture

### Key file
- **S3 path:** s3://family-docs-ui/app/index.html
- **Local backup:** index-backup.html (101624 bytes — CLEAN baseline)
- **Latest deployed:** index-final-clean.html (127401 bytes)

### App helper functions — CRITICAL RULES
The app uses custom helper functions. **These rules must be followed or the app breaks:**

| Helper | What it does | Restriction |
|---|---|---|
| `div(attrs, ...children)` | Creates div | Children must be strings or other helper results — **NOT real DOM elements** |
| `h1(attrs, text)` | Creates h1 | Same restriction |
| `p(attrs, text)` | Creates p | Same restriction |
| `el(tag, attrs, text)` | Creates element | `attrs` must be plain object — **string onclick values FORBIDDEN** — uses addEventListener internally |
| `req(path, opts, token)` | API fetch | Uses `await` internally — **must be called from async context only** |

### ⚠️ Critical lesson learned (Session 8)
**NEVER use `div()`/`h1()`/`p()`/`el()` helpers in buildCosts or any new screen.**  
Always use pure `document.createElement()` for new screens.  
The `req()` function uses `await` but is not declared `async` — causes silent failures.  
For new screens, always use direct `fetch()` with `Authorization: Bearer S.token`.

### Sidebar nav structure
```js
var nav = [
  {label:'Library', items:[
    {icon:'🏠', label:'Dashboard', s:'dashboard'},
    {icon:'📄', label:'Documents', s:'documents'},
    {icon:'📤', label:'Upload', s:'upload'},
    {icon:'📧', label:'Email Docs', s:'email'},
    {icon:'🧠', label:'Memory', s:'memory'},
    {icon:'🔔', label:'Activity', s:'notifications', badge:7},
  ]},
  {label:'Account', items:[
    {icon:'👤', label:'Profile', s:'profile'},
    {icon:'⚙️', label:'Settings', s:'settings'},
    {icon:'💰', label:'Costs', s:'costs'},     // Added Session 8
  ]},
];
```

### Screen switch
```js
case 'dashboard':     content=buildDashboard();      break;
case 'documents':     content=buildDocuments();      break;
case 'upload':        content=buildUpload();         break;
case 'email':         content=buildEmail();          break;
case 'memory':        content=buildMemory();         break;
case 'notifications': content=buildNotifications();  break;
case 'profile':       content=buildProfile();        break;
case 'settings':      content=buildSettings();       break;
case 'costs':         content=buildCosts();          break;
```

### Token retrieval pattern for new screens
```js
var token = (typeof S !== 'undefined' && S.token)
  ? S.token
  : localStorage.getItem('fv_token') || localStorage.getItem('fv_atoken') || '';
```

### API call pattern for new screens (safe, avoids req() issues)
```js
// Get API base URL from the app config (CFG.API) or look it up:
// aws apigatewayv2 get-apis --region eu-west-1
fetch(CFG.API + '/your-route', {
  headers: { Authorization: 'Bearer ' + token }
})
.then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
.then(function(data) { /* render */ })
.catch(function(e) { console.error(e); });
```

### Deployment commands
```powershell
# Deploy UI
aws s3 cp your-file.html s3://family-docs-ui/app/index.html --content-type text/html --region eu-west-1

# Get CloudFront dist ID first:
# aws cloudfront list-distributions
aws cloudfront create-invalidation --distribution-id <DIST_ID> --paths "/app/*" --region us-east-1

# Deploy Lambda
aws lambda update-function-code --function-name fv-xyz --zip-file fileb://fv-xyz.zip --region eu-west-1
```

### UI injection pattern (ALWAYS start from index-backup.html)
```powershell
$html = Get-Content "index-backup.html" -Raw -Encoding UTF8
# ... make replacements ...
$ip = $html.LastIndexOf("</script>")
$html = $html.Substring(0,$ip) + $newFunction + $html.Substring($ip)
$html | Out-File "index-new.html" -Encoding UTF8 -NoNewline
```
**NEVER chain patches on corrupted files. Always start from index-backup.html.**

---

## 💰 Cost Dashboard Feature (Added Session 8)

### How it works
1. User clicks 💰 Costs in sidebar
2. `buildCosts()` called by repaint
3. `setTimeout(doLoad, 300)` fires after 300ms (ensures S.token is ready)
4. `doLoad()` fetches `GET /costs?gran=DAILY&from=...&to=...` with Bearer token
5. `fv-cost-handler` Lambda calls AWS Cost Explorer API live
6. Response renders: 6 KPI cards, insights banner, 3 tabs (Chart/Services/Table)

### buildCosts() rules
- 100% pure `document.createElement()` — zero `div()`/`h1()`/`p()`/`el()` calls
- Direct `fetch()` — never `req()`
- `setTimeout(doLoad, 300)` for initial load
- `window._costLoad` assigned after first load for Refresh button

### Tabs
| Tab | Content |
|---|---|
| 📈 Chart | Chart.js stacked bar (AI/S3/Tax/Other), monthly summary cards |
| 🗂️ Services | Donut chart + service list with Free/AI/Tax/Other badges |
| 📊 Table | Daily rows + totals row + projections box |

---

## 🐛 Bugs Fixed (Session History)

### Session 7
- Email-ingested docs missing `user_id`/`uploaded_at` — manually stamped 3 docs
- `ddb_updater.py` UUID regex — handles both upload and email S3 key formats
- Activity > Emails — fixed to use `req('/notifications', {}, S.token)`
- Dashboard doc count — fixed using `S.allDocs` vs `S.docs`

### Session 8
- Cost Dashboard blank page — `el()` helper rejects string onclick → switched to pure DOM
- Cost Dashboard blank page — `div()` helper rejects real DOM elements as children → removed all helper calls
- Cost Dashboard API never called — `req()` uses `await` without `async` → switched to direct `fetch()`
- File corruption from patches — started patching corrupted files → rule: always start from index-backup.html

---

## 🚧 Pending Work (Sprint Backlog)

### IMMEDIATE — Sprint 1.5
- [ ] **KB user_id isolation** — Add `user_id` metadata filter to Bedrock KB `retrieve()` in fv-chat-handler — MUST do before adding new users
- [ ] **Vector metadata backfill** — Stamp `user_id` in vector_processor S3 metadata for existing 34+ docs
- [ ] **GSI on DocumentMetadata** — `user_id-uploaded_at-index` for efficient per-user queries
- [ ] **Email ingestion pipeline** — Stamp `user_id` + `uploaded_at` at write time (currently missing for email docs)

### Sprint 2 — Family Hierarchy
- [ ] `FamilyTree` DynamoDB table
- [ ] Cognito Groups for family members
- [ ] Invite/accept endpoints
- [ ] Family member document sharing

### Sprint 3 — Guardrails
- [ ] `FamilyGuardrails` table
- [ ] Bedrock Guardrails integration
- [ ] Per-family-member access controls

### Sprint 4 — Cost Dashboard Enhancements
- [ ] Token count tracking per conversation
- [ ] Cost alerts/budget threshold notifications
- [ ] Per-user cost breakdown (when multi-user is live)
- [ ] Historical trend comparison (month vs last month)
- [ ] Export cost report as CSV

---

## 🔧 Useful Debug Commands

```powershell
# Get all resource IDs dynamically (no hardcoding needed)
aws sts get-caller-identity
aws apigatewayv2 get-apis --region eu-west-1
aws cognito-idp list-user-pools --max-results 10 --region eu-west-1
aws cloudfront list-distributions
aws lambda list-functions --region eu-west-1

# Check latest Lambda logs
aws logs describe-log-streams --log-group-name /aws/lambda/fv-cost-handler --region eu-west-1 --order-by LastEventTime --descending --limit 3

# Check DynamoDB doc (replace DOC#xxxx with real ID)
aws dynamodb get-item --table-name DocumentMetadata --key '{"doc_id":{"S":"DOC#xxxx"}}' --region eu-west-1
```

---

## 🔑 vector_processor S3 Key Formats

Two formats exist — both handled by `ddb_updater.py`:
```
# Upload path:
user=<uid>/year=YYYY/month=MM/<doc_id>/filename.pdf

# Email ingestion path:
year=YYYY/month=MM/<doc_id>/filename.pdf
```

---

## 📦 GitHub Repo

**Repo:** https://github.com/roy777rajat/familyvault-ai

### Key files in repo
```
lambdas/
  fv-cost-handler/lambda_function.py   ← Live Cost Explorer Lambda
  fv-upload-handler/lambda_function.py ← v4 with notifications
  fv-email-sender/lambda_function.py   ← v4 with read=False
  vector-processor/ddb_updater.py      ← UUID regex fix
infra/
  api-gateway-routes.md                ← All routes documented
  ARCHITECTURE.md                      ← System architecture
ui/
  COST_DASHBOARD.md                    ← Cost Dashboard feature docs
  CODING_RULES.md                      ← Critical UI coding rules
PROJECT_CONTEXT.md                     ← THIS FILE
SESSIONS.md                            ← Session history
```

---

## 💡 Session Workflow (for future Claude sessions)

1. **Read PROJECT_CONTEXT.md first** (this file)
2. **Discover resource IDs dynamically** — never hardcode, always query AWS:
   ```powershell
   aws apigatewayv2 get-apis --region eu-west-1
   aws cloudfront list-distributions
   ```
3. **Download fresh index.html** before patching UI:
   ```powershell
   aws s3api get-object --bucket family-docs-ui --key app/index.html --region eu-west-1 current.html
   ```
4. **Always patch from index-backup.html** not a previously patched file
5. **Verify before deploying** (all must be True):
   ```powershell
   Write-Host "Nav:" ($html -match "s:'newscreen'")
   Write-Host "Case:" ($html -match "case 'newscreen'")
   Write-Host "Function:" ($html -match "function buildNewScreen")
   Write-Host "No el() errors:" (-not ($html -match "el\('(span|button)',\{onclick:"))
   ```
6. **Deploy and invalidate**
7. **Update PROJECT_CONTEXT.md + SESSIONS.md** before ending session
