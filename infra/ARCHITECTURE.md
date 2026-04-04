# FamilyVault AI — Architecture

## High-Level Flow
```
User Browser
  ├── CloudFront (d38ys5d9amc45p.cloudfront.net)
  │     └── S3 family-docs-ui/app/index.html   ← Single-page app
  │
  ├── HTTP API Gateway (1oj10740w0)
  │     ├── JWT Authorizer (kj2taa) ← Cognito eu-west-1_LUZKAYGwC
  │     ├── GET  /documents     → fv-upload-handler
  │     ├── GET  /notifications → fv-upload-handler
  │     ├── POST /notifications/read → fv-upload-handler
  │     ├── GET  /download      → fv-download-handler (no auth)
  │     └── GET  /costs         → fv-cost-handler
  │
  └── WebSocket API (4hnchd4nrk)
        └── /production         → fv-chat-handler

Document Upload Flow:
  Browser → S3 family-docs-raw
         → S3 event → vector_processor_lambda
         → Textract (OCR) → Bedrock KB (PYV06IINGT)
         → DynamoDB DocumentMetadata (status: INDEXED)
         → S3 family-docs-vectors

Email Ingestion Flow:
  Email → SES → S3 family-docs-raw (year=.../month=.../<doc_id>/file)
       → S3 event → vector_processor_lambda
       → Same as upload flow above
       ⚠️ KNOWN ISSUE: user_id + uploaded_at NOT stamped at ingest time

Chat Flow:
  Browser WebSocket → fv-chat-handler
                   → Bedrock KB retrieve() [TODO: add user_id filter]
                   → Claude Haiku 4.5 (inference)
                   → Response streamed back

Cost Dashboard Flow:
  Browser → GET /costs?gran=DAILY&from=...&to=...
          → API Gateway (JWT) → fv-cost-handler
          → boto3 ce.get_cost_and_usage() [us-east-1]
          → AWS Cost Explorer API (LIVE, real-time)
          → JSON response → Browser renders
```

## Key Design Decisions

### Single-page app (SPA)
- One HTML file served from S3/CloudFront
- All screens built with JS DOM manipulation
- State stored in global `S` object
- `repaint()` rebuilds the current screen on state change

### Lambda role (FamilyVaultLambdaRole)
Inline policies attached:
- CloudWatchLogsFullAccess
- DynamoDBFullAccess (scoped to FamilyVault tables)
- S3FullAccess (scoped to family-docs-* buckets)
- BedrockFullAccess
- SESFullAccess
- TextractFullAccess
- CostExplorerReadAccess (added Session 8)

### Auth flow
1. User logs in via Cognito hosted UI or app UI
2. Cognito returns JWT token
3. Token stored in `S.token` (in-memory) + `localStorage.fv_token`
4. All API calls include `Authorization: Bearer <token>`
5. API Gateway validates token via JWT Authorizer against Cognito

### Document ID format
- DynamoDB key: `DOC#<uuid>` (e.g., `DOC#74e2166a-...`)
- S3 upload path: `user=<sub>/year=YYYY/month=MM/<uuid>/filename.pdf`
- S3 email path: `year=YYYY/month=MM/<uuid>/filename.pdf`
