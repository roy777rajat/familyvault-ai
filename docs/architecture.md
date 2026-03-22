# FamilyVault AI — Architecture Notes

## Region
`eu-west-1` (Ireland) — all resources

## Auth Flow
```
Browser → Cognito InitiateAuth → JWT (IdToken + AccessToken)
→ All API calls: Authorization: Bearer <AccessToken>
→ JWT Authorizer (kj2taa) validates against User Pool eu-west-1_LUZKAYGwC
→ Lambda reads sub from event.requestContext.authorizer.jwt.claims.sub
```

## Chat WebSocket Flow
```
1. Browser → connectWS() → wss://4hnchd4nrk.../production
2. $connect route → fv-chat-handler (Lambda)
3. User sends: {query, session_id, user_id}
4. Lambda:
   a. plan(query) → Planner Claude call → JSON steps
   b. push scratchpad plan to client
   c. for each step: execute tool, push scratchpad event
   d. stream tokens via apigw.post_to_connection()
5. Client receives: token | html | links | final | scratchpad
```

## S3 Key Structure
```
New uploads:  user=<sub>/year=<Y>/month=<M>/<doc_id>/<filename>
Old (email):  year=<Y>/month=<M>/<doc_id>/<filename>
```

## DynamoDB Patterns
```
DocumentMetadata:
  PK = DOC#<uuid>
  user_id = <cognito sub>     ← filter key
  status = PENDING | UPLOADED_PROCESSING | INDEXED
  deleted = true/false         ← soft delete

ChatSessions:
  PK = USER#<sub>
  SK = SESSION#<sid>#TURN#<uuid>
```

## Bedrock KB Notes
- All KB scores cluster at 0.61 ± 0.02 — score-based filtering is NOT reliable
- Use keyword-grounded matching for download links
- KB query does NOT filter by user_id yet — Sprint 1.5 fix needed
- Embedding model: amazon.titan-embed-text-v2:0
- Dimensions: 1024, metric: cosine

## Known Score Clustering Issue
```python
# KB scores for 'PAN card' query:
# PanCard.pdf          = 0.618  ← best
# PolicyKit.pdf        = 0.613  ← only 0.5% lower!
# 07.Rajat_Passport    = 0.611
# All above 0.50 threshold

# Fix: keyword match planner's search query against source filename
# 'pan card' keywords: {'pan', 'card'}
# PanCard.pdf: 'pan'✓ 'card'✓ = score 2 → INCLUDED
# PolicyKit.pdf: no match → EXCLUDED
```

## Lambda Environment Variables
```
fv-chat-handler:    BEDROCK_KB_ID=PYV06IINGT, BUCKET=family-docs-raw, REGION=eu-west-1
fv-upload-handler:  BUCKET=family-docs-raw, REGION=eu-west-1
fv-delete-handler:  BUCKET=family-docs-raw, BEDROCK_KB_ID=PYV06IINGT, BEDROCK_DS_ID=JZ13ZYCSRL
vector_processor:   BEDROCK_KB_SYNC=false, VECTOR_BUCKET=family-docs-vectors, VECTOR_INDEX=family-docs-index
```

## IAM Roles
```
FamilyVaultLambdaRole:
  - AWSLambdaBasicExecutionRole
  - AmazonDynamoDBFullAccess
  - AmazonS3FullAccess
  - AmazonBedrockFullAccess
  - AmazonSESFullAccess
  Inline: WebSocketManageConnections (execute-api:ManageConnections on 4hnchd4nrk)

vector_processor_lambda-role-gc893i7i:
  Inline: S3VectorsPutPolicy (s3vectors:PutVectors/QueryVectors/GetVectors/DeleteVectors)
```
