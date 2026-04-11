"""FamilyVault AI — Chat Handler v15.5

Fixes vs v15.4:
  BUG-G — Token text "Here is the secure download link for X (valid 24h):"
           was pushed as a streaming token before the link card. That token
           persists in the AI bubble after clear_links clears the card,
           causing ghost-text bleed into subsequent turns. Fix: removed the
           token push from run_exact_download and run_semantic_download.
           The link card is the only download UI needed.

  BUG-H — "Share the sem-1.pdf document link" classified as semantic_download
           → KB vector search → Sem-2.pdf returned (higher cosine score than
           Sem-1). Two-part fix:
           (a) Decomposer prompt: exact filename (.pdf/.doc/.jpg extension)
               MUST always → exact_download, not semantic_download.
           (b) run_semantic_download: try exact_doc_match on the raw query
               before calling KB — if the user said the filename exactly,
               skip the vector search entirely.

  BUG-I — content_question answerer said "I don't have the ability to
           provide download links" — wrong, confusing. Clarified system
           prompt: the AI CAN share download links but for content questions
           it answers with document content, not file links.

All v15.4 and earlier fixes retained unchanged.
"""
import json, boto3, os, uuid, re, time
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Attr

dynamodb  = boto3.resource("dynamodb", region_name="eu-west-1")
bedrock   = boto3.client("bedrock-runtime", region_name="eu-west-1")
s3        = boto3.client("s3", region_name="eu-west-1")
cw        = boto3.client("cloudwatch", region_name="eu-west-1")
lmb       = boto3.client("lambda", region_name="eu-west-1")

KB_ID            = os.environ.get("BEDROCK_KB_ID", "PYV06IINGT")
BUCKET           = os.environ.get("BUCKET", "family-docs-raw")
DECOMPOSER_MODEL = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
ANSWERER_MODEL   = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
EMAIL_LAMBDA_NAME = os.environ.get("EMAIL_LAMBDA_NAME", "fv-email-sender")

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
        print("OBS: latency=" + str(obs.get("latency_ms")) + "ms")
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
    except Exception as e:
        print("CW error: " + str(e))

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
            if not q: continue
            is_internal = a.startswith("[") and a.endswith("]")
            if q: messages.append({"role": "user", "content": q})
            if a and not is_internal:
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
                is_internal = a.startswith("[") and a.endswith("]")
                if q and a and not is_internal:
                    a_clean = re.sub(r'\*\*(.+?)\*\*', r'\1', a)
                    a_clean = re.sub(r'(?m)^[\-\*]\s+', '', a_clean).strip()
                    lines.append("Q: " + q)
                    lines.append("A: " + (a_clean[:300] + "..." if len(a_clean) > 300 else a_clean))
        if len(lines) <= 1: return ""
        return "\n".join(lines)
    except Exception as e:
        print("LTM error: " + str(e))
        return ""

# ================================================================
#  PENDING TASK STATE
# ================================================================

def save_pending_task(uid, sid, task_state):
    try:
        dynamodb.Table("ChatSessions").put_item(Item={
            "PK": "USER#" + uid, "SK": "PENDING#" + sid,
            "session_id": sid,
            "pending_task": json.dumps(task_state),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "deleted": False,
        })
        print("Pending saved: " + task_state.get("intent_type","?") + " stage=" + task_state.get("stage","?"))
    except Exception as e:
        print("Save pending error: " + str(e))

def load_pending_task(uid, sid):
    try:
        result = dynamodb.Table("ChatSessions").get_item(Key={"PK": "USER#" + uid, "SK": "PENDING#" + sid})
        item = result.get("Item")
        if item and item.get("pending_task"):
            task = json.loads(item["pending_task"])
            print("Pending found: " + task.get("intent_type","?") + " stage=" + task.get("stage","?"))
            return task
    except Exception as e:
        print("Load pending error: " + str(e))
    return None

def clear_pending_task(uid, sid):
    try:
        dynamodb.Table("ChatSessions").delete_item(Key={"PK": "USER#" + uid, "SK": "PENDING#" + sid})
        print("Pending cleared")
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
#  MARKDOWN STRIPPER
# ================================================================

def strip_markdown(text):
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'(?m)^[\-\*]\s+', '', text)
    return text

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
#  DOC MATCHING
# ================================================================

def exact_doc_match(all_docs, filename_query):
    fq = filename_query.strip().lower()
    for doc in all_docs:
        if (doc.get("filename") or "").strip().lower() == fq:
            return doc
    return None

