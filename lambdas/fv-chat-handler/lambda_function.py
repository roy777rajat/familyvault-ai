"""FamilyVault AI — Chat Handler v14
What changed from v13:
  - OBSERVABILITY: Every chat turn writes a structured record to ChatObservability DynamoDB table
  - Tracks: input_tokens, output_tokens, latency_ms, kb_chunks_retrieved, tools_called,
    tool_latency_ms, model_id, session_id, user_id, status, estimated_cost_usd
  - Publishes CloudWatch custom metrics: ChatLatencyMs, InputTokens, OutputTokens,
    KBChunksRetrieved, ChatErrors, TotalTokens (namespace: FamilyVault/Chat)
  - Estimated cost: input $0.80/MTok, output $4.00/MTok (Claude Haiku 4.5 pricing)
"""
import json, boto3, os, uuid, re, time
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Attr

dynamodb = boto3.resource("dynamodb", region_name="eu-west-1")
bedrock  = boto3.client("bedrock-runtime", region_name="eu-west-1")
s3       = boto3.client("s3", region_name="eu-west-1")
cw       = boto3.client("cloudwatch", region_name="eu-west-1")

KB_ID          = os.environ.get("BEDROCK_KB_ID", "PYV06IINGT")
BUCKET         = os.environ.get("BUCKET", "family-docs-raw")
PLANNER_MODEL  = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
ANSWERER_MODEL = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"

# Cost per million tokens (Claude Haiku 4.5)
COST_INPUT_PER_MTOK  = 0.80
COST_OUTPUT_PER_MTOK = 4.00

WELCOME = (
    "Hello! I am FamilyVault AI \u2014 your personal document assistant. "
    "I can answer questions about your document contents, list everything stored in your vault, "
    "share secure download links, or handle all of these together in one request. "
    "Just ask naturally."
)

# ==============================================================
#  OBSERVABILITY
# ==============================================================

def estimate_cost(input_tokens, output_tokens):
    return round(
        (input_tokens / 1_000_000 * COST_INPUT_PER_MTOK) +
        (output_tokens / 1_000_000 * COST_OUTPUT_PER_MTOK), 8
    )

def write_observation(uid, sid, obs):
    """Write a structured observation to ChatObservability table."""
    try:
        ts = datetime.now(timezone.utc).isoformat()
        record = {
            "PK": f"USER#{uid}",
            "SK": f"OBS#{ts}#{str(uuid.uuid4())[:8]}",
            "user_id": uid,
            "session_id": sid,
            "ts": ts,
            "input_tokens":        int(obs.get("input_tokens", 0)),
            "output_tokens":       int(obs.get("output_tokens", 0)),
            "total_tokens":        int(obs.get("input_tokens", 0)) + int(obs.get("output_tokens", 0)),
            "latency_ms":          int(obs.get("latency_ms", 0)),
            "planner_latency_ms":  int(obs.get("planner_latency_ms", 0)),
            "answerer_latency_ms": int(obs.get("answerer_latency_ms", 0)),
            "kb_latency_ms":       int(obs.get("kb_latency_ms", 0)),
            "kb_chunks_retrieved": int(obs.get("kb_chunks_retrieved", 0)),
            "tools_called":        obs.get("tools_called", []),
            "model_id":            obs.get("model_id", ANSWERER_MODEL),
            "status":              obs.get("status", "ok"),
            "error":               obs.get("error", ""),
            "estimated_cost_usd":  str(estimate_cost(
                                       obs.get("input_tokens", 0),
                                       obs.get("output_tokens", 0))),
            "query_len":           int(obs.get("query_len", 0)),
            "answer_len":          int(obs.get("answer_len", 0)),
            "short_term_turns":    int(obs.get("short_term_turns", 0)),
            "long_term_sessions":  int(obs.get("long_term_sessions", 0)),
        }
        dynamodb.Table("ChatObservability").put_item(Item=record)
        print(f"OBS written: latency={record['latency_ms']}ms tokens={record['total_tokens']}")
    except Exception as e:
        print(f"OBS write error: {e}")

