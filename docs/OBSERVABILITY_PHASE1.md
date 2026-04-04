# Phase 1 Observability — Complete

Deployed: Session 9, Apr 4 2026

## What was built

### Infrastructure
| Resource | Details |
|---|---|
| DynamoDB: ChatObservability | Stores every chat turn trace. PK=USER#uid, SK=OBS#ts#uuid |
| DynamoDB: ObservabilityConfig | Alert config store. PK=CONFIG, SK=ALERTS |
| Lambda: fv-chat-handler v14 | Adds write_observation() + publish_metrics() to every orchestrate() call |
| Lambda: fv-observability-handler v1 | GET /observability, GET/POST /observability/config |
| SNS Topic: FamilyVaultAlerts | Email alerts → roy777rajat@gmail.com (confirm subscription!) |
| CW Alarm: FV-ChatLatency-High | avg latency >8000ms → SNS |
| CW Alarm: FV-ChatErrors-High | errors >5/hour → SNS |
| CW Alarm: FV-DailyTokens-High | tokens >50000/day → SNS |

### API routes added
| Route | Integration | Auth |
|---|---|---|
| GET /observability | janmymf → fv-observability-handler | JWT |
| GET /observability/config | janmymf → fv-observability-handler | JWT |
| POST /observability/config | janmymf → fv-observability-handler | JWT |

### UI
- Nav: 📊 Observability under Account section (below 💰 Costs)
- Screen: buildObservability() — 100% pure DOM
- 4 tabs:
  - 📈 Overview: p50/p95/p99 latency cards + daily latency chart + token chart
  - 🔍 Traces: per-turn table with latency color coding, tokens, KB chunks, tools, cost
  - 🔧 Tools: tool usage breakdown by call count + token breakdown
  - ⚙️ Alerts: current alarm thresholds + live config form (save → updates DDB + CW alarms)
- Time range: 1h / 6h / 24h / 48h / 7d selector

## What fv-chat-handler v14 captures per turn

```python
{
  'input_tokens': int,        # tokens sent to Claude
  'output_tokens': int,       # tokens received from Claude  
  'total_tokens': int,        # sum
  'latency_ms': int,          # total orchestrate() wall time
  'planner_latency_ms': int,  # time in plan() call
  'answerer_latency_ms': int, # time in tool_answer_question()
  'kb_latency_ms': int,       # time in Bedrock KB retrieve()
  'kb_chunks_retrieved': int, # chunks returned by KB
  'tools_called': [str],      # list of tool names executed
  'model_id': str,            # Bedrock model used
  'status': 'ok'|'error',
  'error': str,               # if status=error
  'estimated_cost_usd': str,  # input*0.80/MTok + output*4.00/MTok
  'query_len': int,           # user query character length
  'answer_len': int,          # answer character length
  'short_term_turns': int,    # memory turns loaded
  'long_term_sessions': int,  # past sessions loaded
}
```

## CloudWatch metrics (namespace: FamilyVault/Chat)
- ChatLatencyMs (per-user + global)
- InputTokens (per-user)
- OutputTokens (per-user)
- TotalTokens (per-user + global)
- KBChunksRetrieved (per-user)
- ChatErrors (per-user + global)

## p50/p95/p99 calculation
Computed from raw latency values in ChatObservability DDB, sorted numerically.
Not from CloudWatch (CloudWatch percentile requires high-resolution metrics — DDB is simpler and cheaper).

## Important: SNS Email Confirmation
Check roy777rajat@gmail.com inbox for SNS subscription confirmation email.
Must click confirm before alert emails will be delivered.

## Next steps (Phase 2)
- Add LangSmith SDK wrapper around fv-chat-handler (after user_id isolation sprint)
- LangSmith gives: full prompt/output trace, per-span latency waterfall, eval datasets
- Use EU tenant or self-hosted to keep family document content private