def fuzzy_doc_match(all_docs, query, require_hits=2):
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
        if query.lower() in fname:
            if doc not in matched: matched.append(doc)
            continue
        hits = sum(1 for kw in kws if kw in fname)
        if hits >= require_hits and doc not in matched:
            matched.append(doc)
    return matched

# ================================================================
#  EMAIL LAMBDA
# ================================================================

def invoke_email_lambda(path_suffix, payload_dict, uid):
    event = {
        "requestContext": {
            "http": {"method": "POST"},
            "authorizer": {"jwt": {"claims": {}}}
        },
        "rawPath": "/email/" + path_suffix,
        "headers": {"x-user-id": uid, "content-type": "application/json"},
        "body": json.dumps(payload_dict),
    }
    try:
        resp = lmb.invoke(
            FunctionName=EMAIL_LAMBDA_NAME,
            InvocationType="RequestResponse",
            Payload=json.dumps(event).encode()
        )
        result_str = resp["Payload"].read().decode()
        result = json.loads(result_str)
        if isinstance(result.get("body"), str):
            result["body"] = json.loads(result["body"])
        print("Lambda invoke /email/" + path_suffix + " status=" + str(result.get("statusCode")))
        return result
    except Exception as e:
        print("Lambda invoke error: " + str(e))
        return {"statusCode": 500, "body": {"error": str(e)}}

# ================================================================
#  DECOMPOSER  (Layer 1)
# ================================================================

DECOMPOSER_SYSTEM = """You are the Decomposer for FamilyVault AI, a personal document assistant.

Your ONLY job: look at the user's LATEST message (last in the conversation) and return a JSON array
of independent sub-tasks for THAT message only. Do NOT re-create tasks for previous turns.
Use history only to resolve references like "that file" or "the same document".

INTENT TYPES:
- exact_download    : user provides an exact filename AND asks to download/get the file
- semantic_download : user describes a doc by concept AND asks to download/get the file
- content_question  : user asks a question answered by document content
- list_documents    : user wants to see their document inventory
- send_email        : user wants to email documents to someone
- delete_document   : user wants to delete/remove a document
- out_of_scope      : completely unrelated to personal documents

OUTPUT — valid JSON array ONLY, no markdown:
[{"intent_type":"...","target":"...","params":{"filename":"...","query":"...","recipients":["..."],"tone":"...","doc_refs":["..."]}}]

RULES:
- Decompose the LATEST user message only. One sub-task per distinct demand.
- exact_download → params.filename = exact filename string
- semantic_download → params.query = concept string
- send_email → params.recipients, params.doc_refs, params.tone (if stated)
- delete_document → params.query = description of what to delete
- Maximum 8 sub-tasks.

EXACT FILENAME RULE (highest priority):
  If the user's message contains a string that looks like a filename
  (ends with .pdf, .doc, .docx, .jpg, .jpeg, .png, .txt, .xlsx, .pptx)
  AND the message also contains a download trigger word — ALWAYS use
  exact_download with params.filename = that exact filename string.
  NEVER use semantic_download when an exact filename is given.
  Example: "share the sem-1.pdf link" → exact_download with filename="Sem-1.pdf"
  Example: "give me Rajat_Roy_Resume.pdf" → exact_download with filename="Rajat_Roy_Resume.pdf"

CRITICAL — DOWNLOAD INTENT GUARD:
  NEVER emit exact_download or semantic_download unless the user's message
  explicitly contains at least one of these trigger phrases (case-insensitive):
    "download", "download link", "link", "url", "attach",
    "get me the file", "give me the file", "send me the file",
    "give me the download", "get the download"

  The following patterns ALWAYS map to content_question or list_documents,
  NEVER to a download intent — even if the word "share" appears:
    "please share the <document>", "please share <document>",
    "can you share the <document>", "can you share <document>",
    "share the details", "share the information",
    "do you have", "have you", "know about", "tell me about",
    "what is", "what are", "can you tell", "is there",
    "please share the details", "details about"
  The key rule: "please share X" where X is a DOCUMENT NAME or CONCEPT
  is a request for INFORMATION about that document, NOT a file download.
  Only "share the download link", "share the link", or "share the file"
  trigger download intent.

EXAMPLES:

User: "download Aishiki-aakash-first-payment-03042026.pdf and my PAN card"
[{"intent_type":"exact_download","target":"Aishiki payment","params":{"filename":"Aishiki-aakash-first-payment-03042026.pdf"}},
 {"intent_type":"semantic_download","target":"PAN card","params":{"query":"PAN card"}}]

User: "share the sem-1.pdf link"
[{"intent_type":"exact_download","target":"Sem-1 marksheet","params":{"filename":"Sem-1.pdf"}}]

User: "give me the sem-1.pdf document link"
[{"intent_type":"exact_download","target":"Sem-1 marksheet","params":{"filename":"Sem-1.pdf"}}]

User: "Ok. Share the sem-1.pdf document link"
[{"intent_type":"exact_download","target":"Sem-1 marksheet","params":{"filename":"Sem-1.pdf"}}]

User: "email my TCS offer letter to rajat@gmail.com professionally"
[{"intent_type":"send_email","target":"TCS offer letter","params":{"recipients":["rajat@gmail.com"],"doc_refs":["TCS offer letter"],"tone":"Professional"}}]

User: "delete the old admission form"
[{"intent_type":"delete_document","target":"admission form","params":{"query":"admission form"}}]

User: "what is my PAN number?"
[{"intent_type":"content_question","target":"PAN number","params":{"query":"PAN card number"}}]

User: "what does my offer letter say about my salary?"
[{"intent_type":"content_question","target":"offer letter salary","params":{"query":"offer letter salary details"}}]

User: "do you have sem-1.pdf?"
[{"intent_type":"content_question","target":"Sem-1 document","params":{"query":"Sem-1 first semester academic results"}}]

User: "Do you have Rajat Semester-1 marksheet from First Year BTech exam?"
[{"intent_type":"content_question","target":"Sem-1 BTech marksheet","params":{"query":"Rajat Roy semester 1 first year BTech marksheet grades"}}]

User: "have you know Poushali doctor prescription reg Aishiki Roy?"
[{"intent_type":"content_question","target":"Poushali prescription Aishiki","params":{"query":"Poushali doctor prescription Aishiki Roy"}}]

User: "tell me about Rajat experience in Cloud Technology?"
[{"intent_type":"content_question","target":"Rajat cloud experience","params":{"query":"Rajat Roy cloud technology experience"}}]

User: "please share the resume of Rajat Roy"
[{"intent_type":"content_question","target":"Rajat resume","params":{"query":"Rajat Roy resume work experience skills"}}]

User: "please share the PAN card of Rajat"
[{"intent_type":"content_question","target":"PAN card info","params":{"query":"Rajat Roy PAN card number"}}]

User: "can you share Rajat AWS Professional details"
[{"intent_type":"content_question","target":"Rajat AWS certifications","params":{"query":"Rajat Roy AWS professional certifications"}}]

User: "give me the download link for my resume"
[{"intent_type":"semantic_download","target":"resume","params":{"query":"resume"}}]

User: "show me my Academic documents"
[{"intent_type":"list_documents","target":"Academic documents","params":{"query":"Academic"}}]

User: "please share the list of documents you have regarding semester exam of Rajat Roy"
[{"intent_type":"list_documents","target":"semester exam documents","params":{"query":"semester"}}]

User: "what is the weather?"
[{"intent_type":"out_of_scope","target":"weather","params":{}}]"""


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
        return [{"intent_type": "content_question", "target": query, "params": {"query": query}}]