def publish_metrics(uid, obs):
    """Publish custom CloudWatch metrics."""
    try:
        dims = [{"Name": "UserId", "Value": uid}]
        metrics = [
            {"MetricName": "ChatLatencyMs",       "Value": float(obs.get("latency_ms", 0)),          "Unit": "Milliseconds", "Dimensions": dims},
            {"MetricName": "InputTokens",          "Value": float(obs.get("input_tokens", 0)),         "Unit": "Count",        "Dimensions": dims},
            {"MetricName": "OutputTokens",         "Value": float(obs.get("output_tokens", 0)),        "Unit": "Count",        "Dimensions": dims},
            {"MetricName": "TotalTokens",          "Value": float(obs.get("input_tokens", 0) + obs.get("output_tokens", 0)), "Unit": "Count", "Dimensions": dims},
            {"MetricName": "KBChunksRetrieved",    "Value": float(obs.get("kb_chunks_retrieved", 0)),  "Unit": "Count",        "Dimensions": dims},
            {"MetricName": "ChatErrors",           "Value": 1.0 if obs.get("status") == "error" else 0.0, "Unit": "Count", "Dimensions": dims},
        ]
        # Also publish without dimension for account-wide aggregates
        global_metrics = [
            {"MetricName": "ChatLatencyMs",  "Value": float(obs.get("latency_ms", 0)),  "Unit": "Milliseconds"},
            {"MetricName": "TotalTokens",    "Value": float(obs.get("input_tokens", 0) + obs.get("output_tokens", 0)), "Unit": "Count"},
            {"MetricName": "ChatErrors",     "Value": 1.0 if obs.get("status") == "error" else 0.0, "Unit": "Count"},
        ]
        cw.put_metric_data(Namespace="FamilyVault/Chat", MetricData=metrics + global_metrics)
        print(f"CW metrics published: latency={obs.get('latency_ms')}ms")
    except Exception as e:
        print(f"CW metrics error: {e}")

# ==============================================================
#  MEMORY LAYER
# ==============================================================

def load_short_term_memory(uid, sid, limit=6):
    try:
        table = dynamodb.Table("ChatSessions")
        result = table.scan(
            FilterExpression=Attr("PK").eq("USER#" + uid)
                           & Attr("session_id").eq(sid)
                           & Attr("deleted").ne(True)
        )
        items = result.get("Items", [])
        items.sort(key=lambda x: x.get("created_at", ""))
        items = items[-limit:]
        messages = []
        for item in items:
            q = (item.get("question") or "").strip()
            a = (item.get("answer") or "").strip()
            if q:
                messages.append({"role": "user",      "content": q})
            if a and not a.startswith("[Document list"):
                messages.append({"role": "assistant", "content": a})
        print(f"Short-term memory: {len(items)} turns for session {sid}")
        return messages
    except Exception as e:
        print(f"Short-term memory error: {e}")
        return []


def load_long_term_memory(uid, current_sid, max_sessions=3):
    try:
        table = dynamodb.Table("ChatSessions")
        result = table.scan(
            FilterExpression=Attr("PK").eq("USER#" + uid) & Attr("deleted").ne(True)
        )
        items = result.get("Items", [])
        sessions = {}
        for item in items:
            s = item.get("session_id", "")
            if not s or s == current_sid:
                continue
            sessions.setdefault(s, []).append(item)
        if not sessions:
            return ""
        def session_ts(items_list):
            return max((i.get("created_at", "") for i in items_list), default="")
        sorted_sessions = sorted(sessions.items(), key=lambda kv: session_ts(kv[1]), reverse=True)[:max_sessions]
        lines = ["=== Past conversations (long-term memory) ==="]
        for sess_id, sess_items in sorted_sessions:
            sess_items.sort(key=lambda x: x.get("created_at", ""))
            first_ts = sess_items[0].get("created_at", "")
            try:
                date_label = datetime.fromisoformat(first_ts.replace("Z", "+00:00")).strftime("%d %b %Y")
            except:
                date_label = first_ts[:10]
            lines.append(f"\n[Session - {date_label}]")
            for item in sess_items[-4:]:
                q = (item.get("question") or "").strip()
                a = (item.get("answer") or "").strip()
                sources = item.get("sources", [])
                if q and a and not a.startswith("[Document list"):
                    lines.append(f"Q: {q}")
                    a_short = a[:300] + "..." if len(a) > 300 else a
                    lines.append(f"A: {a_short}")
                    if sources:
                        lines.append(f"   (Sources: {', '.join(sources[:3])})")
        if len(lines) <= 1:
            return ""
        print(f"Long-term memory: {len(sorted_sessions)} past sessions")
        return "\n".join(lines)
    except Exception as e:
        print(f"Long-term memory error: {e}")
        return ""

