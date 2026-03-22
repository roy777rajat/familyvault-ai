"""
FamilyVault AI — Chat Handler v12
Architecture: Planner → Orchestrator → Tools → Streamer

Flow:
  1. PLANNER   : Claude Haiku reads user query, produces JSON execution plan
  2. ORCHESTRATOR: Executes plan steps in order, accumulates context
  3. TOOLS     : document_list | search_documents | download_document | answer_question | out_of_scope
  4. STREAMER  : pushes tokens / html / links / scratchpad back over WebSocket

Version History:
  v1-v7:  Various iterations of intent detection (regex-based, unreliable)
  v8:     First Planner+Orchestrator architecture
  v9:     Push logging, relative score threshold (failed - scores cluster at 0.61)
  v10:    WebSocket push fix, clear_streaming message type
  v11:    Keyword-grounded download (not score-based)
  v12:    Smart document_list filter, score display, agent scratchpad streaming
"""
import json, boto3, os, uuid, re
from datetime import datetime, timezone

dynamodb = boto3.resource("dynamodb", region_name="eu-west-1")
bedrock  = boto3.client("bedrock-runtime", region_name="eu-west-1")
s3       = boto3.client("s3", region_name="eu-west-1")

KB_ID          = os.environ.get("BEDROCK_KB_ID", "PYV06IINGT")
BUCKET         = os.environ.get("BUCKET", "family-docs-raw")
PLANNER_MODEL  = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
ANSWERER_MODEL = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"

WELCOME = (
    "Hello! I am FamilyVault AI \u2014 your personal document assistant. "
    "I can answer questions about your document contents, list everything stored in your vault, "
    "share secure download links, or handle all of these together in one request. "
    "Just ask naturally \u2014 for example: "
    "\"What is my PAN card number and can you share its download link?\", "
    "\"List my documents and tell me which semester I scored the highest SGPA\", "
    "or \"How many documents do I have?\"."
)

# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n#  PLANNER SYSTEM PROMPT
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
PLANNER_SYSTEM = """You are the Planner for FamilyVault AI, a personal document assistant.

Your job is to read the user's question and produce a JSON execution plan.

Available tools:
1. document_list    \u2014 Fetch user document list from DynamoDB.
                      Supports optional "filter" for targeted queries:
                        {"tool":"document_list","filter":"pan card","reason":"..."}
                        {"tool":"document_list","filter":"insurance","reason":"..."}
                      Omit "filter" to show ALL documents.
2. search_documents \u2014 Semantic search over document contents via Bedrock KB
3. download_document\u2014 Generate presigned download links for KB-matched documents
4. answer_question  \u2014 Generate a natural language answer using retrieved context
5. out_of_scope     \u2014 User asked something unrelated to documents

RULES:
- Return ONLY a valid JSON array. No markdown, no explanation.
- Each step: {"tool": "<name>", "query": "<search string>", "reason": "<why>"}
- Use "query" only for search_documents steps.
- Use "filter" only for document_list steps (keyword to filter by).
- Include download_document ONLY if user EXPLICITLY asked for a link/download/url.
- Include answer_question if there is a content question to answer.
- Maximum 4 steps.

Examples:
User: "What is my PAN card number?"
Plan: [{"tool":"search_documents","query":"PAN card number","reason":"Find PAN card"},{"tool":"answer_question","reason":"Answer question"}]

User: "List all my documents"
Plan: [{"tool":"document_list","reason":"Show full document inventory"}]

User: "Do I have any insurance documents?"
Plan: [{"tool":"document_list","filter":"insurance","reason":"Filter to insurance docs"}]

User: "Share PAN card details and download link"
Plan: [{"tool":"search_documents","query":"PAN card","reason":"Find PAN card"},{"tool":"answer_question","reason":"Share details"},{"tool":"download_document","reason":"User asked for link"}]

User: "What is the weather today?"
Plan: [{"tool":"out_of_scope"}]"""


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
#  HELPERS
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
def get_user_docs(uid):
    from boto3.dynamodb.conditions import Attr
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
    title = f"Documents matching '{filter_label}' ({len(docs)} found)" if filter_label else f"Your Documents ({len(docs)} total)"
    rows = ""
    for i, d in enumerate(sort_docs(docs), 1):
        fname = d.get("filename", "\u2014")
        cat   = doc_category(fname)
        src   = source_label(d)
        date  = fmt_date(d.get("received_at") or d.get("uploaded_at", ""))
        st    = d.get("status", "\u2014")
        sc    = "st-ok" if st == "INDEXED" else "st-proc" if "PROCESS" in st else "st-pend"
        sl    = "Indexed" if st == "INDEXED" else "Processing" if "PROCESS" in st else st
        rows += f"<tr><td class='tsl'>{i}</td><td class='tfn'>{fname}</td><td class='tca'>{cat}</td><td class='tsr'>{src}</td><td class='tdt'>{date}</td><td><span class='tbl-st {sc}'>{sl}</span></td></tr>"
    return f'<div class="doc-table-wrap"><div class="doc-table-hd">{title}</div><div class="doc-table-scroll"><table class="doc-table"><thead><tr><th>Sl</th><th>Document Name</th><th>Category</th><th>Source</th><th>Date</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table></div></div>'


