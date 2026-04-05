"""FamilyVault AI — Chat Handler v15

MAJOR REWRITE — 3-layer orchestrator replacing flat planner:

Layer 1 — Decomposer
  Reads raw user message and splits it into N independent sub-tasks.
  Each sub-task has: intent_type + target + params.
  Intent types: exact_download, semantic_download, content_question,
                list_documents, send_email, delete_document, out_of_scope

Layer 2 — Sub-task Router
  Each intent_type maps to a fixed, hardcoded tool sequence.
  No LLM decides which tools to call — the type determines the sequence.

Layer 3 — Task Executor
  Runs sub-tasks in priority order (non-destructive first, destructive last).
  Each sub-task has FULLY ISOLATED state — no source leakage between tasks.

Multi-turn tasks (send_email, delete_document):
  Stored in DDB ChatSessions as pending_task.
  On next user message, executor checks for pending task first.
  Checkpoint (CP) flow:
    send_email:      CP1=collect info → CP2=show draft + approve → CP3=execute
    delete_document: CP1=confirm docs → CP2=explicit approval → CP3=execute
"""
import json, boto3, os, uuid, re, time, urllib.request
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Attr

dynamodb = boto3.resource("dynamodb", region_name="eu-west-1")
bedrock  = boto3.client("bedrock-runtime", region_name="eu-west-1")
s3       = boto3.client("s3", region_name="eu-west-1")
cw       = boto3.client("cloudwatch", region_name="eu-west-1")

KB_ID           = os.environ.get("BEDROCK_KB_ID", "PYV06IINGT")
BUCKET          = os.environ.get("BUCKET", "family-docs-raw")
DECOMPOSER_MODEL = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
ANSWERER_MODEL   = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
EMAIL_LAMBDA_URL = os.environ.get("EMAIL_LAMBDA_URL", "https://1oj10740w0.execute-api.eu-west-1.amazonaws.com")
DELETE_LAMBDA_URL = os.environ.get("DELETE_LAMBDA_URL", "https://1oj10740w0.execute-api.eu-west-1.amazonaws.com")

COST_INPUT_PER_MTOK  = 0.80
COST_OUTPUT_PER_MTOK = 4.00

WELCOME = (
    "Hello! I am FamilyVault AI \u2014 your personal document assistant. "
    "I can answer questions about your documents, list your vault, share download links, "
    "send documents by email, or delete files. Just ask naturally."
)

TONES = ["Professional", "Friendly", "Brief", "Formal", "Warm"]

# ================================================================
#  OBSERVABILITY
# ================================================================

def estimate_cost(inp, out):
    return round((inp / 1_000_000 * COST_INPUT_PER_MTOK) + (out / 1_000_000 * COST_OUTPUT_PER_MTOK), 8)

def write_observation(uid, sid, obs):
    try:
        ts = datetime.now(timezone.utc).isoformat()
        dynamodb.Table("ChatObservability").put_item(Item={
            "PK": "USER#" + uid, "SK": "OBS#" + ts + "#" + str(uuid.uuid4())[:8],
            "user_id": uid, "session_id": sid, "ts": ts,
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
            "estimated_cost_usd":  str(estimate_cost(obs.get("input_tokens", 0), obs.get("output_tokens", 0))),
            "query_len":           int(obs.get("query_len", 0)),
            "answer_len":          int(obs.get("answer_len", 0)),
            "short_term_turns":    int(obs.get("short_term_turns", 0)),
            "long_term_sessions":  int(obs.get("long_term_sessions", 0)),
        })
        print("OBS: latency=" + str(obs.get("latency_ms")) + "ms tokens=" + str(int(obs.get("input_tokens",0))+int(obs.get("output_tokens",0))))
    except Exception as e:
        print("OBS error: " + str(e))

def publish_metrics(uid, obs):
    try:
        dims = [{"Name": "UserId", "Value": uid}]
        inp = float(obs.get("input_tokens", 0))
        out = float(obs.get("output_tokens", 0))
        lat = float(obs.get("latency_ms", 0))
        err_val = 1.0 if obs.get("status") == "error" else 0.0
        cw.put_metric_data(Namespace="FamilyVault/Chat", MetricData=[
            {"MetricName": "ChatLatencyMs",    "Value": lat,       "Unit": "Milliseconds", "Dimensions": dims},
            {"MetricName": "InputTokens",       "Value": inp,       "Unit": "Count",        "Dimensions": dims},
            {"MetricName": "OutputTokens",      "Value": out,       "Unit": "Count",        "Dimensions": dims},
            {"MetricName": "TotalTokens",       "Value": inp + out, "Unit": "Count",        "Dimensions": dims},
            {"MetricName": "KBChunksRetrieved", "Value": float(obs.get("kb_chunks_retrieved", 0)), "Unit": "Count", "Dimensions": dims},
            {"MetricName": "ChatErrors",        "Value": err_val,   "Unit": "Count",        "Dimensions": dims},
            {"MetricName": "ChatLatencyMs",     "Value": lat,       "Unit": "Milliseconds"},
            {"MetricName": "TotalTokens",       "Value": inp + out, "Unit": "Count"},
            {"MetricName": "ChatErrors",        "Value": err_val,   "Unit": "Count"},
        ])
        print("CW metrics published")
    except Exception as e:
        print("CW metrics error: " + str(e))

# ================================================================
#  MEMORY LAYER
# ================================================================

def load_short_term_memory(uid, sid, limit=6):
    try:
        table = dynamodb.Table("ChatSessions")
        result = table.scan(
            FilterExpression=Attr("PK").eq("USER#" + uid)
                           & Attr("session_id").eq(sid)
                           & Attr("deleted").ne(True)
        )
        items = sorted(result.get("Items", []), key=lambda x: x.get("created_at", ""))[-limit:]
        messages = []
        for item in items:
            q = (item.get("question") or "").strip()
            a = (item.get("answer") or "").strip()
            if q: messages.append({"role": "user", "content": q})
            if a and not a.startswith("["):
                messages.append({"role": "assistant", "content": a})
        print("STM: " + str(len(items)) + " turns")
        return messages
    except Exception as e:
        print("STM error: " + str(e))
        return []