# ==============================================================
#  HELPERS  (unchanged from v13)
# ==============================================================

def get_user_docs(uid):
    table = dynamodb.Table("DocumentMetadata")
    result = table.scan(FilterExpression=Attr("user_id").eq(uid) & Attr("deleted").ne(True))
    docs = result.get("Items", [])
    while "LastEvaluatedKey" in result:
        result = table.scan(
            FilterExpression=Attr("user_id").eq(uid) & Attr("deleted").ne(True),
            ExclusiveStartKey=result["LastEvaluatedKey"]
        )
        docs.extend(result.get("Items", []))
    return docs

def doc_category(filename):
    f = (filename or "").lower()
    if any(x in f for x in ["pan","passport","aadhaar","uan","birth","voter"]): return "Identity"
    if any(x in f for x in ["sem","certificate","btech","degree","marksheet","gyano","form"]): return "Academic"
    if any(x in f for x in ["tcs","offer","appoint","salary","payslip","resume","increment"]): return "Employment"
    if any(x in f for x in ["statement","invoice","laptop"]): return "Financial"
    if any(x in f for x in ["policy","insurance","kit"]): return "Insurance"
    return "Other"

def source_label(doc):
    if doc.get("sender_email"):
        m = re.search(r'<(.+?)>', doc["sender_email"])
        return m.group(1) if m else doc["sender_email"]
    return "Uploaded" if doc.get("uploaded_at") else "\u2014"

def fmt_date(iso):
    if not iso: return "\u2014"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d %b %Y")
    except:
        return iso[:10]

def sort_docs(docs):
    return sorted(docs, key=lambda x: x.get("received_at") or x.get("uploaded_at") or "", reverse=True)

def make_presigned(s3_key, filename, expiry=86400):
    try:
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": BUCKET, "Key": s3_key,
                    "ResponseContentDisposition": f'attachment; filename="{filename}"'},
            ExpiresIn=expiry
        )
    except Exception as e:
        print(f"Presign err {s3_key}: {e}")
        return None

def build_doc_table(docs, filter_label=None):
    title = (f"Documents matching '{filter_label}' ({len(docs)} found)"
             if filter_label else f"Your Documents ({len(docs)} total)")
    rows = ""
    for i, d in enumerate(sort_docs(docs), 1):
        fname = d.get("filename", "\u2014")
        cat   = doc_category(fname)
        src   = source_label(d)
        date  = fmt_date(d.get("received_at") or d.get("uploaded_at", ""))
        st    = d.get("status", "\u2014")
        sc    = "st-ok" if st == "INDEXED" else "st-proc" if "PROCESS" in st else "st-pend"
        sl    = "Indexed" if st == "INDEXED" else "Processing" if "PROCESS" in st else st
        rows += (f"<tr><td class='tsl'>{i}</td><td class='tfn'>{fname}</td>"
                 f"<td class='tca'>{cat}</td><td class='tsr'>{src}</td>"
                 f"<td class='tdt'>{date}</td><td><span class='tbl-st {sc}'>{sl}</span></td></tr>")
    return (f'<div class="doc-table-wrap"><div class="doc-table-hd">{title}</div>'
            f'<div class="doc-table-scroll"><table class="doc-table">'
            f'<thead><tr><th>Sl</th><th>Document Name</th><th>Category</th>'
            f'<th>Source</th><th>Date</th><th>Status</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div></div>')