# ================================================================
#  TASK RUNNERS
# ================================================================

def run_exact_download(task, all_docs, push, obs):
    filename = task.get("params", {}).get("filename", "")
    if not filename:
        push({"type":"token","content":"I need the exact filename. Could you share it?"})
        return None
    doc = exact_doc_match(all_docs, filename)
    if not doc:
        push({"type":"token","content":"I couldn't find '" + filename + "' in your vault."})
        return None
    url = make_presigned(doc.get("s3_key",""), doc.get("filename","document"))
    if url:
        # BUG-G FIX: do NOT push a token here — the link card is the only UI needed.
        # Pushing a token "Here is the secure download link..." caused that text to
        # persist as ghost-text in the AI bubble across subsequent turns.
        return [{"filename": doc.get("filename","document"), "url": url}]
    push({"type":"token","content":"Found the file but could not generate a download link. Please try again."})
    return None

def run_semantic_download(task, all_docs, push, obs):
    query = task.get("params", {}).get("query", task.get("target",""))
    push({"type":"status","message":"Searching for: " + query[:50] + "..."})

    # BUG-H FIX (part b): if the query looks like an exact filename, try direct
    # match first — skip KB entirely to avoid wrong-file vector matches.
    if re.search(r'\.(pdf|doc|docx|jpg|jpeg|png|txt|xlsx|pptx)$', query.strip(), re.I):
        doc = exact_doc_match(all_docs, query.strip())
        if not doc:
            # try matching without extension precision (e.g. "Sem-1.pdf" → "sem-1.pdf")
            for d in all_docs:
                fn = (d.get("filename") or "").lower()
                if fn == query.strip().lower() or fn.replace(" ","_") == query.strip().lower().replace(" ","_"):
                    doc = d
                    break
        if doc:
            url = make_presigned(doc.get("s3_key",""), doc.get("filename","document"))
            if url:
                # BUG-G FIX: no token push — link card is sufficient
                return [{"filename": doc.get("filename","document"), "url": url}]

    t0 = time.time()
    chunks, sources = kb_search(query)
    obs["kb_latency_ms"] = obs.get("kb_latency_ms",0) + int((time.time()-t0)*1000)
    obs["kb_chunks_retrieved"] = obs.get("kb_chunks_retrieved",0) + len(chunks)
    if not sources:
        push({"type":"token","content":"I couldn't find a document matching '" + query + "' in your vault."})
        return None
    for src in sources:
        doc = exact_doc_match(all_docs, src)
        if doc:
            url = make_presigned(doc.get("s3_key",""), doc.get("filename","document"))
            if url:
                # BUG-G FIX: no token push — link card is sufficient
                return [{"filename": doc.get("filename","document"), "url": url}]
    push({"type":"token","content":"Found references to '" + query + "' but couldn't generate a download link. Try using the exact filename."})
    return None

