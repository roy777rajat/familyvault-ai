# ddb_updater.py — injected into vector_processor_lambda
# Updates DocumentMetadata status to INDEXED after successful vector storage.
import boto3
from datetime import datetime, timezone

_ddb = boto3.resource('dynamodb', region_name='eu-west-1')

def mark_doc_indexed(s3_key):
    """
    Parse doc_id from S3 key and update DocumentMetadata to INDEXED.
    S3 key format: user=<uid>/year=<y>/month=<m>/<doc_id>/<filename>
    """
    try:
        parts = s3_key.strip('/').split('/')
        # doc_id is index 3 (after user=, year=, month=)
        doc_id = parts[3] if len(parts) >= 5 else None
        if not doc_id:
            print(f'[DDB] Could not extract doc_id from key: {s3_key}')
            return
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
        print(f'[DDB] DOC#{doc_id} -> INDEXED')
    except Exception as e:
        print(f'[DDB] mark_indexed error for key {s3_key}: {e}')
