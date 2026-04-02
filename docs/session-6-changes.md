# Session 6 Changes — Activity, Dashboard, Notifications

## Date: 2 April 2026

## What Was Fixed

### Problem 1: Activity > Emails Sent — always empty
- **Root cause:** `buildNotifications()` used raw `fetch()` with localStorage token — token wasn't available at render time
- **Fix:** Rewrote `buildNotifications()` to use `req('/notifications', {}, S.token)` — same pattern as `loadDocs()` which already works. Uses `S.token` (in-memory) not localStorage.
- **Fix:** `fv-email-sender` now writes `read=False` on every new EmailSentLog entry so new emails appear immediately
- **Fix:** `fv-upload-handler` `/notifications` endpoint now uses `Key('PK').eq(...)` boto3 expression correctly

### Problem 2: Dashboard counts showing 0 / only recent
- **Root cause:** `list_documents` was filtering out old docs (no `uploaded_at`), `buildDashboard` used filtered `S.docs`
- **Fix:** `loadDocs()` now stores `S.allDocs` = ALL user docs, `S.docs` = sorted for display
- **Fix:** Dashboard KPIs use `S.allDocs` for counts (total docs, indexed, categories)
- **Fix:** `list_documents` Lambda returns ALL user docs sorted by date (dated first)

### Problem 3: Activity > Documents — source info added
- Each document now shows: icon · filename · 📤 Uploaded or 📧 Via email · Rajat · date · status badge

## API Routes Added
- `GET /notifications` → fv-upload-handler (JWT auth)
- `POST /notifications/read` → fv-upload-handler (JWT auth)

## Lambda Versions
- `fv-upload-handler` v3 (notifications + allDocs sort)
- `fv-email-sender` v4 (read=False on send)
- `fv-download-handler` v1 (unchanged)
- `vector_processor_lambda` patched (DDB status → INDEXED after vector write)

## Files Changed
- `lambdas/fv-upload-handler/lambda_function.py` — v3
- `lambdas/fv-email-sender/lambda_function.py` — v4 (committed separately)
- `ui/index.html` — deployed to S3 (not stored in repo, 110KB)
