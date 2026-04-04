# FamilyVault AI — Session History

## Session 1–6 (Mar 2026)
- Initial infrastructure: Cognito, API Gateway, Lambda functions, DynamoDB, S3, CloudFront
- fv-chat-handler with Bedrock KB integration
- Frontend SPA: all screens built
- WebSocket for real-time chat

## Session 7 (Apr 2–3 2026)
- Email-ingested docs missing user_id/uploaded_at — manually stamped 3 property tax docs
- ddb_updater.py UUID regex fix for both S3 key formats
- Activity > Emails screen fixed
- Dashboard doc count fixed with S.allDocs

## Session 8 (Apr 4 2026)
- Live Cost Dashboard (💰 Costs) — fv-cost-handler Lambda + UI
- Security audit + GitHub sensitive data redaction
- Observability architecture design (Phase 1/2/3 roadmap)

## Session 9 (Apr 4 2026)
### Phase 1 Observability — fully deployed

**Infrastructure:**
- ChatObservability DynamoDB table (GSIs: user_id-ts-index, session_id-index)
- ObservabilityConfig DynamoDB table (alert thresholds)
- fv-chat-handler upgraded to v14 with full instrumentation
- fv-observability-handler Lambda (GET/POST /observability, /observability/config)
- SNS topic FamilyVaultAlerts → email subscription (confirm!)
- 3 CloudWatch alarms: latency, errors, daily tokens

**UI: 📊 Observability screen (4 tabs)**
- Overview: p50/p95/p99 cards + daily latency + token charts
- Traces: per-turn table — latency color-coded, tokens, KB chunks, tools, cost
- Tools: tool usage breakdown + token stats
- Alerts: current thresholds + live config form → updates DDB + CW alarms in real-time

**What gets tracked per chat turn:**
input_tokens, output_tokens, latency_ms, planner_latency_ms, answerer_latency_ms,
kb_latency_ms, kb_chunks_retrieved, tools_called, model_id, status, estimated_cost_usd,
query_len, answer_len, short_term_turns, long_term_sessions

**CloudWatch metrics (FamilyVault/Chat namespace):**
ChatLatencyMs, InputTokens, OutputTokens, TotalTokens, KBChunksRetrieved, ChatErrors

## Pending (Next Session)
1. Confirm SNS subscription email at roy777rajat@gmail.com
2. KB user_id isolation in fv-chat-handler (CRITICAL before new users)
3. Vector metadata backfill for existing 34+ docs
4. GSI on DocumentMetadata for user_id queries
5. Email ingestion pipeline: stamp user_id + uploaded_at
6. Phase 2 Observability: LangSmith integration (EU tenant)
7. Sprint 2: Family Hierarchy
8. Security hardening: IAM least-privilege, MFA, CORS tighten, S3 versioning
