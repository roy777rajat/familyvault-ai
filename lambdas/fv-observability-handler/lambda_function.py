"""FamilyVault — Observability Handler v1
Provides:
  GET  /observability          - Live metrics + recent traces + stats
  GET  /observability/traces   - Paginated trace list with optional filter
  GET  /observability/config   - Current alert config
  POST /observability/config   - Update alert config + recreate CW alarms

All routes require JWT auth.
"""
import json, boto3, os
from datetime import datetime, timezone, timedelta
from boto3.dynamodb.conditions import Attr, Key
from decimal import Decimal

dynamodb = boto3.resource("dynamodb", region_name="eu-west-1")
cw       = boto3.client("cloudwatch", region_name="eu-west-1")
sns_arn  = os.environ.get("SNS_ARN", "arn:aws:sns:eu-west-1:141571819444:FamilyVaultAlerts")

def cors():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type,Authorization",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS"
    }

def decimal_default(obj):
    if isinstance(obj, Decimal): return float(obj)
    raise TypeError

def resp(status, body):
    return {
        "statusCode": status,
        "headers": cors(),
        "body": json.dumps(body, default=decimal_default)
    }

def get_user_id(event):
    """Extract user_id from JWT claims passed by API Gateway."""
    ctx = event.get("requestContext", {})
    claims = ctx.get("authorizer", {}).get("jwt", {}).get("claims", {})
    return claims.get("sub", "unknown")

# ─── PERCENTILE CALCULATION ───────────────────────────────────────────────────

def percentile(sorted_vals, p):
    if not sorted_vals: return 0
    idx = int(len(sorted_vals) * p / 100)
    idx = min(idx, len(sorted_vals) - 1)
    return sorted_vals[idx]

# ─── FETCH TRACES ─────────────────────────────────────────────────────────────

def fetch_traces(uid, hours=24, limit=200):
    """Fetch recent observations for a user from ChatObservability."""
    try:
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        table = dynamodb.Table("ChatObservability")
        result = table.query(
            IndexName="user_id-ts-index",
            KeyConditionExpression=Key("user_id").eq(uid) & Key("SK").gte(f"OBS#{since}"),
            ScanIndexForward=False,
            Limit=limit
        )
        return result.get("Items", [])
    except Exception as e:
        print(f"fetch_traces error: {e}")
        # Fallback: scan
        try:
            since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
            table = dynamodb.Table("ChatObservability")
            result = table.scan(
                FilterExpression=Attr("user_id").eq(uid) & Attr("ts").gte(since),
                Limit=limit
            )
            items = result.get("Items", [])
            items.sort(key=lambda x: x.get("ts", ""), reverse=True)
            return items
        except Exception as e2:
            print(f"fetch_traces scan error: {e2}")
            return []

# ─── COMPUTE STATS ────────────────────────────────────────────────────────────

def compute_stats(traces):
    if not traces:
        return {
            "total_chats": 0, "total_tokens": 0,
            "total_cost_usd": 0, "error_count": 0, "error_rate_pct": 0,
            "latency_p50": 0, "latency_p95": 0, "latency_p99": 0,
            "avg_input_tokens": 0, "avg_output_tokens": 0,
            "avg_kb_chunks": 0, "avg_latency_ms": 0,
        }

    latencies   = sorted([int(t.get("latency_ms", 0))  for t in traces])
    input_toks  = [int(t.get("input_tokens", 0))        for t in traces]
    output_toks = [int(t.get("output_tokens", 0))       for t in traces]
    total_toks  = [int(t.get("total_tokens", 0))        for t in traces]
    costs       = [float(t.get("estimated_cost_usd", 0)) for t in traces]
    errors      = [t for t in traces if t.get("status") == "error"]
    kb_chunks   = [int(t.get("kb_chunks_retrieved", 0)) for t in traces]
    n           = len(traces)

    return {
        "total_chats":       n,
        "total_tokens":      sum(total_toks),
        "total_input_tokens":  sum(input_toks),
        "total_output_tokens": sum(output_toks),
        "total_cost_usd":    round(sum(costs), 6),
        "error_count":       len(errors),
        "error_rate_pct":    round(len(errors) / n * 100, 1),
        "latency_p50":       percentile(latencies, 50),
        "latency_p95":       percentile(latencies, 95),
        "latency_p99":       percentile(latencies, 99),
        "avg_latency_ms":    int(sum(latencies) / n),
        "avg_input_tokens":  int(sum(input_toks) / n),
        "avg_output_tokens": int(sum(output_toks) / n),
        "avg_kb_chunks":     round(sum(kb_chunks) / n, 1),
        "avg_cost_usd":      round(sum(costs) / n, 6),
    }