def run_content_question(task, push, short_term, long_term, obs):
    query = task.get("params", {}).get("query", task.get("target",""))
    push({"type":"status","message":"Searching documents..."})
    t0 = time.time()
    chunks, _ = kb_search(query)
    obs["kb_latency_ms"] = obs.get("kb_latency_ms",0) + int((time.time()-t0)*1000)
    obs["kb_chunks_retrieved"] = obs.get("kb_chunks_retrieved",0) + len(chunks)
    rag_context = "No relevant document content found." if not chunks else "\n\n---\n\n".join(
        ("[Source: " + ch.get("filename","") + " | Score: " + str(round(ch.get("score",0),3)) + "]\n" if ch.get("filename") else "") + ch["text"]
        for ch in chunks[:6]
    )
    ltm_block = ("\n" + long_term + "\n\nUse above as BACKGROUND CONTEXT only.\n") if long_term else ""
    # BUG-I FIX: clarified rule 4 — the AI CAN share download links but for
    # content questions it answers with document content, not file links.
    system = ("You are FamilyVault AI \u2014 a warm, professional personal document assistant. "
              "You have the ability to answer questions about documents, share download links, "
              "send emails, and list files.\n"
              + ltm_block + "\nRETRIEVED DOCUMENT CONTENT:\n" + rag_context
              + "\n\nSTRICT RULES:\n"
              "1. Answer ONLY from retrieved content.\n"
              "2. Be specific, quote exact values (names, numbers, dates).\n"
              "3. Mention the source document name.\n"
              "4. If not found in retrieved content: warmly say you couldn't find it "
              "and suggest the user ask for a document list or download link.\n"
              "5. Never say you cannot provide download links — you can, the user just "
              "needs to ask for 'the download link' explicitly.\n"
              "6. No markdown bold (**) or bullet stars. Keep concise and warm.")
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
                if tok:
                    clean_tok = strip_markdown(tok)
                    full += clean_tok
                    push({"type":"token","content":clean_tok})
            elif ch.get("type") == "message_start":
                inp += ch.get("message",{}).get("usage",{}).get("input_tokens",0)
            elif ch.get("type") == "message_delta":
                out += ch.get("usage",{}).get("output_tokens",0)
    except Exception as e:
        msg = "Sorry, I had trouble generating a response. Please try again."
        push({"type":"token","content":msg}); full = msg
        obs["status"] = "error"; obs["error"] = str(e)
    obs["input_tokens"] = obs.get("input_tokens",0) + inp
    obs["output_tokens"] = obs.get("output_tokens",0) + out
    obs["answerer_latency_ms"] = obs.get("answerer_latency_ms",0) + int((time.time()-t1)*1000)
    return full

def run_list_documents(task, uid, push, obs):
    filter_q = task.get("params", {}).get("query", "").strip()
    all_docs = get_user_docs(uid)
    if filter_q:
        stops = {
            "the","a","an","of","in","for","and","or","my","all","show","list",
            "any","some","about","please","share","documents","you","have",
            "regarding","related","rajat","roy","aishiki","pinaki","prasad",
        }
        kws = [w for w in re.split(r'\W+', filter_q.lower()) if len(w) > 1 and w not in stops]
        if kws:
            all_docs = [d for d in all_docs if any(
                kw in (
                    (d.get("filename","") or "").lower()
                    + " " + (d.get("subject","") or "").lower()
                    + " " + doc_category(d.get("filename","")).lower()
                )
                for kw in kws
            )]
    if not all_docs:
        push({"type":"token","content":"I don't see any documents in your vault yet."})
        return
    push({"type":"clear_streaming"})
    push({"type":"html","content":build_doc_table(all_docs, filter_q if filter_q else None)})

