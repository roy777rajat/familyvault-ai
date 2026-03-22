# FamilyVault AI — API Reference

## Base URL
`https://1oj10740w0.execute-api.eu-west-1.amazonaws.com`

## Authentication
All endpoints (except public ones) require:
```
Authorization: Bearer <Cognito AccessToken>
```

## Endpoints

### Documents

#### GET /documents
List all user documents.
```json
Response: { "documents": [{"PK": "DOC#...", "filename": "...", "status": "INDEXED", ...}] }
```

#### POST /upload/presign
Generate presigned S3 PUT URL for direct browser upload.
```json
Request:  { "filename": "doc.pdf", "content_type": "application/pdf" }
Response: { "presigned_url": "https://...", "document_id": "<uuid>", "s3_key": "..." }
```

#### POST /upload/complete
Mark upload complete, trigger vector processing.
```json
Request:  { "document_id": "<uuid>" }
Response: { "document_id": "<uuid>", "status": "UPLOADED_PROCESSING" }
```

#### DELETE /documents/{document_id}
Soft-delete document from DynamoDB, delete from S3, trigger KB resync.
```json
Response: { "deleted": true, "document_id": "<uuid>" }
```

### Memory

#### GET /memory/sessions
List chat sessions grouped by session_id.
```json
Response: { "sessions": [{"session_id": "...", "turns": [...], "created_at": "..."}] }
```

#### DELETE /memory/sessions/{session_id}
Delete a specific chat session.

#### DELETE /memory/all
Clear all chat history for the user.

### Auth

#### POST /auth/post-confirm (Public)
Post-registration hook. Creates UserProfiles entry.
```json
Request: { "email": "...", "name": "...", "security_question": "...", "security_answer": "..." }
```

#### GET /auth/profile
Get user profile.

#### PUT /auth/profile
Update display name, preferred email, default CC.

### Email

#### POST /email/draft
Generate AI email draft via Claude.
```json
Request:  { "rag_answer": "...", "doc_names": ["..."], "tone": "Professional", "user_name": "..." }
Response: { "draft_subject": "...", "draft_body": "..." }
```

#### POST /email/send
Send email via SES with presigned S3 links.
```json
Request:  { "to": ["..."], "cc": [...], "subject": "...", "body": "...", "doc_ids": ["..."] }
Response: { "sent": true }
```

## WebSocket

**URL:** `wss://4hnchd4nrk.execute-api.eu-west-1.amazonaws.com/production`

### Send Message
```json
{ "query": "What is my PAN card number?", "session_id": "<uuid>", "user_id": "<sub>" }
```

### Receive Messages
```json
{"type": "status",       "message": "Searching..."}
{"type": "scratchpad",   "event": "plan",   "content": "Plan:\n  Step 1..."}
{"type": "scratchpad",   "event": "step",   "content": "Executing: search_documents"}
{"type": "scratchpad",   "event": "result", "content": "Found 3 chunks from: PanCard.pdf"}
{"type": "scratchpad",   "event": "done",   "content": ""}
{"type": "token",        "content": "Your PAN card..."}
{"type": "clear_streaming"}
{"type": "html",         "content": "<div class=doc-table-wrap>..."}
{"type": "links",        "links": [{"filename": "...", "url": "https://...presigned..."}]}
{"type": "final",        "sources": ["PanCard.pdf (0.62)"], "session_id": "<uuid>"}
{"type": "error",        "message": "Something went wrong"}
```
