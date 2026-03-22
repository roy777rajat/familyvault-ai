import json, boto3, os
from boto3.dynamodb.conditions import Attr

s3       = boto3.client('s3', region_name='eu-west-1')
dynamodb = boto3.resource('dynamodb', region_name='eu-west-1')
bedrock  = boto3.client('bedrock-agent', region_name='eu-west-1')

BUCKET = os.environ.get('BUCKET', 'family-docs-raw')
TABLE  = 'DocumentMetadata'
KB_ID  = os.environ.get('BEDROCK_KB_ID', 'PYV06IINGT')
DS_ID  = os.environ.get('BEDROCK_DS_ID', 'JZ13ZYCSRL')


def cors():
    return {'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
            'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS'}

def ok(body):     return {'statusCode': 200, 'headers': cors(), 'body': json.dumps(body)}
def err(c, m):    return {'statusCode': c,   'headers': cors(), 'body': json.dumps({'error': m})}

def get_uid(event):
    return event.get('requestContext',{}).get('authorizer',{}).get('jwt',{}).get('claims',{}).get('sub','unknown')


def lambda_handler(event, context):
    method = event.get('requestContext',{}).get('http',{}).get('method','DELETE').upper()
    path   = event.get('rawPath', event.get('path', '/'))
    uid    = get_uid(event)
    print(f"method={method} path={path} uid={uid}")

    if method == 'OPTIONS': return {'statusCode': 200, 'headers': cors(), 'body': ''}
    if method != 'DELETE':  return err(405, 'Method not allowed')

    parts  = path.strip('/').split('/')
    doc_id = parts[-1] if parts else ''
    if not doc_id or doc_id == 'documents': return err(400, 'document_id is required')

    print(f"Deleting doc_id={doc_id} for uid={uid}")
    table = dynamodb.Table(TABLE)

    # 1. Get item
    try:
        item = table.get_item(Key={'PK': 'DOC#' + doc_id}).get('Item')
        if not item: return err(404, 'Document not found')
        if item.get('user_id') and item.get('user_id') != uid: return err(403, 'Not authorised')
    except Exception as e:
        return err(500, str(e))

    # 2. Delete from S3
    s3_key = item.get('s3_key', '')
    if s3_key:
        try: s3.delete_object(Bucket=BUCKET, Key=s3_key); print(f"S3 deleted: {s3_key}")
        except Exception as e: print(f"S3 delete warning: {e}")

    # 3. Soft-delete in DynamoDB
    try:
        table.update_item(Key={'PK': 'DOC#' + doc_id},
                          UpdateExpression='SET deleted = :t',
                          ExpressionAttributeValues={':t': True})
        print(f"DDB soft-deleted: {doc_id}")
    except Exception as e:
        return err(500, str(e))

    # 4. Trigger Bedrock KB resync (non-fatal)
    try:
        bedrock.start_ingestion_job(knowledgeBaseId=KB_ID, dataSourceId=DS_ID)
        print("KB resync triggered")
    except Exception as e:
        print(f"KB resync warning: {e}")

    return ok({'deleted': True, 'document_id': doc_id})