# ── send_email checkpoints ────────────────────────────────────────

def start_send_email(task, uid, sid, query, all_docs, push, obs):
    params = task.get("params", {})
    recipients = params.get("recipients", [])
    doc_refs   = params.get("doc_refs", [])
    tone       = params.get("tone", "")
    missing = []
    if not recipients: missing.append("recipient_email")
    if not doc_refs:   missing.append("doc_names")
    if not tone:       missing.append("tone")
    state = {
        "intent_type": "send_email", "stage": "collecting" if missing else "awaiting_approval",
        "recipients": recipients, "doc_refs": doc_refs, "tone": tone,
        "missing": missing, "original_query": query,
    }
    if missing:
        msg = "I'd love to help you send that email! Just need a few details:\n\n"
        if "recipient_email" in missing: msg += "To: What is the recipient's email address?\n"
        if "doc_names"       in missing: msg += "Attach: Which document(s) should I attach?\n"
        if "tone"            in missing: msg += "Tone: " + " | ".join(TONES) + "\n"
        push({"type":"token","content":msg})
        save_pending_task(uid, sid, state)
        return "[send_email CP1 — collecting]"
    return resume_send_email_cp2(state, uid, sid, all_docs, push, obs)

def resume_send_email(pending, user_reply, uid, sid, all_docs, push, obs):
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
    missing = pending.get("missing", [])
    reply_lower = user_reply.lower()
    if "recipient_email" in missing:
        emails_found = re.findall(r'[\w.+-]+@[\w.-]+\.\w+', user_reply)
        if emails_found:
            pending["recipients"] = emails_found
            missing = [m for m in missing if m != "recipient_email"]
    if "tone" in missing:
        for t in TONES:
            if t.lower() in reply_lower:
                pending["tone"] = t
                missing = [m for m in missing if m != "tone"]
                break
    if "doc_names" in missing and user_reply.strip():
        pending["doc_refs"] = [user_reply.strip()]
        missing = [m for m in missing if m != "doc_names"]
    pending["missing"] = missing
    if missing:
        msg = "Thanks! Still need:\n"
        if "recipient_email" in missing: msg += "To: recipient email address?\n"
        if "doc_names"       in missing: msg += "Which document(s) to attach?\n"
        if "tone"            in missing: msg += "Tone: " + " | ".join(TONES) + "\n"
        push({"type":"token","content":msg})
        save_pending_task(uid, sid, pending)
        return "[send_email CP1 — still collecting]"
    return resume_send_email_cp2(pending, uid, sid, all_docs, push, obs)

def resume_send_email_cp2(pending, uid, sid, all_docs, push, obs):
    push({"type":"status","message":"Generating email draft..."})
    doc_refs   = pending.get("doc_refs", [])
    tone       = pending.get("tone", "Professional")
    recipients = pending.get("recipients", [])
    resolved_docs = []
    for ref in doc_refs:
        doc = exact_doc_match(all_docs, ref)
        if not doc:
            _, sources = kb_search(ref)
            for src in sources:
                doc = exact_doc_match(all_docs, src)
                if doc: break
        if not doc:
            matches = fuzzy_doc_match(all_docs, ref)
            if matches: doc = matches[0]
        if doc and doc not in resolved_docs:
            resolved_docs.append(doc)
    doc_names = [d.get("filename","") for d in resolved_docs]
    doc_ids   = [d.get("document_id") or d.get("PK","").replace("DOC#","") for d in resolved_docs]
    rag_answer = ""
    for ref in doc_refs[:2]:
        chunks, _ = kb_search(ref)
        if chunks: rag_answer += chunks[0]["text"][:300] + " "
    draft_result = invoke_email_lambda("draft", {
        "rag_answer": rag_answer.strip(),
        "doc_names": doc_names,
        "tone": tone,
        "user_name": "FamilyVault User"
    }, uid)
    body_data = draft_result.get("body", {})
    if isinstance(body_data, str): body_data = json.loads(body_data)
    subject = body_data.get("draft_subject", "FamilyVault \u2014 Documents")
    body    = body_data.get("draft_body", "Dear Recipient,\n\nPlease find the requested documents attached.\n\nBest regards,\nFamilyVault AI")
    to_str   = ", ".join(recipients)
    docs_str = "\n".join("  - " + n for n in doc_names) if doc_names else "  (no documents resolved — please check doc name)"
    preview  = ("Here is the draft email. Please review:\n\n"
                "To: " + to_str + "\n"
                "Subject: " + subject + "\n"
                "Attachments:\n" + docs_str + "\n\n"
                + body + "\n\n"
                "Reply 'send' to confirm, 'edit [instructions]' to change, or 'cancel' to abort.")
    push({"type":"token","content":preview})
    pending.update({
        "stage": "awaiting_approval",
        "draft_subject": subject, "draft_body": body,
        "resolved_doc_ids": doc_ids, "resolved_doc_names": doc_names,
    })
    save_pending_task(uid, sid, pending)
    return "[send_email CP2 — awaiting approval]"