def load_long_term_memory(uid, current_sid, max_sessions=3):
    try:
        result = dynamodb.Table("ChatSessions").scan(
            FilterExpression=Attr("PK").eq("USER#" + uid) & Attr("deleted").ne(True)
        )
        sessions = {}
        for item in result.get("Items", []):
            s = item.get("session_id", "")
            if not s or s == current_sid: continue
            sessions.setdefault(s, []).append(item)
        if not sessions: return ""
        def session_ts(il): return max((i.get("created_at","") for i in il), default="")
        top = sorted(sessions.items(), key=lambda kv: session_ts(kv[1]), reverse=True)[:max_sessions]
        lines = ["=== Past conversations ==="]
        for _, sess_items in top:
            sess_items.sort(key=lambda x: x.get("created_at",""))
            ts = sess_items[0].get("created_at","")
            try: dl = datetime.fromisoformat(ts.replace("Z","+00:00")).strftime("%d %b %Y")
            except: dl = ts[:10]
            lines.append("\n[Session - " + dl + "]")
            for item in sess_items[-4:]:
                q = (item.get("question") or "").strip()
                a = (item.get("answer") or "").strip()
                if q and a and not a.startswith("["):
                    lines.append("Q: " + q)
                    lines.append("A: " + (a[:300] + "..." if len(a) > 300 else a))
        if len(lines) <= 1: return ""
        print("LTM: " + str(len(top)) + " sessions")
        return "\n".join(lines)
    except Exception as e:
        print("LTM error: " + str(e))
        return ""

# ================================================================
#  PENDING TASK STATE  (multi-turn tasks stored in DDB)
# ================================================================

def save_pending_task(uid, sid, task_state):
    """Persist a mid-flight multi-turn task to DDB so it survives across WS connections."""
    try:
        dynamodb.Table("ChatSessions").put_item(Item={
            "PK": "USER#" + uid,
            "SK": "PENDING#" + sid,
            "session_id": sid,
            "pending_task": json.dumps(task_state),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "deleted": False,
        })
        print("Pending task saved: " + task_state.get("intent_type","?"))
    except Exception as e:
        print("Save pending error: " + str(e))

def load_pending_task(uid, sid):
    """Load a pending multi-turn task if one exists for this session."""
    try:
        result = dynamodb.Table("ChatSessions").get_item(Key={"PK": "USER#" + uid, "SK": "PENDING#" + sid})
        item = result.get("Item")
        if item and item.get("pending_task"):
            task = json.loads(item["pending_task"])
            print("Pending task found: " + task.get("intent_type","?") + " stage=" + task.get("stage","?"))
            return task
    except Exception as e:
        print("Load pending error: " + str(e))
    return None

def clear_pending_task(uid, sid):
    """Remove the pending task record from DDB once completed or cancelled."""
    try:
        dynamodb.Table("ChatSessions").delete_item(Key={"PK": "USER#" + uid, "SK": "PENDING#" + sid})
        print("Pending task cleared")
    except Exception as e:
        print("Clear pending error: " + str(e))

# ================================================================
#  HELPERS
# ================================================================

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

def doc_category(f):
    f = (f or "").lower()
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
    try: return datetime.fromisoformat(iso.replace("Z","+00:00")).strftime("%d %b %Y")
    except: return iso[:10]

def sort_docs(docs):
    return sorted(docs, key=lambda x: x.get("received_at") or x.get("uploaded_at") or "", reverse=True)

def make_presigned(s3_key, filename, expiry=86400):
    try:
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": BUCKET, "Key": s3_key,
                    "ResponseContentDisposition": "attachment; filename=\"" + filename + "\""},
            ExpiresIn=expiry
        )
    except Exception as e:
        print("Presign err: " + str(e))
        return None

def build_doc_table(docs, filter_label=None):
    title = ("Documents matching '" + filter_label + "' (" + str(len(docs)) + " found)"
             if filter_label else "Your Documents (" + str(len(docs)) + " total)")
    rows = ""
    for i, d in enumerate(sort_docs(docs), 1):
        fn  = d.get("filename", "\u2014")
        cat = doc_category(fn)
        src = source_label(d)
        dt  = fmt_date(d.get("received_at") or d.get("uploaded_at",""))
        st  = d.get("status","\u2014")
        sc  = "st-ok" if st == "INDEXED" else "st-proc" if "PROCESS" in st else "st-pend"
        sl  = "Indexed" if st == "INDEXED" else "Processing" if "PROCESS" in st else st
        rows += ("<tr><td class='tsl'>" + str(i) + "</td><td class='tfn'>" + fn + "</td>"
                 "<td class='tca'>" + cat + "</td><td class='tsr'>" + src + "</td>"
                 "<td class='tdt'>" + dt + "</td><td><span class='tbl-st " + sc + "'>" + sl + "</span></td></tr>")
    return ('<div class="doc-table-wrap"><div class="doc-table-hd">' + title + '</div>'
            '<div class="doc-table-scroll"><table class="doc-table">'
            '<thead><tr><th>Sl</th><th>Document Name</th><th>Category</th>'
            '<th>Source</th><th>Date</th><th>Status</th></tr></thead>'
            '<tbody>' + rows + '</tbody></table></div></div>')

