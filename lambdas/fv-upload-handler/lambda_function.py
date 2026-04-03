import json, boto3, uuid, os
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Attr, Key

s3 = boto3.client("s3", region_name="eu-west-1")
dynamodb = boto3.resource("dynamodb", region_name="eu-west-1")
BUCKET = "family-docs-raw"
ALLOWED_TYPES = ["application/pdf","application/msword","application/vnd.openxmlformats-officedocument.wordprocessingml.document","text/plain","image/jpeg","image/jpg","image/png"]

def lambda_handler(event, context):
    path = event.get("rawPath", "")
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    body = json.loads(event.get("body", "{}") or "{}")
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    user_id = claims.get("sub", "unknown")
    print(f"method={method} path={path} uid={user_id}")
    if method == "OPTIONS":
        return {"statusCode": 200, "headers": cors(), "body": ""}
    if path == "/documents" and method == "GET":
        return list_documents(user_id)
    if path == "/upload/presign" and method == "POST":
        return generate_presign(user_id, body)
    if path == "/upload/complete" and method == "POST":
        return mark_complete(user_id, body)
    if path == "/upload/status" and method == "GET":
        params = event.get("queryStringParameters") or {}
        return get_status(user_id, params.get("document_id", ""))
    if path == "/notifications" and method == "GET":
        return get_notifications(user_id)
    if path == "/notifications/read" and method == "POST":
        return mark_notifications_read(user_id, body)
    return {"statusCode": 404, "headers": cors(), "body": json.dumps({"error": f"Not found: {method} {path}"})}

def list_documents(user_id):
    """Return ALL user docs — no uploaded_at filter. Sorted newest first."""
    table = dynamodb.Table("DocumentMetadata")
    result = table.scan(FilterExpression=Attr("user_id").eq(user_id) & Attr("deleted").ne(True))
    docs = result.get("Items", [])
    while "LastEvaluatedKey" in result:
        result = table.scan(
            FilterExpression=Attr("user_id").eq(user_id) & Attr("deleted").ne(True),
            ExclusiveStartKey=result["LastEvaluatedKey"]
        )
        docs.extend(result.get("Items", []))
    # Sort: docs with uploaded_at newest first, those without go to bottom
    docs.sort(key=lambda d: d.get("uploaded_at") or "", reverse=True)
    print(f"Returning {len(docs)} docs for {user_id}")
    return {"statusCode": 200, "headers": cors(), "body": json.dumps({"documents": docs}, default=str)}

def get_notifications(user_id):
    """Return email send history as notifications with unread count."""
    print(f"GET /notifications for {user_id}")
    table = dynamodb.Table("EmailSentLog")
    try:
        result = table.query(
            KeyConditionExpression=Key("PK").eq(f"USER#{user_id}"),
            ScanIndexForward=False,
            Limit=20
        )
        items = result.get("Items", [])
        print(f"Found {len(items)} notifications")
        notifications = []
        unread = 0
        for item in items:
            is_read = bool(item.get("read", False))
            if not is_read:
                unread += 1
            notifications.append({
                "id": item.get("SK", ""),
                "type": "email_sent",
                "subject": item.get("subject", "Document shared"),
                "doc_count": int(item.get("doc_count", 0)),
                "sent_at": item.get("sent_at", ""),
                "to": item.get("to", []),
                "read": is_read
            })
        return {"statusCode": 200, "headers": cors(), "body": json.dumps({"notifications": notifications, "unread_count": unread})}
    except Exception as e:
        print(f"Notifications error: {e}")
        return {"statusCode": 500, "headers": cors(), "body": json.dumps({"error": str(e)})}

def mark_notifications_read(user_id, body):
    """Mark all or specific notifications as read."""
    table = dynamodb.Table("EmailSentLog")
    try:
        result = table.query(KeyConditionExpression=Key("PK").eq(f"USER#{user_id}"))
        ids = [item["SK"] for item in result.get("Items", []) if not item.get("read", False)]
        for sk in ids:
            table.update_item(
                Key={"PK": f"USER#{user_id}", "SK": sk},
                UpdateExpression="SET #r = :r",
                ExpressionAttributeNames={"#r": "read"},
                ExpressionAttributeValues={":r": True}
            )
        return {"statusCode": 200, "headers": cors(), "body": json.dumps({"marked_read": len(ids)})}
    except Exception as e:
        return {"statusCode": 500, "headers": cors(), "body": json.dumps({"error": str(e)})}

def generate_presign(user_id, body):
    filename = (body.get("filename") or "").strip()
    content_type = (body.get("content_type") or "application/pdf").strip()
    if not filename:
        return {"statusCode": 400, "headers": cors(), "body": json.dumps({"error": "filename required"})}
    if content_type not in ALLOWED_TYPES:
        content_type = "application/octet-stream"
    doc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    s3_key = f"user={user_id}/year={now.year}/month={now.month:02d}/{doc_id}/{filename}"
    dynamodb.Table("DocumentMetadata").put_item(Item={
        "PK": f"DOC#{doc_id}", "document_id": doc_id, "user_id": user_id,
        "filename": filename, "s3_key": s3_key, "content_type": content_type,
        "status": "PENDING", "deleted": False, "uploaded_at": now.isoformat()
    })
    url = s3.generate_presigned_url("put_object", Params={"Bucket": BUCKET, "Key": s3_key, "ContentType": content_type}, ExpiresIn=300)
    return {"statusCode": 200, "headers": cors(), "body": json.dumps({"presigned_url": url, "document_id": doc_id, "s3_key": s3_key})}

def mark_complete(user_id, body):
    doc_id = body.get("document_id", "")
    if not doc_id:
        return {"statusCode": 400, "headers": cors(), "body": json.dumps({"error": "document_id required"})}
    dynamodb.Table("DocumentMetadata").update_item(
        Key={"PK": f"DOC#{doc_id}"},
        UpdateExpression="SET #s = :s",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "UPLOADED_PROCESSING"}
    )
    return {"statusCode": 200, "headers": cors(), "body": json.dumps({"document_id": doc_id, "status": "UPLOADED_PROCESSING"})}

def get_status(user_id, doc_id):
    try:
        item = dynamodb.Table("DocumentMetadata").get_item(Key={"PK": f"DOC#{doc_id}"}).get("Item", {})
        return {"statusCode": 200, "headers": cors(), "body": json.dumps({"status": item.get("status", "UNKNOWN"), "document_id": doc_id})}
    except Exception as e:
        return {"statusCode": 500, "headers": cors(), "body": json.dumps({"error": str(e)})}

def cors():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Amz-Date,X-Api-Key",
        "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS"
    }