def _handle_send_email_approval(pending, user_reply, uid, sid, all_docs, push, obs):
    if user_reply.lower().strip().startswith("edit"):
        pending["stage"] = "editing"
        pending["edit_instruction"] = user_reply[4:].strip()
        save_pending_task(uid, sid, pending)
        return _handle_send_email_edit(pending, user_reply, uid, sid, all_docs, push, obs)
    if is_confirm(user_reply):
        return _execute_send_email(pending, uid, sid, push, obs)
    push({"type":"token","content":"Reply 'send' to confirm, 'edit [instructions]' to change, or 'cancel' to abort."})
    return "[send_email CP2 — waiting]"

def _handle_send_email_edit(pending, user_reply, uid, sid, all_docs, push, obs):
    instruction = pending.get("edit_instruction","") or user_reply
    old_body    = pending.get("draft_body","")
    draft_result = invoke_email_lambda("draft", {
        "rag_answer": old_body + "\n\nEdit instruction: " + instruction,
        "doc_names": pending.get("resolved_doc_names",[]),
        "tone": pending.get("tone","Professional"),
        "user_name": "FamilyVault User"
    }, uid)
    body_data = draft_result.get("body", {})
    if isinstance(body_data, str): body_data = json.loads(body_data)
    subject = body_data.get("draft_subject", pending.get("draft_subject",""))
    body    = body_data.get("draft_body", old_body)
    to_str   = ", ".join(pending.get("recipients",[]))
    docs_str = "\n".join("  - " + n for n in pending.get("resolved_doc_names",[]))
    preview  = ("Updated draft:\n\nTo: " + to_str + "\nSubject: " + subject
                + "\nAttachments:\n" + docs_str + "\n\n" + body
                + "\n\nReply 'send' to confirm, 'edit [instructions]' to change again, or 'cancel'.")
    push({"type":"token","content":preview})
    pending.update({"stage":"awaiting_approval","draft_subject":subject,"draft_body":body})
    save_pending_task(uid, sid, pending)
    return "[send_email CP2 — updated draft]"

def _execute_send_email(pending, uid, sid, push, obs):
    push({"type":"status","message":"Sending email..."})
    send_result = invoke_email_lambda("send", {
        "to":      pending.get("recipients",[]),
        "subject": pending.get("draft_subject","FamilyVault \u2014 Documents"),
        "body":    pending.get("draft_body",""),
        "doc_ids": pending.get("resolved_doc_ids",[]),
    }, uid)
    body_data = send_result.get("body", {})
    if isinstance(body_data, str): body_data = json.loads(body_data)
    clear_pending_task(uid, sid)
    if send_result.get("statusCode") == 200 and body_data.get("sent"):
        to_str   = ", ".join(pending.get("recipients",[]))
        docs_str = ", ".join(pending.get("resolved_doc_names",[])) or "none"
        push({"type":"token","content":"Email sent to " + to_str + ".\nAttachments: " + docs_str
              + ".\nThe recipient will receive download links valid for 24 hours."})
        return "[send_email CP3 — sent]"
    err_msg = body_data.get("error","Unknown error")
    push({"type":"token","content":"Sorry, the email could not be sent: " + err_msg + ". Please try again."})
    return "[send_email CP3 — error: " + err_msg + "]"

# ── delete_document checkpoints ───────────────────────────────────