def save_turn(uid, sid, question, answer, sources=None):
    try:
        dynamodb.Table("ChatSessions").put_item(Item={
            "PK": "USER#" + uid,
            "SK": "SESSION#" + sid + "#TURN#" + str(uuid.uuid4()),
            "session_id": sid,
            "question": question,
            "answer": answer[:800],
            "sources": sources or [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "deleted": False
        })
    except Exception as e:
        print(f"DDB save: {e}")

# ==============================================================
#  PLANNER (unchanged from v13)
# ==============================================================

PLANNER_SYSTEM = """You are the Planner for FamilyVault AI, a personal document assistant.
Your job: read the user's LATEST question and produce a JSON execution plan.
IMPORTANT: Use conversation history to resolve follow-up references.

Available tools:
1. document_list    — Fetch user document list from DynamoDB
2. search_documents — Semantic search via Bedrock KB
3. download_document— Generate presigned download links
4. answer_question  — Generate natural language answer
5. out_of_scope     — Unrelated to documents

RULES:
- Return ONLY valid JSON array. No markdown, no explanation.
- Each step: {"tool": "<n>", "query": "<search string>", "reason": "<why>"}
- Include download_document ONLY if user EXPLICITLY asked for link/download/url.
- Maximum 4 steps.

Examples:
User: "What is my PAN card number?"
Plan: [{"tool":"search_documents","query":"PAN card number","reason":"Find PAN"},{"tool":"answer_question","reason":"Answer"}]

User: "List all my documents"
Plan: [{"tool":"document_list","reason":"Show inventory"}]

User: "Share PAN card details and download link"
Plan: [{"tool":"search_documents","query":"PAN card","reason":"Find PAN"},{"tool":"answer_question","reason":"Share details"},{"tool":"download_document","reason":"User asked for link"}]

User: "What is the weather today?"
Plan: [{"tool":"out_of_scope"}]"""


def plan(query, short_term_history):
    try:
        messages = list(short_term_history)
        messages.append({"role": "user", "content": query})
        resp = bedrock.invoke_model(
            modelId=PLANNER_MODEL,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 512,
                "system": PLANNER_SYSTEM,
                "messages": messages
            })
        )
        raw = json.loads(resp["body"].read())["content"][0]["text"].strip()
        raw = re.sub(r'^```[a-z]*\n?', '', raw, flags=re.M)
        raw = re.sub(r'\n?```$', '', raw, flags=re.M)
        steps = json.loads(raw)
        print(f"Plan: {steps}")
        return steps
    except Exception as e:
        print(f"Planner error: {e}")
        return [{"tool": "search_documents", "query": query, "reason": "fallback"},
                {"tool": "answer_question", "reason": "fallback"}]

# ==============================================================
#  TOOL: search_documents
# ==============================================================

def tool_search_documents(query, min_score=0.50):
    kb_client = boto3.client("bedrock-agent-runtime", region_name="eu-west-1")
    try:
        res = kb_client.retrieve(
            knowledgeBaseId=KB_ID,
            retrievalQuery={"text": query},
            retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 8}}
        )
    except Exception as e:
        print(f"KB error: {e}")
        return [], []
    raw_results = res.get("retrievalResults", [])
    chunks, sources, seen = [], [], set()
    for r in raw_results:
        score = r.get("score", 0)
        if score < min_score: continue
        text = r.get("content", {}).get("text", "") or r.get("metadata", {}).get("text", "")
        if not text or not text.strip(): continue
        sig = text.strip()[:120]
        if sig in seen: continue
        seen.add(sig)
        fname = r.get("metadata", {}).get("filename", "")
        if not fname:
            uri = r.get("location", {}).get("s3Location", {}).get("uri", "")
            if uri: fname = uri.split("/")[-1]
        chunks.append({"text": text.strip(), "score": round(score, 4), "filename": fname})
        if fname and fname not in sources: sources.append(fname)
    chunks.sort(key=lambda x: -x["score"])
    return chunks, sources

# ==============================================================
#  TOOL: document_list
# ==============================================================

def tool_document_list(uid, filter_query=None):
    all_docs = get_user_docs(uid)
    if not filter_query or not filter_query.strip():
        return all_docs, False
    fq = filter_query.lower().strip()
    stops = {"the","a","an","of","in","for","and","or","my","all","show","list","have","do","i","any","some","about"}
    keywords = [w for w in re.split(r'\W+', fq) if len(w) > 1 and w not in stops]
    if not keywords: return all_docs, False
    matched = [d for d in all_docs if any(
        kw in (f"{(d.get('filename','') or '').lower()} {doc_category(d.get('filename','')).lower()} "
               f"{(d.get('subject','') or '').lower()} {(d.get('sender_email','') or '').lower()}")
        for kw in keywords
    )]
    return matched, True

# ==============================================================
#  TOOL: download_document
# ==============================================================