# ─── GET OBSERVABILITY ────────────────────────────────────────────────────────

def handle_get(uid, params):
    hours  = int(params.get("hours", "24"))
    hours  = min(max(hours, 1), 168)  # 1h-7d
    traces = fetch_traces(uid, hours=hours, limit=500)

    stats = compute_stats(traces)

    # Daily breakdown (last 7 days)
    daily = {}
    for t in traces:
        day = (t.get("ts") or "")[:10]
        if not day: continue
        if day not in daily:
            daily[day] = {"date": day, "chats": 0, "tokens": 0, "errors": 0,
                          "cost_usd": 0, "latencies": []}
        daily[day]["chats"]    += 1
        daily[day]["tokens"]   += int(t.get("total_tokens", 0))
        daily[day]["errors"]   += 1 if t.get("status") == "error" else 0
        daily[day]["cost_usd"] += float(t.get("estimated_cost_usd", 0))
        daily[day]["latencies"].append(int(t.get("latency_ms", 0)))

    daily_list = []
    for day, d in sorted(daily.items()):
        lats = sorted(d.pop("latencies"))
        d["p50_ms"] = percentile(lats, 50)
        d["p95_ms"] = percentile(lats, 95)
        d["p99_ms"] = percentile(lats, 99)
        d["cost_usd"] = round(d["cost_usd"], 6)
        daily_list.append(d)

    # Tool usage breakdown
    tool_counts = {}
    for t in traces:
        for tool in t.get("tools_called", []):
            tool_counts[tool] = tool_counts.get(tool, 0) + 1

    # Recent traces (last 20)
    recent = []
    for t in traces[:20]:
        recent.append({
            "ts":             t.get("ts", ""),
            "session_id":     t.get("session_id", ""),
            "latency_ms":     int(t.get("latency_ms", 0)),
            "input_tokens":   int(t.get("input_tokens", 0)),
            "output_tokens":  int(t.get("output_tokens", 0)),
            "total_tokens":   int(t.get("total_tokens", 0)),
            "kb_chunks":      int(t.get("kb_chunks_retrieved", 0)),
            "tools_called":   t.get("tools_called", []),
            "status":         t.get("status", "ok"),
            "error":          t.get("error", ""),
            "cost_usd":       float(t.get("estimated_cost_usd", 0)),
            "query_len":      int(t.get("query_len", 0)),
        })

    # Load config
    config = get_config()

    return resp(200, {
        "stats":       stats,
        "daily":       daily_list,
        "tool_usage":  tool_counts,
        "recent":      recent,
        "config":      config,
        "hours":       hours,
        "generated_at": datetime.now(timezone.utc).isoformat()
    })

# ─── GET CONFIG ───────────────────────────────────────────────────────────────

def get_config():
    try:
        result = dynamodb.Table("ObservabilityConfig").get_item(
            Key={"PK": "CONFIG", "SK": "ALERTS"}
        )
        item = result.get("Item", {})
        return {
            "latency_warn_ms":       int(item.get("latency_warn_ms", 8000)),
            "latency_critical_ms":   int(item.get("latency_critical_ms", 15000)),
            "error_rate_threshold":  int(item.get("error_rate_threshold", 5)),
            "daily_token_limit":     int(item.get("daily_token_limit", 50000)),
            "daily_cost_limit_usd":  float(item.get("daily_cost_limit_usd", 2)),
            "alert_email":           str(item.get("alert_email", "")),
            "alerts_enabled":        bool(item.get("alerts_enabled", True)),
            "email_on_error":        bool(item.get("email_on_error", True)),
            "email_on_latency":      bool(item.get("email_on_latency", True)),
            "email_on_cost":         bool(item.get("email_on_cost", True)),
        }
    except Exception as e:
        print(f"get_config error: {e}")
        return {}

# ─── UPDATE CONFIG + ALARMS ───────────────────────────────────────────────────