def save_turn(uid, sid, question, answer, sources=None):
    try:
        dynamodb.Table("ChatSessions").put_item(Item={
            "PK": "USER#" + uid,
            "SK": "SESSION#" + sid + "#TURN#" + str(uuid.uuid4()),
            "session_id": sid, "question": question,
            "answer": answer[:800], "sources": sources or [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "deleted": False
        })
    except Exception as e:
        print("DDB save: " + str(e))

def is_cancel(text):
    t = text.lower().strip()
    return any(w in t for w in ["cancel","stop","abort","never mind","quit","no thanks"])

def is_confirm(text):
    t = text.lower().strip()
    return any(w in t for w in ["yes","send","confirm","delete","ok","sure","proceed","go ahead","do it","yep","yeah"])

# ================================================================
#  KB SEARCH
# ================================================================

def kb_search(query, min_score=0.45):
    kb_client = boto3.client("bedrock-agent-runtime", region_name="eu-west-1")
    try:
        res = kb_client.retrieve(
            knowledgeBaseId=KB_ID,
            retrievalQuery={"text": query},
            retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 8}}
        )
    except Exception as e:
        print("KB error: " + str(e))
        return [], []
    chunks, sources, seen = [], [], set()
    for r in res.get("retrievalResults", []):
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

# ================================================================
#  EXACT FILENAME MATCH (for exact_download and delete resolution)
# ================================================================

def exact_doc_match(all_docs, filename_query):
    """Returns one doc if exact filename match found (case-insensitive)."""
    fq = filename_query.strip().lower()
    for doc in all_docs:
        if (doc.get("filename") or "").strip().lower() == fq:
            return doc
    return None

def fuzzy_doc_match(all_docs, query, require_hits=2):
    """
    Returns list of docs matching query by substring or keyword.
    Used when no exact filename is known.
    """
    stops = {"the","for","and","of","a","an","in","on","at","to","with","details",
             "what","is","my","from","about","download","send","delete","remove",
             "give","me","pdf","doc","file","document","share","email"}
    kws = set()
    for w in re.split(r"[\W_]+", query.lower()):
        if len(w) > 2 and w not in stops:
            kws.add(w)
    matched = []
    for doc in all_docs:
        fname = (doc.get("filename") or "").lower()
        # Substring: query contained in filename
        if query.lower() in fname:
            if doc not in matched: matched.append(doc)
            continue
        # Keyword hits
        hits = sum(1 for kw in kws if kw in fname)
        if hits >= require_hits and doc not in matched:
            matched.append(doc)
    return matched

# ================================================================
#  DECOMPOSER  (Layer 1 — replaces plan())
# ================================================================

DECOMPOSER_SYSTEM = """You are the Decomposer for FamilyVault AI, a personal document assistant.

Your ONLY job: parse the user's latest message and return a JSON array of independent sub-tasks.
Use conversation history to resolve follow-up references (e.g. "that file", "both documents").

INTENT TYPES (classify each user demand into exactly one):
- exact_download    : user provides an exact filename or refers to a specific named file
- semantic_download : user describes a doc by concept (e.g. "my PAN card", "the insurance policy")
- content_question  : user asks a question whose answer is inside a document
- list_documents    : user wants to see their document inventory
- send_email        : user wants to email documents to someone
- delete_document   : user wants to delete/remove a document
- out_of_scope      : completely unrelated to personal documents

OUTPUT FORMAT — return ONLY a valid JSON array, no markdown, no explanation:
[
  {
    "intent_type": "<one of the 6 types above>",
    "target": "<what the user wants — human readable>",
    "params": {
      "filename": "<exact filename if known, else omit>",
      "query": "<search concept or question>",
      "recipients": ["<email1>", "<email2>"],
      "tone": "<Professional|Friendly|Brief|Formal|Warm — if stated, else omit>",
      "doc_refs": ["<doc name or concept 1>", "<doc name or concept 2>"]
    }
  }
]

RULES:
- One sub-task per distinct user demand. If user asks for 3 things, return 3 sub-tasks.
- For exact_download: set params.filename to the exact filename string.
- For semantic_download: set params.query to the concept (e.g. "PAN card", "salary slip").
- For send_email: set params.recipients to any emails mentioned, params.doc_refs to docs mentioned, params.tone if stated.
- For delete_document: set params.query to what the user wants deleted.
- For out_of_scope: return single task with intent_type "out_of_scope".
- Maximum 8 sub-tasks total.

EXAMPLES:

User: "download Aishiki-aakash-first-payment-03042026.pdf and my PAN card"
Output: [
  {"intent_type":"exact_download","target":"Aishiki payment file","params":{"filename":"Aishiki-aakash-first-payment-03042026.pdf"}},
  {"intent_type":"semantic_download","target":"PAN card","params":{"query":"PAN card"}}
]

User: "email my TCS offer letter and PAN card to rajat@gmail.com professionally, also delete the old admission form"
Output: [
  {"intent_type":"send_email","target":"TCS offer letter and PAN card","params":{"recipients":["rajat@gmail.com"],"doc_refs":["TCS offer letter","PAN card"],"tone":"Professional"}},
  {"intent_type":"delete_document","target":"old admission form","params":{"query":"admission form"}}
]

User: "what is my PAN number?"
Output: [{"intent_type":"content_question","target":"PAN card number","params":{"query":"PAN card number"}}]

User: "list all my documents"
Output: [{"intent_type":"list_documents","target":"all documents","params":{}}]

User: "what is the weather?"
Output: [{"intent_type":"out_of_scope","target":"weather","params":{}}]"""


def decompose(query, short_term_history):
    try:
        messages = list(short_term_history)
        messages.append({"role": "user", "content": query})
        resp = bedrock.invoke_model(
            modelId=DECOMPOSER_MODEL,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 800,
                "system": DECOMPOSER_SYSTEM,
                "messages": messages
            })
        )
        raw = json.loads(resp["body"].read())["content"][0]["text"].strip()
        raw = re.sub(r'^```[a-z]*\n?', '', raw, flags=re.M)
        raw = re.sub(r'\n?```$', '', raw, flags=re.M)
        tasks = json.loads(raw)
        print("Decomposed: " + str(tasks))
        return tasks
    except Exception as e:
        print("Decomposer error: " + str(e))
        # Fallback: treat as content question
        return [{"intent_type": "content_question", "target": query, "params": {"query": query}}]

# ================================================================
#  TASK RUNNERS  (Layer 2+3)
# ================================================================

# ── exact_download ───────────────────────────────────────────────