def tool_download_document(all_docs, grounded_sources, search_queries=None):
    if not grounded_sources: return []
    query_keywords = set()
    if search_queries:
        stops = {"the","for","and","of","a","an","in","on","at","to","with","details","number",
                 "what","is","my","their","from","about","show","find","get","tell","please","can","you"}
        for q in search_queries:
            for w in re.split(r'\W+', q.lower()):
                if len(w) > 2 and w not in stops: query_keywords.add(w)
    scored_sources = []
    for src in grounded_sources:
        src_lower = src.lower()
        if query_keywords:
            kw_matches = sum(1 for kw in query_keywords if kw in src_lower)
            if kw_matches > 0: scored_sources.append((kw_matches, src))
        else:
            scored_sources.append((0, src)); break
    if not scored_sources and grounded_sources:
        scored_sources = [(0, grounded_sources[0])]
    scored_sources.sort(key=lambda x: -x[0])
    target_sources = [s for _, s in scored_sources]
    matched = []
    for doc in all_docs:
        fname = (doc.get("filename") or "").lower().strip()
        for src in target_sources:
            if fname == src.lower() or fname in src.lower() or src.lower() in fname:
                if doc not in matched: matched.append(doc); break
    links = []
    for doc in matched[:5]:
        s3_key = doc.get("s3_key", "")
        fname  = doc.get("filename", "document")
        if s3_key:
            url = make_presigned(s3_key, fname)
            if url: links.append({"filename": fname, "url": url})
    return links

# ==============================================================
#  TOOL: answer_question  — now counts tokens
# ==============================================================

def tool_answer_question(query, all_chunks, push_fn, short_term_history, long_term_summary, obs):
    """
    Streams an answer. Now returns (text, input_tokens, output_tokens).
    obs dict is mutated to accumulate token counts.
    """
    if not all_chunks:
        rag_context = "No relevant document content was found for this query."
    else:
        ctx_parts = []
        for ch in all_chunks[:6]:
            fname = ch.get("filename", "")
            score = ch.get("score", 0)
            src   = f"[Source: {fname} | Score: {score:.3f}]" if fname else ""
            ctx_parts.append(f"{src}\n{ch['text']}")
        rag_context = "\n\n---\n\n".join(ctx_parts)

    long_term_block = ""
    if long_term_summary:
        long_term_block = f"\n{long_term_summary}\n\nUse the above past conversations as BACKGROUND CONTEXT only.\n"

    system = f"""You are FamilyVault AI \u2014 a warm, professional personal document assistant.
{long_term_block}
RETRIEVED DOCUMENT CONTENT:
{rag_context}

STRICT RULES:
1. Answer ONLY from retrieved document content. Never invent facts.
2. Be specific \u2014 quote exact values when found.
3. Mention which document the info comes from.
4. If content doesn't answer: say warmly that you couldn't find it.
5. NEVER use markdown bold (**) or bullet stars. Plain sentences only.
6. NEVER say "I don't have download links".
7. NEVER start with "Based on retrieved content".
8. Keep responses concise, warm, professional."""

    messages = list(short_term_history)
    messages.append({"role": "user", "content": query})

    full = ""
    input_tokens = 0
    output_tokens = 0
    t0 = time.time()
    try:
        stream = bedrock.invoke_model_with_response_stream(
            modelId=ANSWERER_MODEL,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 900,
                "system": system,
                "messages": messages
            })
        )
        for ev in stream["body"]:
            chunk = json.loads(ev["chunk"]["bytes"])
            if chunk.get("type") == "content_block_delta":
                token = chunk.get("delta", {}).get("text", "")
                if token:
                    full += token
                    push_fn({"type": "token", "content": token})
            # Extract token usage from message_delta event
            elif chunk.get("type") == "message_start":
                usage = chunk.get("message", {}).get("usage", {})
                input_tokens += usage.get("input_tokens", 0)
            elif chunk.get("type") == "message_delta":
                usage = chunk.get("usage", {})
                output_tokens += usage.get("output_tokens", 0)
    except Exception as e:
        print(f"Answerer error: {e}")
        msg = "Sorry, I had trouble generating a response. Please try again."
        push_fn({"type": "token", "content": msg})
        full = msg
        obs["status"] = "error"
        obs["error"] = str(e)

    obs["input_tokens"]  = obs.get("input_tokens", 0) + input_tokens
    obs["output_tokens"] = obs.get("output_tokens", 0) + output_tokens
    obs["answerer_latency_ms"] = int((time.time() - t0) * 1000)
    return full