def start_delete_document(task, uid, sid, all_docs, push, obs):
    query = task.get("params", {}).get("query", task.get("target",""))
    matches = fuzzy_doc_match(all_docs, query, require_hits=1)
    if not matches:
        push({"type":"token","content":"I couldn't find any documents matching '" + query + "'. Please check the name."})
        return "[delete CP1 — no match]"
    if len(matches) == 1:
        doc = matches[0]
        fname = doc.get("filename","")
        push({"type":"token","content":"I found this document:\n\n  " + fname
              + "\n\nAre you sure you want to permanently delete it? This cannot be undone.\nReply 'yes' or 'cancel'."})
        save_pending_task(uid, sid, {
            "intent_type": "delete_document", "stage": "awaiting_approval",
            "confirmed_docs": [{"doc_id": doc.get("document_id") or doc.get("PK","").replace("DOC#",""),
                                 "filename": fname, "s3_key": doc.get("s3_key","")}],
            "query": query,
        })
        return "[delete CP1 — single match]"
    lines = ["I found " + str(len(matches)) + " documents matching '" + query + "':\n"]
    for i, doc in enumerate(matches[:10], 1):
        lines.append(str(i) + ". " + doc.get("filename",""))
    lines.append("\nReply with number(s) e.g. '1' or '1,3' or 'all', or 'cancel'.")
    push({"type":"token","content":"\n".join(lines)})
    save_pending_task(uid, sid, {
        "intent_type": "delete_document", "stage": "selecting",
        "candidates": [{"doc_id": d.get("document_id") or d.get("PK","").replace("DOC#",""),
                        "filename": d.get("filename",""), "s3_key": d.get("s3_key","")} for d in matches[:10]],
        "query": query,
    })
    return "[delete CP1 — multiple matches]"

def resume_delete_document(pending, user_reply, uid, sid, push, obs):
    if is_cancel(user_reply):
        clear_pending_task(uid, sid)
        push({"type":"token","content":"Deletion cancelled. Your documents are safe."})
        return "[delete cancelled]"
    stage = pending.get("stage","")
    if stage == "selecting":           return _handle_delete_selection(pending, user_reply, uid, sid, push, obs)
    elif stage == "awaiting_approval": return _handle_delete_approval(pending, user_reply, uid, sid, push, obs)
    return "[delete unknown stage]"

def _handle_delete_selection(pending, user_reply, uid, sid, push, obs):
    candidates = pending.get("candidates", [])
    selected = candidates if "all" in user_reply.lower() else [
        candidates[int(n)-1] for n in re.findall(r'\d+', user_reply)
        if 0 <= int(n)-1 < len(candidates)
    ]
    if not selected:
        push({"type":"token","content":"I didn't understand. Reply with number(s) like '1' or '1,2', or 'cancel'."})
        return "[delete CP1 — bad selection]"
    lines = ["You selected " + str(len(selected)) + " document(s) for permanent deletion:\n"]
    for doc in selected: lines.append("  - " + doc["filename"])
    lines.append("\nThis CANNOT be undone. Reply 'yes' to confirm or 'cancel' to abort.")
    push({"type":"token","content":"\n".join(lines)})
    pending.update({"stage":"awaiting_approval","confirmed_docs":selected})
    save_pending_task(uid, sid, pending)
    return "[delete CP2 — awaiting approval]"

def _handle_delete_approval(pending, user_reply, uid, sid, push, obs):
    if is_confirm(user_reply): return _execute_delete(pending, uid, sid, push, obs)
    push({"type":"token","content":"Reply 'yes' to confirm permanent deletion, or 'cancel' to abort."})
    return "[delete CP2 — waiting]"

def _execute_delete(pending, uid, sid, push, obs):
    confirmed = pending.get("confirmed_docs", [])
    push({"type":"status","message":"Deleting " + str(len(confirmed)) + " document(s)..."})
    deleted, failed = [], []
    table = dynamodb.Table("DocumentMetadata")
    for doc in confirmed:
        try:
            table.update_item(Key={"PK": "DOC#" + doc.get("doc_id","")},
                              UpdateExpression="SET deleted = :t",
                              ExpressionAttributeValues={":t": True})
            if doc.get("s3_key"):
                try: s3.delete_object(Bucket=BUCKET, Key=doc["s3_key"])
                except Exception as e: print("S3 warn: " + str(e))
            deleted.append(doc.get("filename",""))
            print("Deleted: " + doc.get("doc_id","") + " / " + doc.get("filename",""))
        except Exception as e:
            print("Delete error: " + str(e))
            failed.append(doc.get("filename",""))
    try:
        bedrock_agent = boto3.client("bedrock-agent", region_name="eu-west-1")
        bedrock_agent.start_ingestion_job(knowledgeBaseId=KB_ID,
                                           dataSourceId=os.environ.get("BEDROCK_DS_ID","JZ13ZYCSRL"))
    except Exception as e: print("KB resync warn: " + str(e))
    clear_pending_task(uid, sid)
    if deleted:
        msg = "Deleted " + str(len(deleted)) + " document(s):\n" + "\n".join("  - " + f for f in deleted)
        if failed: msg += "\n\nCould not delete: " + ", ".join(failed)
        push({"type":"token","content":msg})
    else:
        push({"type":"token","content":"Could not delete the documents. Please try again."})
    return "[delete CP3 — done=" + str(len(deleted)) + "]"