def run_exact_download(task, all_docs, push, obs):
    filename = task.get("params", {}).get("filename", "")
    if not filename:
        push({"type": "token", "content": "I need the exact filename to generate a download link. Could you share it?"})
        return None
    doc = exact_doc_match(all_docs, filename)
    if not doc:
        push({"type": "token", "content": "I couldn't find '" + filename + "' in your vault. Please check the filename."})
        return None
    url = make_presigned(doc.get("s3_key",""), doc.get("filename","document"))
    if url:
        push({"type": "token", "content": "Here is the secure download link for " + doc.get("filename","") + " (valid 24h):"})
        return [{"filename": doc.get("filename","document"), "url": url}]
    push({"type": "token", "content": "I found the file but could not generate a download link. Please try again."})
    return None

# ── semantic_download ─────────────────────────────────────────────

def run_semantic_download(task, all_docs, push, obs):
    query = task.get("params", {}).get("query", task.get("target",""))
    push({"type": "status", "message": "Searching for: " + query[:50] + "..."})
    t0 = time.time()
    chunks, sources = kb_search(query)
    obs["kb_latency_ms"] = obs.get("kb_latency_ms",0) + int((time.time()-t0)*1000)
    obs["kb_chunks_retrieved"] = obs.get("kb_chunks_retrieved",0) + len(chunks)
    if not sources:
        push({"type": "token", "content": "I couldn't find a document matching '" + query + "' in your vault."})
        return None
    # Match top KB source exactly to DDB
    for src in sources:
        doc = exact_doc_match(all_docs, src)
        if doc:
            url = make_presigned(doc.get("s3_key",""), doc.get("filename","document"))
            if url:
                push({"type": "token", "content": "Here is the secure download link for " + doc.get("filename","") + " (valid 24h):"})
                return [{"filename": doc.get("filename","document"), "url": url}]
    push({"type": "token", "content": "I found references to '" + query + "' but couldn't generate a download link. Try using the exact filename."})
    return None

# ── content_question ──────────────────────────────────────────────

def run_content_question(task, push, short_term, long_term, obs):
    query = task.get("params", {}).get("query", task.get("target",""))
    push({"type": "status", "message": "Searching documents..."})
    t0 = time.time()
    chunks, _ = kb_search(query)
    obs["kb_latency_ms"] = obs.get("kb_latency_ms",0) + int((time.time()-t0)*1000)
    obs["kb_chunks_retrieved"] = obs.get("kb_chunks_retrieved",0) + len(chunks)

    if not chunks:
        rag_context = "No relevant document content found."
    else:
        parts = []
        for ch in chunks[:6]:
            fn = ch.get("filename","")
            sc = ch.get("score",0)
            src = "[Source: " + fn + " | Score: " + str(round(sc,3)) + "]" if fn else ""
            parts.append(src + "\n" + ch["text"])
        rag_context = "\n\n---\n\n".join(parts)

    ltm_block = ("\n" + long_term + "\n\nUse above as BACKGROUND CONTEXT only.\n") if long_term else ""
    system = ("You are FamilyVault AI \u2014 a warm, professional personal document assistant.\n"
              + ltm_block
              + "\nRETRIEVED DOCUMENT CONTENT:\n" + rag_context
              + "\n\nSTRICT RULES:\n"
              "1. Answer ONLY from retrieved content. Never invent.\n"
              "2. Be specific \u2014 quote exact values found.\n"
              "3. Mention which document the info comes from.\n"
              "4. If content does not answer: say warmly you couldn't find it.\n"
              "5. NEVER use markdown bold (**) or bullet stars.\n"
              "6. NEVER say 'Based on retrieved content'.\n"
              "7. Keep responses concise, warm, professional.")
    messages = list(short_term)
    messages.append({"role": "user", "content": query})
    full = ""
    inp = out = 0
    t1 = time.time()
    try:
        stream = bedrock.invoke_model_with_response_stream(
            modelId=ANSWERER_MODEL,
            body=json.dumps({"anthropic_version":"bedrock-2023-05-31","max_tokens":900,
                             "system":system,"messages":messages})
        )
        for ev in stream["body"]:
            ch = json.loads(ev["chunk"]["bytes"])
            if ch.get("type") == "content_block_delta":
                tok = ch.get("delta",{}).get("text","")
                if tok: full += tok; push({"type":"token","content":tok})
            elif ch.get("type") == "message_start":
                inp += ch.get("message",{}).get("usage",{}).get("input_tokens",0)
            elif ch.get("type") == "message_delta":
                out += ch.get("usage",{}).get("output_tokens",0)
    except Exception as e:
        print("Answerer error: " + str(e))
        msg = "Sorry, I had trouble generating a response. Please try again."
        push({"type":"token","content":msg})
        full = msg; obs["status"] = "error"; obs["error"] = str(e)
    obs["input_tokens"] = obs.get("input_tokens",0) + inp
    obs["output_tokens"] = obs.get("output_tokens",0) + out
    obs["answerer_latency_ms"] = obs.get("answerer_latency_ms",0) + int((time.time()-t1)*1000)
    return full

# ── list_documents ────────────────────────────────────────────────

def run_list_documents(task, uid, push, obs):
    filter_q = task.get("params", {}).get("query", "").strip()
    all_docs = get_user_docs(uid)
    if filter_q:
        stops = {"the","a","an","of","in","for","and","or","my","all","show","list","any","some","about"}
        kws = [w for w in re.split(r'\W+', filter_q.lower()) if len(w) > 1 and w not in stops]
        if kws:
            all_docs = [d for d in all_docs if any(
                kw in ((d.get("filename","") or "").lower() + " " + (d.get("subject","") or "").lower())
                for kw in kws
            )]
    if not all_docs:
        push({"type":"token","content":"I don't see any documents in your vault yet."})
        return
    push({"type":"clear_streaming"})
    push({"type":"html","content":build_doc_table(all_docs, filter_q if filter_q else None)})