# ==============================================================
#  ORCHESTRATOR — instrumented
# ==============================================================

def orchestrate(query, uid, sid, push):
    t_start = time.time()
    obs = {
        "input_tokens": 0, "output_tokens": 0,
        "latency_ms": 0, "planner_latency_ms": 0,
        "answerer_latency_ms": 0, "kb_latency_ms": 0,
        "kb_chunks_retrieved": 0, "tools_called": [],
        "model_id": ANSWERER_MODEL, "status": "ok", "error": "",
        "query_len": len(query), "answer_len": 0,
        "short_term_turns": 0, "long_term_sessions": 0,
    }

    push({"type": "status", "message": "Recalling conversation history..."})
    short_term = load_short_term_memory(uid, sid, limit=6)
    long_term  = load_long_term_memory(uid, sid, max_sessions=3)
    obs["short_term_turns"]   = len(short_term) // 2
    obs["long_term_sessions"] = long_term.count("[Session")

    push({"type": "status", "message": "Understanding your request..."})
    t_plan = time.time()
    steps = plan(query, short_term)
    obs["planner_latency_ms"] = int((time.time() - t_plan) * 1000)
    obs["tools_called"] = [s.get("tool") for s in steps]

    push({"type": "scratchpad", "event": "plan",
          "content": "Plan:\n" + "\n".join(
              f"  {i}. {s.get('tool')}" + (f' query={s[\"query\"]}' if s.get('query') else '')
              for i, s in enumerate(steps, 1)
          )})

    all_chunks, all_sources, score_map = [], [], {}
    all_docs, full_reply, search_queries = None, "", []

    has_list     = any(s["tool"] == "document_list"    for s in steps)
    has_download = any(s["tool"] == "download_document" for s in steps)

    if has_list or has_download:
        push({"type": "status", "message": "Fetching your documents..."})
        all_docs = get_user_docs(uid)

    for step in steps:
        tool = step.get("tool")
        print(f"Orchestrator -> {tool}")
        push({"type": "scratchpad", "event": "step",
              "content": f"Executing: {tool} ({(step.get('query') or step.get('filter') or step.get('reason',''))[:80]})"})

        if tool == "document_list":
            filter_q = step.get("filter", "").strip()
            list_docs, is_filtered = tool_document_list(uid, filter_q)
            if not all_docs: all_docs = get_user_docs(uid)
            if not list_docs and is_filtered:
                push({"type": "token", "content": f"I couldn't find any documents matching '{filter_q}' in your vault."})
            elif not list_docs:
                push({"type": "token", "content": "I don't see any documents in your vault yet. Upload documents using the Upload section."})
            else:
                push({"type": "clear_streaming"})
                push({"type": "html", "content": build_doc_table(list_docs, filter_q if is_filtered else None)})
                if not any(s["tool"] in ("search_documents","answer_question","download_document") for s in steps):
                    push({"type": "scratchpad", "event": "done", "content": ""})
                    push({"type": "final", "sources": [], "session_id": sid})
                    save_turn(uid, sid, query, f"[Document list: {len(list_docs)} docs filter='{filter_q}']")
                    obs["latency_ms"] = int((time.time() - t_start) * 1000)
                    write_observation(uid, sid, obs)
                    publish_metrics(uid, obs)
                    return
                push({"type": "token", "content": "\n"})

        elif tool == "search_documents":
            search_query = step.get("query", query)
            search_queries.append(search_query)
            push({"type": "status", "message": f"Searching: {search_query[:50]}..."})
            t_kb = time.time()
            chunks, sources = tool_search_documents(search_query)
            obs["kb_latency_ms"] += int((time.time() - t_kb) * 1000)
            obs["kb_chunks_retrieved"] += len(chunks)
            existing_sigs = {ck["text"][:120] for ck in all_chunks}
            for ch in chunks:
                if ch["text"][:120] not in existing_sigs:
                    all_chunks.append(ch)
                    existing_sigs.add(ch["text"][:120])
                fn, sc = ch.get("filename",""), ch.get("score",0)
                if fn: score_map[fn] = max(score_map.get(fn, 0), sc)
            for src in sources:
                if src not in all_sources: all_sources.append(src)
            push({"type": "scratchpad", "event": "result",
                  "content": f"  Found {len(chunks)} chunks from: {', '.join(sources) if sources else 'no matches'}"})

        elif tool == "answer_question":
            push({"type": "status", "message": "Preparing answer..."})
            full_reply += tool_answer_question(
                query, all_chunks, push, short_term, long_term, obs
            )

        elif tool == "download_document":
            if not all_docs: all_docs = get_user_docs(uid)
            links = tool_download_document(all_docs, all_sources, search_queries)
            if not links:
                msg = "\n\nRegarding download links: I wasn't able to identify the specific document. Could you mention the name or type?"
                push({"type": "token", "content": msg})
                full_reply += msg
            else:
                count = len(links)
                intro = f"\n\nHere {'is' if count==1 else 'are'} the secure download link{'s' if count>1 else ''} (valid 24h):"
                push({"type": "token", "content": intro})
                full_reply += intro
                scored_sources = [f"{s} ({score_map.get(s,0):.2f})" if score_map.get(s) else s for s in all_sources]
                obs["latency_ms"]  = int((time.time() - t_start) * 1000)
                obs["answer_len"]  = len(full_reply)
                write_observation(uid, sid, obs)
                publish_metrics(uid, obs)
                push({"type": "scratchpad", "event": "done", "content": ""})
                push({"type": "final", "sources": scored_sources, "session_id": sid})
                push({"type": "links", "links": links})
                save_turn(uid, sid, query, full_reply, sources=all_sources)
                return

        elif tool == "out_of_scope":
            reply = ("That is a bit outside what I can help with. "
                     "I am best at answering questions about your stored documents, "
                     "listing files, or sharing download links. Is there something document-related I can help with?")
            push({"type": "token", "content": reply})
            obs["latency_ms"] = int((time.time() - t_start) * 1000)
            obs["answer_len"] = len(reply)
            write_observation(uid, sid, obs)
            publish_metrics(uid, obs)
            push({"type": "final", "sources": [], "session_id": sid})
            save_turn(uid, sid, query, reply)
            return

    # Finish
    obs["latency_ms"] = int((time.time() - t_start) * 1000)
    obs["answer_len"] = len(full_reply)
    write_observation(uid, sid, obs)
    publish_metrics(uid, obs)

    scored_sources = [f"{s} ({score_map.get(s,0):.2f})" if score_map.get(s) else s for s in all_sources]
    push({"type": "scratchpad", "event": "done", "content": ""})
    push({"type": "final", "sources": scored_sources, "session_id": sid})
    save_turn(uid, sid, query, full_reply or "[Document list shown]", sources=all_sources)

