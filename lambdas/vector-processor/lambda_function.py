import json, boto3, os, re
from datetime import datetime, timezone

s3_client   = boto3.client('s3',      region_name='eu-west-1')
dynamodb    = boto3.resource('dynamodb', region_name='eu-west-1')
textract    = boto3.client('textract', region_name='eu-west-1')

VECTOR_BUCKET = os.environ.get('VECTOR_BUCKET', 'family-docs-vectors')
VECTOR_INDEX  = os.environ.get('VECTOR_INDEX',  'family-docs-index')


def lambda_handler(event, context):
    print('Lambda triggered')
    for record in event.get('Records', []):
        bucket = record['s3']['bucket']['name']
        key    = record['s3']['object']['key']
        print(f'Processing: s3://{bucket}/{key}')
        try:
            process_document(bucket, key)
        except Exception as e:
            print(f'Error processing {key}: {e}')
            mark_doc_status(key, 'FAILED')


def process_document(bucket, key):
    # ── 1. Textract OCR ──────────────────────────────────────────
    print(f'Starting Textract for {key}')
    response = textract.detect_document_text(
        Document={'S3Object': {'Bucket': bucket, 'Name': key}}
    )
    text = ' '.join(
        b['Text'] for b in response.get('Blocks', [])
        if b['BlockType'] == 'LINE'
    )
    print(f'Extracted {len(text)} chars, {len(text.split())} words')

    if not text.strip():
        print(f'No text extracted from {key}, skipping vector storage')
        mark_doc_status(key, 'FAILED')
        return

    # ── 2. Chunk ──────────────────────────────────────────────────
    chunks = chunk_text(text)
    print(f'Created {len(chunks)} chunks')

    # ── 3. Embed + store vectors ──────────────────────────────────
    bedrock   = boto3.client('bedrock-runtime', region_name='eu-west-1')
    s3v       = boto3.client('s3vectors',        region_name='eu-west-1')
    doc_id    = extract_doc_id(key)
    filename  = key.split('/')[-1]
    user_id   = extract_user_id(key)

    vectors = []
    for i, chunk in enumerate(chunks):
        embed_resp = bedrock.invoke_model(
            modelId='amazon.titan-embed-text-v2:0',
            body=json.dumps({'inputText': chunk}),
            contentType='application/json',
            accept='application/json'
        )
        embedding = json.loads(embed_resp['body'].read())['embedding']
        vectors.append({
            'key':       f'{doc_id}_{i}',
            'data':      {'float32': embedding},
            'metadata':  {
                'doc_id':   doc_id,
                'filename': filename,
                'user_id':  user_id,
                'chunk_id': i,
                'text':     chunk[:500]
            }
        })

    s3v.put_vectors(
        vectorBucketName=VECTOR_BUCKET,
        indexName=VECTOR_INDEX,
        vectors=vectors
    )
    print(f'S3Vectors: stored {len(vectors)} vectors for {filename} (doc_id={doc_id})')

    if os.environ.get('BEDROCK_KB_SYNC') == 'true':
        print(f'BEDROCK_KB_SYNC: wrote {len(vectors)} vectors to S3 Vectors')

    # ── 4. Update DynamoDB status to INDEXED ─────────────────────
    mark_doc_status(key, 'INDEXED')


def mark_doc_status(s3_key, status):
    """Update DocumentMetadata status by parsing doc_id from the S3 key."""
    doc_id = extract_doc_id(s3_key)
    if not doc_id:
        print(f'[DDB] Could not parse doc_id from key: {s3_key}')
        return
    try:
        update_expr = 'SET #s = :s, indexed_at = :t' if status == 'INDEXED' else 'SET #s = :s'
        expr_values = {':s': status}
        if status == 'INDEXED':
            expr_values[':t'] = datetime.now(timezone.utc).isoformat()
        dynamodb.Table('DocumentMetadata').update_item(
            Key={'PK': f'DOC#{doc_id}'},
            UpdateExpression=update_expr,
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues=expr_values
        )
        print(f'[DDB] DOC#{doc_id} → {status}')
    except Exception as e:
        print(f'[DDB] update error for {doc_id}: {e}')


def extract_doc_id(s3_key):
    """Parse doc_id from: user=<uid>/year=<y>/month=<m>/<doc_id>/<filename>"""
    try:
        parts = s3_key.strip('/').split('/')
        # doc_id is index 3 (after user=, year=, month=)
        return parts[3] if len(parts) >= 5 else None
    except Exception:
        return None


def extract_user_id(s3_key):
    """Parse user_id from: user=<uid>/..."""
    try:
        match = re.search(r'user=([^/]+)', s3_key)
        return match.group(1) if match else 'unknown'
    except Exception:
        return 'unknown'


def chunk_text(text, max_words=300):
    words = text.split()
    return [
        ' '.join(words[i:i + max_words])
        for i in range(0, len(words), max_words)
    ] or [text]