# ── send_email: CP handlers ────────────────────────────────────────

def start_send_email(task, uid, sid, query, all_docs, push, obs):
    """CP1 — collect any missing fields and save pending state."""
    params = task.get("params", {})
    recipients = params.get("recipients", [])
    doc_refs   = params.get("doc_refs", [])
    tone       = params.get("tone", "")

    missing = []
    if not recipients: missing.append("recipient_email")
    if not doc_refs:   missing.append("doc_names")
    if not tone:       missing.append("tone")

    state = {
        "intent_type": "send_email",
        "stage": "collecting" if missing else "awaiting_approval",
        "recipients": recipients,
        "doc_refs": doc_refs,
        "tone": tone,
        "missing": missing,
        "original_query": query,
    }

    if missing:
        msg = "I'd love to help you send that email! I just need a couple of details:\n\n"
        if "recipient_email" in missing:
            msg += "To: What is the recipient's email address?\n"
        if "doc_names" in missing:
            msg += "Attach: Which document(s) should I attach?\n"
        if "tone" in missing:
            msg += "Tone: " + " | ".join(TONES) + "\n"
        push({"type":"token","content":msg})
        save_pending_task(uid, sid, state)
        return "[send_email CP1 — collecting info]"

    # All info present — skip straight to CP2
    return resume_send_email_cp2(state, uid, sid, all_docs, push, obs)


def resume_send_email(pending, user_reply, uid, sid, all_docs, push, obs):
    """Route incoming reply to the right checkpoint."""
    if is_cancel(user_reply):
        clear_pending_task(uid, sid)
        push({"type":"token","content":"Email cancelled. Let me know if you need anything else."})
        return "[send_email cancelled]"

    stage = pending.get("stage","collecting")

    if stage == "collecting":
        return _fill_send_email_fields(pending, user_reply, uid, sid, all_docs, push, obs)
    elif stage == "awaiting_approval":
        return _handle_send_email_approval(pending, user_reply, uid, sid, all_docs, push, obs)
    elif stage == "editing":
        return _handle_send_email_edit(pending, user_reply, uid, sid, all_docs, push, obs)
    return "[send_email unknown stage]"


def _fill_send_email_fields(pending, user_reply, uid, sid, all_docs, push, obs):
    """Parse user reply to fill missing CP1 fields."""
    missing = pending.get("missing", [])
    reply_lower = user_reply.lower()

    # Extract email addresses
    if "recipient_email" in missing:
        emails_found = re.findall(r'[\w.+-]+@[\w.-]+\.\w+', user_reply)
        if emails_found:
            pending["recipients"] = emails_found
            missing = [m for m in missing if m != "recipient_email"]

    # Extract tone
    if "tone" in missing:
        for t in TONES:
            if t.lower() in reply_lower:
                pending["tone"] = t
                missing = [m for m in missing if m != "tone"]
                break

    # Extract doc refs from remaining text (anything that's not an email or tone)
    if "doc_names" in missing and user_reply.strip():
        pending["doc_refs"] = [user_reply.strip()]
        missing = [m for m in missing if m != "doc_names"]

    pending["missing"] = missing

    if missing:
        msg = "Thanks! Still need:\n"
        if "recipient_email" in missing: msg += "To: recipient email address?\n"
        if "doc_names" in missing:       msg += "Which document(s) to attach?\n"
        if "tone" in missing:            msg += "Tone: " + " | ".join(TONES) + "\n"
        push({"type":"token","content":msg})
        save_pending_task(uid, sid, pending)
        return "[send_email CP1 — still collecting]"

    return resume_send_email_cp2(pending, uid, sid, all_docs, push, obs)


