# FamilyVault AI — Master Project Context

> **Last updated:** Session 8, Apr 4 2026  
> **Purpose:** Complete project state for future Claude sessions — read this first before doing anything

---

## 🌐 Live URLs
| Resource | URL |
|---|---|
| App | https://d38ys5d9amc45p.cloudfront.net/app/index.html |
| API Base | https://1oj10740w0.execute-api.eu-west-1.amazonaws.com |
| WebSocket | wss://4hnchd4nrk.execute-api.eu-west-1.amazonaws.com/production |

---

## 🏗️ AWS Infrastructure

| Resource | Value |
|---|---|
| Account ID | 141571819444 |
| IAM User | rajat-full-access |
| Primary Region | eu-west-1 |
| Cognito User Pool | eu-west-1_LUZKAYGwC |
| Cognito Client ID | 5j9s5557grmvt7gbuo8nopga8o |
| HTTP API ID | 1oj10740w0 |
| WebSocket API ID | 4hnchd4nrk |
| JWT Authorizer ID | kj2taa |
| CloudFront Dist ID | E6U4KTUCXF1Q3 |
| CloudFront Domain | d38ys5d9amc45p.cloudfront.net |
| Lambda Role ARN | arn:aws:iam::141571819444:role/FamilyVaultLambdaRole |
| Bedrock KB ID | PYV06IINGT |
| Bedrock Data Source | JZ13ZYCSRL |
| Root user sub | f2558464-7001-7088-8818-16f339b84fb6 |
| Root user email | roy777rajat@gmail.com |

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

| Route | Integration ID | Auth | Lambda |
|---|---|---|---|
| GET /documents | cw000te | JWT | fv-upload-handler |
| GET /notifications | cw000te | JWT | fv-upload-handler |
| POST /notifications/read | cw000te | JWT | fv-upload-handler |
| GET /download | bllt1be | NONE | fv-download-handler |
| GET /costs | 3jzgrsa | JWT | fv-cost-handler |

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
- **Local backup:** E:\NEWTEMP\aws-api-mcp\workdir\index-backup.html (101624 bytes — CLEAN)
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

### Screen switch (in repaint/render function)
```js
case 'dashboard':     content=buildDashboard();      break;
case 'documents':     content=buildDocuments();      break;
case 'upload':        content=buildUpload();         break;
case 'email':         content=buildEmail();          break;
case 'memory':        content=buildMemory();         break;
case 'notifications': content=buildNotifications();  break;
case 'profile':       content=buildProfile();        break;
case 'settings':      content=buildSettings();       break;
case 'costs':         content=buildCosts();          break;  // Added Session 8
```

### State object (S)
```js
S.token        // Cognito JWT token
S.user         // User profile
S.docs         // Filtered/sorted documents (for display)
S.allDocs      // All documents (for dashboard counts) — added Session 8
S.docsLoaded   // Boolean
S.screen       // Current screen name
S.modal        // Modal state
```

### Token retrieval pattern for new screens
```js
var token = (typeof S !== 'undefined' && S.token)
  ? S.token
  : localStorage.getItem('fv_token') || localStorage.getItem('fv_atoken') || '';
```

### API call pattern for new screens (safe, avoids req() issues)
```js
fetch('https://1oj10740w0.execute-api.eu-west-1.amazonaws.com/your-route', {
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
aws cloudfront create-invalidation --distribution-id E6U4KTUCXF1Q3 --paths "/app/*" --region us-east-1

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

### Service categorisation
```python
AI_SVCS    = {"Claude Haiku 4.5 (Amazon Bedrock Edition)",
               "Claude 3 Haiku (Amazon Bedrock Edition)",
               "Claude Sonnet 4 (Amazon Bedrock Edition)",
               "Amazon Bedrock"}
S3_SVCS    = {"Amazon Simple Storage Service"}
TEXT_SVCS  = {"Amazon Textract"}
INFRA_SVCS = {"AWS Lambda", "Amazon API Gateway", "Amazon DynamoDB",
               "Amazon CloudFront", "Amazon Cognito",
               "Amazon Simple Email Service", "Amazon Rekognition"}