def handle_update_config(uid, body):
    try:
        cfg = body
        # Validate
        latency_warn = int(cfg.get("latency_warn_ms", 8000))
        latency_crit = int(cfg.get("latency_critical_ms", 15000))
        error_thresh = int(cfg.get("error_rate_threshold", 5))
        daily_tokens = int(cfg.get("daily_token_limit", 50000))
        daily_cost   = float(cfg.get("daily_cost_limit_usd", 2))
        alerts_on    = bool(cfg.get("alerts_enabled", True))

        # Save to DDB
        dynamodb.Table("ObservabilityConfig").put_item(Item={
            "PK": "CONFIG", "SK": "ALERTS",
            "latency_warn_ms":      latency_warn,
            "latency_critical_ms":  latency_crit,
            "error_rate_threshold": error_thresh,
            "daily_token_limit":    daily_tokens,
            "daily_cost_limit_usd": str(daily_cost),
            "alert_email":          cfg.get("alert_email", ""),
            "alerts_enabled":       alerts_on,
            "email_on_error":       bool(cfg.get("email_on_error", True)),
            "email_on_latency":     bool(cfg.get("email_on_latency", True)),
            "email_on_cost":        bool(cfg.get("email_on_cost", True)),
            "updated_at":           datetime.now(timezone.utc).isoformat(),
            "updated_by":           uid,
        })

        # Recreate CloudWatch alarms with new thresholds
        alarm_actions = [sns_arn] if alerts_on else []

        if cfg.get("email_on_latency", True):
            cw.put_metric_alarm(
                AlarmName="FV-ChatLatency-High",
                AlarmDescription=f"FamilyVault chat avg latency >{latency_warn}ms",
                MetricName="ChatLatencyMs", Namespace="FamilyVault/Chat",
                Statistic="Average", Period=300, EvaluationPeriods=2,
                Threshold=latency_warn, ComparisonOperator="GreaterThanThreshold",
                AlarmActions=alarm_actions, TreatMissingData="notBreaching"
            )
            cw.put_metric_alarm(
                AlarmName="FV-ChatLatency-Critical",
                AlarmDescription=f"FamilyVault chat avg latency >{latency_crit}ms",
                MetricName="ChatLatencyMs", Namespace="FamilyVault/Chat",
                Statistic="Average", Period=300, EvaluationPeriods=1,
                Threshold=latency_crit, ComparisonOperator="GreaterThanThreshold",
                AlarmActions=alarm_actions, TreatMissingData="notBreaching"
            )

        if cfg.get("email_on_error", True):
            cw.put_metric_alarm(
                AlarmName="FV-ChatErrors-High",
                AlarmDescription=f"FamilyVault errors >{error_thresh} per hour",
                MetricName="ChatErrors", Namespace="FamilyVault/Chat",
                Statistic="Sum", Period=3600, EvaluationPeriods=1,
                Threshold=error_thresh, ComparisonOperator="GreaterThanThreshold",
                AlarmActions=alarm_actions, TreatMissingData="notBreaching"
            )

        if cfg.get("email_on_cost", True):
            cw.put_metric_alarm(
                AlarmName="FV-DailyTokens-High",
                AlarmDescription=f"FamilyVault daily tokens >{daily_tokens}",
                MetricName="TotalTokens", Namespace="FamilyVault/Chat",
                Statistic="Sum", Period=86400, EvaluationPeriods=1,
                Threshold=daily_tokens, ComparisonOperator="GreaterThanThreshold",
                AlarmActions=alarm_actions, TreatMissingData="notBreaching"
            )

        return resp(200, {"ok": True, "message": "Config saved and alarms updated"})

    except Exception as e:
        print(f"update_config error: {e}")
        return resp(500, {"error": str(e)})

# ─── ENTRY POINT ─────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET").upper()
    path   = event.get("rawPath", "/observability")
    params = event.get("queryStringParameters") or {}

    if method == "OPTIONS":
        return {"statusCode": 200, "headers": cors(), "body": ""}

    uid = get_user_id(event)

    if method == "GET" and "/config" in path:
        return resp(200, get_config())

    if method == "POST" and "/config" in path:
        try:
            body = json.loads(event.get("body", "{}") or "{}")
        except:
            return resp(400, {"error": "Invalid JSON"})
        return handle_update_config(uid, body)

    if method == "GET":
        return handle_get(uid, params)

    return resp(405, {"error": "Method not allowed"})