def resume_send_email_cp2(pending, uid, sid, all_docs, push, obs):
    """CP2 — resolve docs, generate draft, ask for approval."""
    push({"type":"status","message":"Generating email draft..."})

    doc_refs  = pending.get("doc_refs", [])
    tone      = pending.get("tone", "Professional")
    recipients = pending.get("recipients", [])

    # Resolve each doc_ref to an actual DDB document
    resolved_docs = []
    for ref in doc_refs:
        # Try exact match first
        doc = exact_doc_match(all_docs, ref)
        if not doc:
            # Semantic: KB search then match
            _, sources = kb_search(ref)
            for src in sources:
                doc = exact_doc_match(all_docs, src)
                if doc: break
        if not doc:
            # Fuzzy DDB match
            matches = fuzzy_doc_match(all_docs, ref)
            if matches: doc = matches[0]
        if doc and doc not in resolved_docs:
            resolved_docs.append(doc)

    doc_names = [d.get("filename","") for d in resolved_docs]
    doc_ids   = [d.get("document_id") or d.get("PK","").replace("DOC#","") for d in resolved_docs]

    # Get context from KB for the docs
    rag_answer = ""
    for ref in doc_refs[:2]:
        chunks, _ = kb_search(ref)
        if chunks: rag_answer += chunks[0]["text"][:300] + " "

    # Call email Lambda to generate draft
    try:
        draft_payload = json.dumps({
            "rag_answer": rag_answer.strip(),
            "doc_names": doc_names,
            "tone": tone,
            "user_name": "FamilyVault User"
        }).encode()
        req = urllib.request.Request(
            EMAIL_LAMBDA_URL + "/email/draft",
            data=draft_payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            draft = json.loads(resp.read())
        subject = draft.get("draft_subject","FamilyVault \u2014 Documents")
        body    = draft.get("draft_body","")
    except Exception as e:
        print("Draft gen error: " + str(e))
        subject = "FamilyVault \u2014 Documents"
        body    = "Dear Recipient,\n\nPlease find the requested documents attached.\n\nBest regards,\nFamilyVault AI"

    # Build preview
    to_str    = ", ".join(recipients)
    docs_str  = "\n".join("  - " + n for n in doc_names) if doc_names else "  (no documents resolved)"
    preview   = ("Here is the draft email. Please review:\n\n"
                 "To: " + to_str + "\n"
                 "Subject: " + subject + "\n"
                 "Attachments:\n" + docs_str + "\n\n"
                 + body + "\n\n"
                 "Reply 'send' to confirm, 'edit [instructions]' to change, or 'cancel' to abort.")
    push({"type":"token","content":preview})

    pending.update({
        "stage": "awaiting_approval",
        "draft_subject": subject,
        "draft_body": body,
        "resolved_doc_ids": doc_ids,
        "resolved_doc_names": doc_names,
    })
    save_pending_task(uid, sid, pending)
    return "[send_email CP2 — awaiting approval]"


def _handle_send_email_approval(pending, user_reply, uid, sid, all_docs, push, obs):
    """CP2 approval response handler."""
    if user_reply.lower().strip().startswith("edit"):
        edit_instruction = user_reply[4:].strip()
        pending["stage"] = "editing"
        pending["edit_instruction"] = edit_instruction
        save_pending_task(uid, sid, pending)
        return _handle_send_email_edit(pending, user_reply, uid, sid, all_docs, push, obs)

    if is_confirm(user_reply):
        return _execute_send_email(pending, uid, sid, push, obs)

    push({"type":"token","content":"Reply 'send' to confirm, 'edit [instructions]' to change, or 'cancel' to abort."})
    return "[send_email CP2 — waiting]"


def _handle_send_email_edit(pending, user_reply, uid, sid, all_docs, push, obs):
    """Regenerate draft with edit instruction."""
    instruction = pending.get("edit_instruction","") or user_reply
    old_body = pending.get("draft_body","")
    try:
        edit_payload = json.dumps({
            "rag_answer": old_body + "\n\nEdit instruction: " + instruction,
            "doc_names": pending.get("resolved_doc_names",[]),
            "tone": pending.get("tone","Professional"),
            "user_name": "FamilyVault User"
        }).encode()
        req = urllib.request.Request(
            EMAIL_LAMBDA_URL + "/email/draft",
            data=edit_payload,
            headers={"Content-Type":"application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            draft = json.loads(resp.read())
        subject = draft.get("draft_subject", pending.get("draft_subject",""))
        body    = draft.get("draft_body", old_body)
    except Exception as e:
        print("Edit draft error: " + str(e))
        subject = pending.get("draft_subject","")
        body    = old_body

    to_str  = ", ".join(pending.get("recipients",[]))
    docs_str = "\n".join("  - " + n for n in pending.get("resolved_doc_names",[]))
    preview = ("Updated draft:\n\n"
               "To: " + to_str + "\n"
               "Subject: " + subject + "\n"
               "Attachments:\n" + docs_str + "\n\n"
               + body + "\n\n"
               "Reply 'send' to confirm, 'edit [instructions]' to change again, or 'cancel'.")
    push({"type":"token","content":preview})
    pending.update({"stage":"awaiting_approval","draft_subject":subject,"draft_body":body})
    save_pending_task(uid, sid, pending)
    return "[send_email CP2 — updated draft]"


def _execute_send_email(pending, uid, sid, push, obs):
    """CP3 — actually send the email via fv-email-sender Lambda."""
    push({"type":"status","message":"Sending email..."})
    try:
        send_payload = json.dumps({
            "to":      pending.get("recipients",[]),
            "subject": pending.get("draft_subject","FamilyVault \u2014 Documents"),
            "body":    pending.get("draft_body",""),
            "doc_ids": pending.get("resolved_doc_ids",[]),
        }).encode()
        req = urllib.request.Request(
            EMAIL_LAMBDA_URL + "/email/send",
            data=send_payload,
            headers={"Content-Type":"application/json","X-User-Id":uid},
            method="POST"
        )
        # Inject uid as custom header — email sender reads it from authorizer in normal flow
        # but we need to pass it for internal Lambda-to-Lambda calls
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read())
        if result.get("sent"):
            to_str = ", ".join(pending.get("recipients",[]))
            docs_str = ", ".join(pending.get("resolved_doc_names",[]))
            msg = ("Email sent successfully to " + to_str + ".\n"
                   "Attachments: " + (docs_str or "none") + ".\n"
                   "The recipient will receive download links valid for 24 hours.")
            push({"type":"token","content":msg})
            clear_pending_task(uid, sid)
            return "[send_email CP3 — sent]"
        else:
            push({"type":"token","content":"Email could not be sent. Please try again."})
    except Exception as e:
        print("Execute email error: " + str(e))
        push({"type":"token","content":"There was an error sending the email: " + str(e)})
    clear_pending_task(uid, sid)
    return "[send_email CP3 — error]"

# ── delete_document: CP handlers ─────────────────────────────────

def start_delete_document(task, uid, sid, all_docs, push, obs):
    """CP1 — identify matching documents and ask for confirmation."""
    query = task.get("params", {}).get("query", task.get("target",""))
    matches = fuzzy_doc_match(all_docs, query, require_hits=1)

    if not matches:
        push({"type":"token","content":"I couldn't find any documents matching '" + query + "'. Please check the name or description."})
        return "[delete CP1 — no match]"

    if len(matches) == 1:
        doc = matches[0]
        fname = doc.get("filename","")
        msg = ("I found this document:\n\n"
               "  " + fname + "\n\n"
               "Are you sure you want to permanently delete it? This cannot be undone.\n"
               "Reply 'yes' to confirm or 'cancel' to abort.")
        push({"type":"token","content":msg})
        state = {
            "intent_type": "delete_document",
            "stage": "awaiting_approval",
            "confirmed_docs": [{"doc_id": doc.get("document_id") or doc.get("PK","").replace("DOC#",""),
                                 "filename": fname,
                                 "s3_key": doc.get("s3_key","")}],
            "query": query,
        }
        save_pending_task(uid, sid, state)
        return "[delete CP1 — single match, awaiting approval]"

    # Multiple matches — ask user to pick
    lines = ["I found " + str(len(matches)) + " documents matching '" + query + "':\n"]
    for i, doc in enumerate(matches[:10], 1):
        lines.append(str(i) + ". " + doc.get("filename",""))
    lines.append("\nWhich should I delete? Reply with number(s) e.g. '1' or '1,3' or 'all', or 'cancel' to abort.")
    push({"type":"token","content":"\n".join(lines)})
    state = {
        "intent_type": "delete_document",
        "stage": "selecting",
        "candidates": [{"doc_id": d.get("document_id") or d.get("PK","").replace("DOC#",""),
                        "filename": d.get("filename",""),
                        "s3_key": d.get("s3_key","")} for d in matches[:10]],
        "query": query,
    }
    save_pending_task(uid, sid, state)
    return "[delete CP1 — multiple matches, selecting]"


def resume_delete_document(pending, user_reply, uid, sid, push, obs):
    """Route incoming reply to the right delete checkpoint."""
    if is_cancel(user_reply):
        clear_pending_task(uid, sid)
        push({"type":"token","content":"Deletion cancelled. Your documents are safe."})
        return "[delete cancelled]"

    stage = pending.get("stage","")

    if stage == "selecting":
        return _handle_delete_selection(pending, user_reply, uid, sid, push, obs)
    elif stage == "awaiting_approval":
        return _handle_delete_approval(pending, user_reply, uid, sid, push, obs)
    return "[delete unknown stage]"


def _handle_delete_selection(pending, user_reply, uid, sid, push, obs):
    """User replied with which numbered docs to delete."""
    candidates = pending.get("candidates", [])
    reply = user_reply.lower().strip()
    selected = []

    if "all" in reply:
        selected = candidates
    else:
        nums = re.findall(r'\d+', reply)
        for n in nums:
            idx = int(n) - 1
            if 0 <= idx < len(candidates):
                selected.append(candidates[idx])

    if not selected:
        push({"type":"token","content":"I didn't understand the selection. Please reply with number(s) like '1' or '1,2', or 'cancel'."})
        return "[delete CP1 — bad selection]"

    # Move to CP2 — final approval
    lines = ["You have selected " + str(len(selected)) + " document(s) for permanent deletion:\n"]
    for doc in selected:
        lines.append("  - " + doc["filename"])
    lines.append("\nThis CANNOT be undone. Reply 'yes' to confirm deletion or 'cancel' to abort.")
    push({"type":"token","content":"\n".join(lines)})
    pending.update({"stage":"awaiting_approval","confirmed_docs":selected})
    save_pending_task(uid, sid, pending)
    return "[delete CP2 — awaiting final approval]"


def _handle_delete_approval(pending, user_reply, uid, sid, push, obs):
    """CP2 final approval received."""
    if is_confirm(user_reply):
        return _execute_delete(pending, uid, sid, push, obs)
    push({"type":"token","content":"Reply 'yes' to confirm permanent deletion, or 'cancel' to abort."})
    return "[delete CP2 — waiting]"


def _execute_delete(pending, uid, sid, push, obs):
    """CP3 — call delete handler for each confirmed doc."""
    confirmed = pending.get("confirmed_docs", [])
    push({"type":"status","message":"Deleting " + str(len(confirmed)) + " document(s)..."})
    deleted = []
    failed  = []
    table = dynamodb.Table("DocumentMetadata")
    for doc in confirmed:
        doc_id  = doc.get("doc_id","")
        fname   = doc.get("filename","")
        s3_key  = doc.get("s3_key","")
        try:
            # Soft-delete in DDB first (always, non-reversible action is logged)
            table.update_item(
                Key={"PK": "DOC#" + doc_id},
                UpdateExpression="SET deleted = :t",
                ExpressionAttributeValues={":t": True}
            )
            # Hard-delete from S3
            if s3_key:
                try: s3.delete_object(Bucket=BUCKET, Key=s3_key)
                except Exception as e: print("S3 delete warning: " + str(e))
            deleted.append(fname)
            print("Deleted: " + doc_id + " / " + fname)
        except Exception as e:
            print("Delete error " + doc_id + ": " + str(e))
            failed.append(fname)

    # Trigger KB resync (non-fatal)
    try:
        bedrock_agent = boto3.client("bedrock-agent", region_name="eu-west-1")
        bedrock_agent.start_ingestion_job(knowledgeBaseId=KB_ID, dataSourceId=os.environ.get("BEDROCK_DS_ID","JZ13ZYCSRL"))
    except Exception as e:
        print("KB resync warning: " + str(e))

    if deleted:
        msg = "Deleted " + str(len(deleted)) + " document(s):\n" + "\n".join("  - " + f for f in deleted)
        if failed:
            msg += "\n\nCould not delete: " + ", ".join(failed)
        push({"type":"token","content":msg})
    else:
        push({"type":"token","content":"Could not delete the documents. Please try again."})

    clear_pending_task(uid, sid)
    return "[delete CP3 — done, deleted=" + str(len(deleted)) + "]"

# ================================================================
#  MAIN ORCHESTRATOR  (entry point)
# ================================================================

# Execution priority order (non-destructive first, destructive last)
TASK_ORDER = ["list_documents", "content_question", "exact_download",
              "semantic_download", "send_email", "delete_document", "out_of_scope"]


def orchestrate(query, uid, sid, push):
    t_start = time.time()
    obs = {
        "input_tokens":0,"output_tokens":0,"latency_ms":0,"planner_latency_ms":0,
        "answerer_latency_ms":0,"kb_latency_ms":0,"kb_chunks_retrieved":0,
        "tools_called":[],"model_id":ANSWERER_MODEL,"status":"ok","error":"",
        "query_len":len(query),"answer_len":0,"short_term_turns":0,"long_term_sessions":0,
    }

    push({"type":"status","message":"Recalling conversation..."})
    short_term = load_short_term_memory(uid, sid, limit=6)
    long_term  = load_long_term_memory(uid, sid, max_sessions=3)
    obs["short_term_turns"]   = len(short_term) // 2
    obs["long_term_sessions"] = long_term.count("[Session")

    # ── Check for pending multi-turn task ──────────────────────────
    pending = load_pending_task(uid, sid)
    if pending:
        intent = pending.get("intent_type","")
        push({"type":"scratchpad","event":"plan","content":"Resuming: " + intent + " stage=" + pending.get("stage","?")})
        full_reply = ""
        if intent == "send_email":
            full_reply = resume_send_email(pending, query, uid, sid, get_user_docs(uid), push, obs)
        elif intent == "delete_document":
            full_reply = resume_delete_document(pending, query, uid, sid, push, obs)
        obs["latency_ms"] = int((time.time()-t_start)*1000)
        obs["answer_len"] = len(full_reply or "")
        write_observation(uid, sid, obs)
        publish_metrics(uid, obs)
        push({"type":"scratchpad","event":"done","content":""})
        push({"type":"final","sources":[],"session_id":sid})
        save_turn(uid, sid, query, full_reply or "")
        return

    # ── Decompose fresh query ──────────────────────────────────────
    push({"type":"status","message":"Understanding your request..."})
    t_decomp = time.time()
    tasks = decompose(query, short_term)
    obs["planner_latency_ms"] = int((time.time()-t_decomp)*1000)
    obs["tools_called"] = [t.get("intent_type") for t in tasks]

    # Sort by execution priority
    tasks.sort(key=lambda t: TASK_ORDER.index(t.get("intent_type","out_of_scope"))
               if t.get("intent_type") in TASK_ORDER else 99)

    plan_lines = []
    for i, t in enumerate(tasks, 1):
        plan_lines.append("  " + str(i) + ". " + t.get("intent_type","?") + " → " + t.get("target","")[:60])
    push({"type":"scratchpad","event":"plan","content":"Tasks:\n" + "\n".join(plan_lines)})

    # Fetch docs once if any task needs them
    needs_docs = any(t.get("intent_type") in
                     ("exact_download","list_documents","send_email","delete_document")
                     for t in tasks)
    all_docs = get_user_docs(uid) if needs_docs else []

    full_reply = ""
    all_links  = []
    sources    = []

    for task in tasks:
        intent = task.get("intent_type","out_of_scope")
        push({"type":"scratchpad","event":"step",
              "content":"Running: " + intent + " → " + task.get("target","")[:60]})

        if intent == "list_documents":
            run_list_documents(task, uid, push, obs)

        elif intent == "content_question":
            answer = run_content_question(task, push, short_term, long_term, obs)
            full_reply += answer + "\n\n"

        elif intent == "exact_download":
            if not all_docs: all_docs = get_user_docs(uid)
            links = run_exact_download(task, all_docs, push, obs)
            if links: all_links.extend(links)

        elif intent == "semantic_download":
            if not all_docs: all_docs = get_user_docs(uid)
            links = run_semantic_download(task, all_docs, push, obs)
            if links: all_links.extend(links)

        elif intent == "send_email":
            if not all_docs: all_docs = get_user_docs(uid)
            reply = start_send_email(task, uid, sid, query, all_docs, push, obs)
            full_reply += reply + "\n\n"

        elif intent == "delete_document":
            if not all_docs: all_docs = get_user_docs(uid)
            reply = start_delete_document(task, uid, sid, all_docs, push, obs)
            full_reply += reply + "\n\n"

        elif intent == "out_of_scope":
            msg = ("That is a bit outside what I can help with. I am best at answering questions "
                   "about your stored documents, listing files, sharing download links, "
                   "sending documents by email, or deleting files.")
            push({"type":"token","content":msg})
            full_reply += msg

    # Emit all collected links in one block at the end
    if all_links:
        push({"type":"links","links":all_links})

    obs["latency_ms"] = int((time.time()-t_start)*1000)
    obs["answer_len"] = len(full_reply)
    write_observation(uid, sid, obs)
    publish_metrics(uid, obs)
    push({"type":"scratchpad","event":"done","content":""})
    push({"type":"final","sources":sources,"session_id":sid})
    save_turn(uid, sid, query, full_reply.strip() or "[tasks completed]", sources=sources)

# ================================================================
#  LAMBDA ENTRY POINT
# ================================================================

def lambda_handler(event, context):
    route  = event.get("requestContext",{}).get("routeKey","$default")
    cid    = event.get("requestContext",{}).get("connectionId","")
    domain = event.get("requestContext",{}).get("domainName","")
    stage  = event.get("requestContext",{}).get("stage","production")

    if route == "$connect":    return {"statusCode":200,"body":"Connected"}
    if route == "$disconnect": return {"statusCode":200,"body":"Disconnected"}

    body  = json.loads(event.get("body","{}") or "{}")
    query = body.get("query", body.get("message","")).strip()
    sid   = body.get("session_id", str(uuid.uuid4()))
    uid   = body.get("user_id","unknown")

    apigw = boto3.client("apigatewaymanagementapi", endpoint_url="https://" + domain + "/" + stage)

    def push(data):
        try:
            apigw.post_to_connection(ConnectionId=cid,
                                     Data=json.dumps(data, ensure_ascii=False).encode("utf-8"))
        except Exception as e:
            print("Push FAILED type=" + str(data.get("type","?")) + " err=" + str(e))

    if not query or query.lower() in ("hi","hello","hey","start"):
        for i in range(0, len(WELCOME), 8):
            push({"type":"token","content":WELCOME[i:i+8]})
        push({"type":"final","sources":[],"session_id":sid})
        return {"statusCode":200,"body":"OK"}

    try:
        orchestrate(query, uid, sid, push)
    except Exception as e:
        import traceback
        print("Orchestrator error: " + str(e))
        print(traceback.format_exc())
        push({"type":"error","message":"Something went wrong. Please try again."})
        write_observation(uid, sid, {"status":"error","error":str(e),"tools_called":[]})
        publish_metrics(uid, {"status":"error","input_tokens":0,"output_tokens":0,"latency_ms":0})

    return {"statusCode":200,"body":"OK"}
