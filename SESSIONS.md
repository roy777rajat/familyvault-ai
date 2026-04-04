# FamilyVault AI — Session History

## Session 1–6 (Mar 2026)
- Initial infrastructure: Cognito, API Gateway, Lambda functions, DynamoDB, S3, CloudFront
- fv-chat-handler with Bedrock KB integration
- fv-upload-handler for document upload + notifications
- fv-email-sender for SES email
- Frontend SPA: Dashboard, Documents, Upload, Email, Memory, Activity, Profile, Settings screens
- WebSocket for real-time chat

## Session 7 (Apr 2–3 2026)
### Fixes
- Email-ingested docs missing `user_id`/`uploaded_at` — manually stamped 3 property tax docs
- `ddb_updater.py` — UUID regex to handle both upload and email S3 key formats
- Activity > Emails screen — fixed to use `req('/notifications', {}, S.token)` instead of raw localStorage fetch
- Dashboard doc count — `S.allDocs` stores all docs, `S.docs` is filtered/sorted for display

### Infrastructure
- vector_processor_lambda redeployed with ddb_updater.py fix
- fv-email-sender v4 — sets `read=False` on EmailSentLog

## Session 8 (Apr 4 2026)
### Feature: Live Cost Dashboard
- New Lambda: `fv-cost-handler` — calls AWS Cost Explorer `ce.get_cost_and_usage()` live
- New route: `GET /costs` (JWT auth, integration 3jzgrsa, route ju6w4kq)
- IAM: `CostExplorerReadAccess` inline policy on FamilyVaultLambdaRole
- UI: 💰 Costs nav item under Account section
- 6 KPI cards, live insights banner, 3 tabs (Chart/Services/Table)
- Date range picker + Daily/Monthly granularity toggle
- ↻ Refresh button re-fetches live data
- Status badge: Loading… → ✓ Live · date → Error

### Critical bugs fixed in this session
1. `el()` helper rejects string onclick → TypeError: parameter 2 is not of type Object
   - Fix: use `document.createElement()` + `element.onclick = function(){}`
2. `div()` helper rejects real DOM elements as children
   - Fix: don't mix helper functions and real DOM — use 100% pure DOM for new screens
3. `req()` uses await without async → silent failure, API never called
   - Fix: use direct `fetch()` with Authorization header
4. File corruption from patching corrupted files
   - Fix: always start from index-backup.html (101624 bytes, clean)
5. `buildCosts` was last function in file → `IndexOf("function ")` returned -1 → corrupted file
   - Fix: inject before `</script>` using `LastIndexOf("</script>")`, not between functions

### Deployment
- index-final-clean.html (127401 bytes) — current live version
- Built cleanly from index-backup.html in one PowerShell block

### Cost data summary (as of Apr 4 2026)
- March 2026: $0.5793 (AI = 82%, Tax = 15%)
- April 2026 (4 days): $0.2227
- Apr 3 highest day: $0.1039
- All infra = $0.00 (free tier)
- Projected monthly at current rate: ~$1.67

## Pending (Next Session)
1. KB user_id isolation in fv-chat-handler (CRITICAL before new users)
2. Vector metadata backfill for existing docs
3. GSI on DocumentMetadata for user_id queries
4. Email ingestion pipeline: stamp user_id + uploaded_at at write time
5. Sprint 2: Family Hierarchy (FamilyTree table, Cognito Groups, invite/accept)
6. Sprint 3: Guardrails (FamilyGuardrails table, Bedrock Guardrails)
7. Cost Dashboard enhancements: token tracking, budget alerts, CSV export