```

---

## 📊 Cost Data Summary (as of Apr 4 2026)

| Month | Total | AI Cost | AI% |
|---|---|---|---|
| March 2026 | $0.5793 | $0.4768 | 82% |
| April 2026 (4 days) | $0.2227 | $0.0637 | 29% |

| Day | Cost | Notes |
|---|---|---|
| Apr 3 2026 | $0.1039 | Highest single day |
| Mar 22 | $0.1358 | 2nd highest |
| Mar 7 | $0.0668 | Heavy Claude 3 Haiku use |

**All infra services = $0.00 (free tier):** Lambda, DynamoDB, API GW, CloudFront, SES, Cognito, Textract, Rekognition

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
- [ ] Add token count tracking per conversation
- [ ] Cost alerts/budget threshold notifications
- [ ] Per-user cost breakdown (when multi-user is live)
- [ ] Historical trend comparison (this month vs last month)
- [ ] Export cost report as CSV

---

## 📁 Key Files in Workdir (E:\NEWTEMP\aws-api-mcp\workdir)

| File | Status | Notes |
|---|---|---|
| index-backup.html | ✅ CLEAN | 101624 bytes — always use as base for patches |
| index-final-clean.html | ✅ DEPLOYED | 127401 bytes — current live version |
| fv-cost-handler.zip | ✅ | Lambda zip for cost handler |
| vector_processor_fixed.zip | ✅ | With ddb_updater fix |
| ddb_updater.py | ✅ | Fixed UUID regex for both S3 key formats |
| index-final-v2/v3/v4/v5/v6.html | ⚠️ CORRUPTED | Do not use — intermediate failed patches |

---

## 🔑 vector_processor S3 Key Formats

Two formats exist — both handled by `ddb_updater.py`:
```
# Upload path:
user=<uid>/year=YYYY/month=MM/<doc_id>/filename.pdf

# Email ingestion path:
year=YYYY/month=MM/<doc_id>/filename.pdf
```

The UUID regex in ddb_updater.py extracts doc_id from both.

---

## 🔧 Useful Debug Commands

```powershell
# Check latest Lambda logs
aws logs describe-log-streams --log-group-name /aws/lambda/fv-cost-handler --region eu-west-1 --order-by LastEventTime --descending --limit 3

# Test cost Lambda directly
aws lambda invoke --function-name fv-cost-handler --region eu-west-1 \
  --payload '{"requestContext":{"http":{"method":"GET"}},"queryStringParameters":{"gran":"DAILY","from":"2026-04-01","to":"2026-04-04"}}' \
  --invocation-type RequestResponse out.json

# Check DynamoDB doc
aws dynamodb get-item --table-name DocumentMetadata --key '{"doc_id":{"S":"DOC#xxxx"}}' --region eu-west-1

# List all docs for user
aws dynamodb query --table-name DocumentMetadata \
  --index-name user_id-uploaded_at-index \
  --key-condition-expression 'user_id = :u' \
  --expression-attribute-values '{":u":{"S":"<user_sub>"}}' --region eu-west-1
```

---

## 📦 GitHub Repo

**Repo:** https://github.com/roy777rajat/familyvault-ai  
**Latest commit:** Session 8 — Live Cost Dashboard  

### Key files in repo
```
lambdas/
  fv-cost-handler/lambda_function.py   ← Live Cost Explorer Lambda
  fv-upload-handler/lambda_function.py ← v4 with notifications
  fv-email-sender/lambda_function.py   ← v4 with read=False
  vector-processor/ddb_updater.py      ← UUID regex fix
infra/
  api-gateway-routes.md                ← All routes documented
ui/
  COST_DASHBOARD.md                    ← Cost Dashboard feature docs
PROJECT_CONTEXT.md                     ← THIS FILE
```

---

## 💡 Session Workflow (for future Claude sessions)

1. **Read PROJECT_CONTEXT.md first** (this file) — full state
2. **Read the relevant lambda file** for the feature being worked on
3. **Always download fresh index.html** before patching UI:
   ```powershell
   aws s3api get-object --bucket family-docs-ui --key app/index.html --region eu-west-1 current.html
   ```
4. **Always patch from index-backup.html** not from a previously patched file
5. **Always verify before deploying:**
   - Nav: `($html -match "s:'costs'")`
   - Screen case: `($html -match "case 'costs'")`
   - No bad helpers: `(-not ($html -match "el\('span'"))`
   - Function present: `($html -match "function buildXxx")`
6. **Deploy and invalidate:**
   ```powershell
   aws s3 cp file.html s3://family-docs-ui/app/index.html --content-type text/html --region eu-west-1
   aws cloudfront create-invalidation --distribution-id E6U4KTUCXF1Q3 --paths "/app/*" --region us-east-1
   ```
7. **Update PROJECT_CONTEXT.md** with session summary before ending