def save_turn(uid, sid, question, answer):
    try:
        dynamodb.Table("ChatSessions").put_item(Item={
            "PK": "USER#" + uid, "SK": "SESSION#" + sid + "#TURN#" + str(uuid.uuid4()),
            "session_id": sid, "question": question, "answer": answer[:600],
            "sources": [], "created_at": datetime.now(timezone.utc).isoformat(), "deleted": False
        })
    except Exception as e:
        print(f"DDB save: {e}")


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
#  PLANNER
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
def plan(query):
    try:
        resp = bedrock.invoke_model(
            modelId=PLANNER_MODEL,
            body=json.dumps({"anthropic_version": "bedrock-2023-05-31", "max_tokens": 512,
                             "system": PLANNER_SYSTEM, "messages": [{"role": "user", "content": query}]})
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


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
#  TOOL: search_documents
#  KB retrieve \u2192 score filter \u2192 dedup \u2192 rerank
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
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
    print(f"KB raw: {len(raw_results)} results for '{query[:60]}'")
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
    print(f"KB filtered: {len(chunks)} chunks, sources={sources}")
    return chunks, sources


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
#  TOOL: document_list (with optional keyword filter)
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
def tool_document_list(uid, filter_query=None):
    all_docs = get_user_docs(uid)
    if not filter_query or not filter_query.strip():
        return all_docs, False
    fq = filter_query.lower().strip()
    stops = {"the","a","an","of","in","for","and","or","my","all","show","list","have","do","i","any","some","about"}
    keywords = [w for w in re.split(r'\W+', fq) if len(w) > 1 and w not in stops]
    if not keywords: return all_docs, False
    matched = [d for d in all_docs if any(
        kw in f"{(d.get('filename','') or '').lower()} {doc_category(d.get('filename','')).lower()} {(d.get('subject','') or '').lower()} {(d.get('sender_email','') or '').lower()}"
        for kw in keywords
    )]
    return matched, True


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
#  TOOL: download_document
#  Keyword-grounded: only links docs matching Planner's search query keywords
#  NOTE: KB scores cluster at 0.61+/-0.02 making score-based filtering impossible
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
def tool_download_document(all_docs, grounded_sources, search_queries=None):
    if not grounded_sources: return []
    query_keywords = set()
    if search_queries:
        stops = {"the","for","and","of","a","an","in","on","at","to","with","details","number",
                 "what","is","my","their","from","about","show","find","get","tell","please","can","you"}
        for q in search_queries:
            for w in re.split(r'\W+', q.lower()):
                if len(w) > 2 and w not in stops: query_keywords.add(w)
    print(f"Download keywords: {query_keywords}")
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
    print(f"Keyword-matched sources: {target_sources}")
    matched = []
    for doc in all_docs:
        fname = (doc.get("filename") or "").lower().strip()
        for src in target_sources:
            if fname == src.lower() or fname in src.lower() or src.lower() in fname:
                if doc not in matched: matched.append(doc)
                break
    links = []
    for doc in matched[:5]:
        s3_key = doc.get("s3_key", "")
        fname  = doc.get("filename", "document")
        if s3_key:
            url = make_presigned(s3_key, fname)
            if url: links.append({"filename": fname, "url": url})
    print(f"Download: {len(links)} links for sources={target_sources}")
    return links


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
#  TOOL: answer_question
#  Claude streams answer using accumulated chunk context
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
def tool_answer_question(query, all_chunks, push_fn):
    if not all_chunks:
        rag_context = "No relevant document content was found for this query."
    else:
        ctx_parts = []
        for ch in all_chunks[:6]:
            fname = ch.get("filename", "")
            score = ch.get("score", 0)
            src = f"[Source: {fname} | Score: {score:.3f}]" if fname else ""
            ctx_parts.append(f"{src}\n{ch['text']}")
        rag_context = "\n\n---\n\n".join(ctx_parts)
    system = f"""You are FamilyVault AI \u2014 a warm, professional personal document assistant.
Answer the user's question using ONLY the retrieved document content below.

RETRIEVED DOCUMENT CONTENT:
{rag_context}

STRICT RULES:
1. Answer ONLY from retrieved content. Never invent or hallucinate.
2. Be specific \u2014 quote exact values (numbers, dates, grades, names) when found.
3. Mention which document the info comes from, naturally.
4. If content doesn't answer the question: "I wasn't able to find that specific detail. Could you give more context \u2014 for example the document type or a keyword?"
5. NEVER use markdown bold (**) or bullet stars (*). Plain sentences only.
6. NEVER say \"I don't have download links\" \u2014 the system handles links separately.
7. NEVER list all documents you have access to.
8. NEVER start with \"Based on retrieved content\" or \"According to the documents\"."""
    full = ""
    try:
        stream = bedrock.invoke_model_with_response_stream(
            modelId=ANSWERER_MODEL,
            body=json.dumps({"anthropic_version": "bedrock-2023-05-31", "max_tokens": 900,
                             "system": system, "messages": [{"role": "user", "content": query}]})
        )
        for ev in stream["body"]:
            chunk = json.loads(ev["chunk"]["bytes"])
            if chunk.get("type") == "content_block_delta":
                token = chunk.get("delta", {}).get("text", "")
                if token:
                    full += token
                    push_fn({"type": "token", "content": token})
    except Exception as e:
        print(f"Answerer error: {e}")
        msg = "Sorry, I had trouble generating a response. Please try again."
        push_fn({"type": "token", "content": msg})
        full = msg
    return full


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
#  ORCHESTRATOR
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
def orchestrate(query, uid, sid, push):
    push({"type": "status", "message": "Understanding your request..."})
    steps = plan(query)

    # Stream plan to scratchpad
    plan_lines = []
    for i, s in enumerate(steps, 1):
        q_part = f' \u2192 query: "{s["query"]}"' if s.get("query") else ""
        f_part = f' \u2192 filter: "{s["filter"]}"' if s.get("filter") else ""
        plan_lines.append(f"  Step {i}: {s.get('tool','?')}{q_part}{f_part}  # {s.get('reason','')}")
    push({"type": "scratchpad", "event": "plan", "content": "Plan:\n" + "\n".join(plan_lines)})

    all_chunks, all_sources, score_map = [], [], {}
    all_docs, full_reply, search_queries = None, "", []
    has_list     = any(s["tool"] == "document_list"    for s in steps)
    has_download = any(s["tool"] == "download_document" for s in steps)

    if has_list or has_download:
        push({"type": "status", "message": "Fetching your documents..."})
        all_docs = get_user_docs(uid)

    for step in steps:
        tool = step.get("tool")
        print(f"Orchestrator \u2192 {tool}: {step.get('reason','')}")
        push({"type": "scratchpad", "event": "step",
              "content": f"Executing: {tool}  ({(step.get('query') or step.get('filter') or step.get('reason',''))[:80]})"})

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
                    return
                push({"type": "token", "content": "\n"})

        elif tool == "search_documents":
            search_query = step.get("query", query)
            search_queries.append(search_query)
            push({"type": "status", "message": f"Searching: {search_query[:50]}..."})
            chunks, sources = tool_search_documents(search_query)
            push({"type": "scratchpad", "event": "result",
                  "content": f"  Found {len(chunks)} chunks from: {', '.join(sources) if sources else 'no matches'}"})
            existing_sigs = {ck["text"][:120] for ck in all_chunks}
            for ch in chunks:
                if ch["text"][:120] not in existing_sigs:
                    all_chunks.append(ch); existing_sigs.add(ch["text"][:120])
                fn, sc = ch.get("filename",""), ch.get("score",0)
                if fn: score_map[fn] = max(score_map.get(fn, 0), sc)
            for src in sources:
                if src not in all_sources: all_sources.append(src)

        elif tool == "answer_question":
            push({"type": "status", "message": "Preparing answer..."})
            full_reply += tool_answer_question(query, all_chunks, push)

        elif tool == "download_document":
            if not all_docs: all_docs = get_user_docs(uid)
            links = tool_download_document(all_docs, all_sources, search_queries)
            if not links:
                no_match = ("\n\nRegarding download links: I wasn't able to identify the specific document. "
                            "Could you mention the name or type? e.g. \"PAN card\" or \"Sem-1 result\".")
                push({"type": "token", "content": no_match}); full_reply += no_match
            else:
                count = len(links)
                intro = (f"\n\nHere {'is' if count==1 else 'are'} the secure download "
                         f"link{'s' if count>1 else ''} for the matched document{'s' if count>1 else ''} (valid 24h):")
                push({"type": "token", "content": intro}); full_reply += intro
                scored_sources = [f"{s} ({score_map.get(s,0):.2f})" if score_map.get(s) else s for s in all_sources]
                push({"type": "scratchpad", "event": "done", "content": ""})
                push({"type": "final", "sources": scored_sources, "session_id": sid})
                push({"type": "links", "links": links})
                save_turn(uid, sid, query, full_reply); return

        elif tool == "out_of_scope":
            reply = ("That is a bit outside what I can help with. "
                     "I am best at answering questions about your stored documents, listing files, or sharing download links. "
                     "Is there something document-related I can help with?")
            push({"type": "token", "content": reply})
            push({"type": "final", "sources": [], "session_id": sid})
            save_turn(uid, sid, query, reply); return

    push({"type": "scratchpad", "event": "done", "content": ""})
    scored_sources = [f"{s} ({score_map.get(s,0):.2f})" if score_map.get(s) else s for s in all_sources]
    push({"type": "final", "sources": scored_sources, "session_id": sid})
    save_turn(uid, sid, query, full_reply or "[Document list shown]")


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
#  LAMBDA ENTRY POINT
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
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
            print(f"PUSH type={data.get('type')} size={len(payload)}")
            apigw.post_to_connection(ConnectionId=cid, Data=payload)
        except Exception as e:
            print(f"Push FAILED type={data.get('type','?')} err={e}")
    if not query or query.lower() in ("hi", "hello", "hey", "start"):
        for i in range(0, len(WELCOME), 8): push({"type": "token", "content": WELCOME[i:i+8]})
        push({"type": "final", "sources": [], "session_id": sid})
        return {"statusCode": 200, "body": "OK"}
    try:
        orchestrate(query, uid, sid, push)
    except Exception as e:
        print(f"Orchestrator error: {e}")
        push({"type": "error", "message": "Something went wrong. Please try again."})
    return {"statusCode": 200, "body": "OK"}
