# ddb_updater.py — injected into vector_processor_lambda
# Updates DocumentMetadata status to INDEXED after successful vector storage.
import boto3, re
from datetime import datetime, timezone

_ddb = boto3.resource('dynamodb', region_name='eu-west-1')

def _extract_doc_id(s3_key):
    """
    Extract doc_id (UUID) from S3 key — handles both path formats:

    Upload path:  user=<uid>/year=<y>/month=<m>/<doc_id>/<filename>
    Email path:   year=<y>/month=<m>/<doc_id>/<filename>

    Strategy: find the first UUID-shaped segment in the key.
    """
    UUID_RE = re.compile(
        r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
        re.IGNORECASE
    )
    match = UUID_RE.search(s3_key)
    if match:
        return match.group(0)

    # Fallback: positional — upload format index 3, email format index 2
    parts = s3_key.strip('/').split('/')
    for idx in (3, 2):
        if len(parts) > idx:
            candidate = parts[idx]
            # Must look like a doc_id (not year=, month=, user=, filename)
            if not any(candidate.startswith(p) for p in ('user=', 'year=', 'month=')):
                if '.' not in candidate:   # filenames have extensions
                    return candidate
    return None


def mark_doc_indexed(s3_key):
    """
    Parse doc_id from S3 key and update DocumentMetadata to INDEXED.

    Handles:
      - user=<uid>/year=<y>/month=<m>/<doc_id>/<filename>   (browser upload)
      - year=<y>/month=<m>/<doc_id>/<filename>               (email ingestion)
    """
    doc_id = _extract_doc_id(s3_key)
    if not doc_id:
        print(f'[DDB] Could not extract doc_id from key: {s3_key}')
        return
    try:
        _ddb.Table('DocumentMetadata').update_item(
            Key={'PK': f'DOC#{doc_id}'},
            UpdateExpression='SET #s = :s, indexed_at = :t',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={
                ':s': 'INDEXED',
                ':t': datetime.now(timezone.utc).isoformat()
            },
            ConditionExpression='attribute_exists(PK)'
        )
        print(f'[DDB] DOC#{doc_id} -> INDEXED (key={s3_key})')
    except Exception as e:
        print(f'[DDB] mark_indexed error for doc_id={doc_id} key={s3_key}: {e}')