# ==============================================================
#  LAMBDA ENTRY POINT
# ==============================================================

def lambda_handler(event, context):
    route  = event.get("requestContext", {}).get("routeKey", "$default")
    cid    = event.get("requestContext", {}).get("connectionId", "")
    domain = event.get("requestContext", {}).get("domainName", "")
    stage  = event.get("requestContext", {}).get("stage", "production")

    if route == "$connect":    return {"statusCode": 200, "body": "Connected"}
    if route == "$disconnect": return {"statusCode": 200, "body": "Disconnected"}

    body  = json.loads(event.get("body", "{}") or "{}")
    query = body.get("query", body.get("message", "")).strip()
    sid   = body.get("session_id", str(uuid.uuid4()))
    uid   = body.get("user_id", "unknown")

    apigw = boto3.client("apigatewaymanagementapi", endpoint_url=f"https://{domain}/{stage}")

    def push(data):
        try:
            payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
            apigw.post_to_connection(ConnectionId=cid, Data=payload)
        except Exception as e:
            print(f"Push FAILED type={data.get('type','?')} err={e}")

    if not query or query.lower() in ("hi","hello","hey","start"):
        for i in range(0, len(WELCOME), 8):
            push({"type": "token", "content": WELCOME[i:i+8]})
        push({"type": "final", "sources": [], "session_id": sid})
        return {"statusCode": 200, "body": "OK"}

    try:
        orchestrate(query, uid, sid, push)
    except Exception as e:
        print(f"Orchestrator error: {e}")
        push({"type": "error", "message": "Something went wrong. Please try again."})
        # Write error observation
        write_observation(uid, sid, {"status": "error", "error": str(e), "tools_called": []})
        publish_metrics(uid, {"status": "error", "input_tokens": 0, "output_tokens": 0, "latency_ms": 0})

    return {"statusCode": 200, "body": "OK"}
