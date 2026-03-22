import json, boto3, uuid, os
from datetime import datetime, timezone

s3 = boto3.client('s3', region_name='eu-west-1')
dynamodb = boto3.resource('dynamodb', region_name='eu-west-1')
BUCKET = 'family-docs-raw'
ALLOWED_TYPES = ['application/pdf','application/msword',
                 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                 'text/plain','image/jpeg','image/jpg','image/png']

def lambda_handler(event, context):
    path = event.get('rawPath', '')
    method = event.get('requestContext', {}).get('http', {}).get('method', 'POST')
    body = json.loads(event.get('body', '{}') or '{}')
    claims = event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {})
    user_id = claims.get('sub', 'unknown')

    print(f"method={method} path={path} uid={user_id}")

    if method == 'OPTIONS':
        return {'statusCode': 200, 'headers': cors_headers(), 'body': ''}
    if path == '/documents' and method == 'GET':
        return list_documents(user_id)
    if path == '/upload/presign' and method == 'POST':
        return generate_presign(user_id, body)
    if path == '/upload/complete' and method == 'POST':
        return mark_complete(user_id, body)
    if path == '/upload/status' and method == 'GET':
        params = event.get('queryStringParameters') or {}
        return get_status(user_id, params.get('document_id', ''))
    return {'statusCode': 404, 'headers': cors_headers(), 'body': json.dumps({'error': f'Route not found: {method} {path}'})}

def list_documents(user_id):
    from boto3.dynamodb.conditions import Attr
    table = dynamodb.Table('DocumentMetadata')
    result = table.scan(FilterExpression=Attr('user_id').eq(user_id) & Attr('deleted').ne(True))
    docs = result.get('Items', [])
    while 'LastEvaluatedKey' in result:
        result = table.scan(
            FilterExpression=Attr('user_id').eq(user_id) & Attr('deleted').ne(True),
            ExclusiveStartKey=result['LastEvaluatedKey']
        )
        docs.extend(result.get('Items', []))
    print(f"Found {len(docs)} documents for user {user_id}")
    return {'statusCode': 200, 'headers': cors_headers(), 'body': json.dumps({'documents': docs}, default=str)}

def generate_presign(user_id, body):
    filename = (body.get('filename') or '').strip()
    content_type = (body.get('content_type') or 'application/pdf').strip()
    if not filename:
        return {'statusCode': 400, 'headers': cors_headers(), 'body': json.dumps({'error': 'filename is required'})}
    if content_type not in ALLOWED_TYPES:
        content_type = 'application/octet-stream'
    doc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    s3_key = f"user={user_id}/year={now.year}/month={now.month:02d}/{doc_id}/{filename}"
    dynamodb.Table('DocumentMetadata').put_item(Item={
        'PK': f'DOC#{doc_id}', 'document_id': doc_id, 'user_id': user_id,
        'filename': filename, 's3_key': s3_key, 'content_type': content_type,
        'status': 'PENDING', 'deleted': False, 'uploaded_at': now.isoformat()
    })
    presigned_url = s3.generate_presigned_url('put_object',
        Params={'Bucket': BUCKET, 'Key': s3_key, 'ContentType': content_type}, ExpiresIn=300)
    print(f"Presign OK: doc_id={doc_id} key={s3_key}")
    return {'statusCode': 200, 'headers': cors_headers(),
            'body': json.dumps({'presigned_url': presigned_url, 'document_id': doc_id, 's3_key': s3_key})}

def mark_complete(user_id, body):
    doc_id = body.get('document_id', '')
    if not doc_id:
        return {'statusCode': 400, 'headers': cors_headers(), 'body': json.dumps({'error': 'document_id required'})}
    dynamodb.Table('DocumentMetadata').update_item(
        Key={'PK': f'DOC#{doc_id}'},
        UpdateExpression='SET #s = :s',
        ExpressionAttributeNames={'#s': 'status'},
        ExpressionAttributeValues={':s': 'UPLOADED_PROCESSING'}
    )
    return {'statusCode': 200, 'headers': cors_headers(),
            'body': json.dumps({'document_id': doc_id, 'status': 'UPLOADED_PROCESSING'})}

def get_status(user_id, doc_id):
    try:
        item = dynamodb.Table('DocumentMetadata').get_item(Key={'PK': f'DOC#{doc_id}'}).get('Item', {})
        return {'statusCode': 200, 'headers': cors_headers(),
                'body': json.dumps({'status': item.get('status', 'UNKNOWN'), 'document_id': doc_id})}
    except Exception as e:
        return {'statusCode': 500, 'headers': cors_headers(), 'body': json.dumps({'error': str(e)})}

def cors_headers():
    return {'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization,X-Amz-Date,X-Api-Key',
            'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS'}