# ================================================================
#  ORCHESTRATOR
# ================================================================

TASK_ORDER = ["list_documents","content_question","exact_download",
              "semantic_download","send_email","delete_document","out_of_scope"]

def orchestrate(query, uid, sid, push):
    t_start = time.time()
    obs = {"input_tokens":0,"output_tokens":0,"latency_ms":0,"planner_latency_ms":0,
           "answerer_latency_ms":0,"kb_latency_ms":0,"kb_chunks_retrieved":0,
           "tools_called":[],"model_id":ANSWERER_MODEL,"status":"ok","error":"",
           "query_len":len(query),"answer_len":0,"short_term_turns":0,"long_term_sessions":0}

    # BUG-A FIX: tell the frontend to clear any link cards from the previous turn
    push({"type":"clear_links"})

    push({"type":"status","message":"Thinking..."})
    short_term = load_short_term_memory(uid, sid, limit=6)
    long_term  = load_long_term_memory(uid, sid, max_sessions=3)
    obs["short_term_turns"]   = len(short_term) // 2
    obs["long_term_sessions"] = long_term.count("[Session")

    pending = load_pending_task(uid, sid)
    if pending:
        intent = pending.get("intent_type","")
        push({"type":"scratchpad","event":"plan","content":"Resuming: " + intent + " / " + pending.get("stage","?")})
        full_reply = ""
        if intent == "send_email":
            full_reply = resume_send_email(pending, query, uid, sid, get_user_docs(uid), push, obs)
        elif intent == "delete_document":
            full_reply = resume_delete_document(pending, query, uid, sid, push, obs)
        obs["latency_ms"] = int((time.time()-t_start)*1000)
        write_observation(uid, sid, obs); publish_metrics(uid, obs)
        push({"type":"scratchpad","event":"done","content":""})
        push({"type":"final","sources":[],"session_id":sid})
        save_turn(uid, sid, query, full_reply or "")
        return

    t_decomp = time.time()
    tasks = decompose(query, short_term)
    obs["planner_latency_ms"] = int((time.time()-t_decomp)*1000)
    obs["tools_called"] = [t.get("intent_type") for t in tasks]
    tasks.sort(key=lambda t: TASK_ORDER.index(t.get("intent_type","out_of_scope"))
               if t.get("intent_type") in TASK_ORDER else 99)

    plan_lines = ["  " + str(i) + ". " + t.get("intent_type","?") + " \u2192 " + t.get("target","")[:60]
                  for i, t in enumerate(tasks, 1)]
    push({"type":"scratchpad","event":"plan","content":"Tasks:\n" + "\n".join(plan_lines)})

    needs_docs = any(t.get("intent_type") in ("exact_download","list_documents","send_email","delete_document","semantic_download") for t in tasks)
    all_docs = get_user_docs(uid) if needs_docs else []

    full_reply, all_links, sources = "", [], []

    for task in tasks:
        intent = task.get("intent_type","out_of_scope")
        push({"type":"scratchpad","event":"step","content":"Running: " + intent + " \u2192 " + task.get("target","")[:60]})

        if intent == "list_documents":
            run_list_documents(task, uid, push, obs)
        elif intent == "content_question":
            full_reply += run_content_question(task, push, short_term, long_term, obs) + "\n\n"
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
            full_reply += start_send_email(task, uid, sid, query, all_docs, push, obs) + "\n\n"
        elif intent == "delete_document":
            if not all_docs: all_docs = get_user_docs(uid)
            full_reply += start_delete_document(task, uid, sid, all_docs, push, obs) + "\n\n"
        elif intent == "out_of_scope":
            msg = ("That is outside what I can help with. I am best at answering questions about "
                   "your documents, listing files, sharing download links, emailing or deleting files.")
            push({"type":"token","content":msg}); full_reply += msg

    if all_links:
        # BUG-E FIX: deduplicate by filename before pushing
        seen_fnames = set()
        unique_links = []
        for lnk in all_links:
            fn = lnk.get("filename","")
            if fn not in seen_fnames:
                seen_fnames.add(fn)
                unique_links.append(lnk)
        push({"type":"links","links":unique_links})

    obs["latency_ms"] = int((time.time()-t_start)*1000)
    obs["answer_len"] = len(full_reply)
    write_observation(uid, sid, obs); publish_metrics(uid, obs)
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
            print("Push FAILED: " + str(e))

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
