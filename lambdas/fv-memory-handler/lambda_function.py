import json, boto3, uuid, decimal
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Attr

dynamodb = boto3.resource('dynamodb', region_name='eu-west-1')
TABLE    = 'ChatSessions'


def cors():
    return {'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
            'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS'}

def fix(o):
    if isinstance(o, decimal.Decimal): return int(o) if o % 1 == 0 else float(o)
    if isinstance(o, dict):  return {k: fix(v) for k, v in o.items()}
    if isinstance(o, list):  return [fix(i) for i in o]
    return o

def ok(body):  return {'statusCode': 200, 'headers': cors(), 'body': json.dumps(fix(body))}
def err(c, m): return {'statusCode': c,   'headers': cors(), 'body': json.dumps({'error': m})}

def get_uid(event):
    return event.get('requestContext',{}).get('authorizer',{}).get('jwt',{}).get('claims',{}).get('sub','unknown')


def lambda_handler(event, context):
    method = event.get('requestContext',{}).get('http',{}).get('method','GET').upper()
    path   = event.get('rawPath', event.get('path', ''))
    uid    = get_uid(event)
    table  = dynamodb.Table(TABLE)

    if method == 'OPTIONS': return {'statusCode': 200, 'headers': cors(), 'body': ''}

    # GET /memory/sessions
    if method == 'GET' and path.endswith('/sessions'):
        try:
            result = table.scan(FilterExpression=Attr('PK').eq('USER#'+uid) & Attr('deleted').ne(True))
            items  = result.get('Items', [])
            sessions = {}
            for item in items:
                sid = item.get('session_id', '')
                if not sid: continue
                if sid not in sessions:
                    sessions[sid] = {'session_id': sid, 'created_at': item.get('created_at',''), 'turns': []}
                sessions[sid]['turns'].append({
                    'question': item.get('question',''), 'answer': (item.get('answer','') or '')[:300],
                    'sources': item.get('sources',[])
                })
            sorted_sessions = sorted(sessions.values(), key=lambda s: s.get('created_at',''), reverse=True)
            return ok({'sessions': sorted_sessions})
        except Exception as e:
            print(f"sessions error: {e}"); return err(500, str(e))

    # DELETE /memory/sessions/{id}
    if method == 'DELETE' and '/sessions/' in path:
        sid = path.rstrip('/').split('/')[-1]
        try:
            result = table.scan(FilterExpression=Attr('PK').eq('USER#'+uid) & Attr('session_id').eq(sid))
            for item in result.get('Items', []):
                table.delete_item(Key={'PK': item['PK'], 'SK': item['SK']})
            return ok({'deleted': True})
        except Exception as e: return err(500, str(e))

    # DELETE /memory/all
    if method == 'DELETE' and path.endswith('/all'):
        try:
            result = table.scan(FilterExpression=Attr('PK').eq('USER#'+uid))
            for item in result.get('Items', []):
                table.delete_item(Key={'PK': item['PK'], 'SK': item['SK']})
            return ok({'deleted': True})
        except Exception as e: return err(500, str(e))

    # GET /memory/long-term
    if method == 'GET' and 'long-term' in path: return ok({'memories': []})

    # DELETE /memory/long-term or /memory/turns
    if method == 'DELETE' and ('long-term' in path or 'turns' in path): return ok({'deleted': True})

    # POST /memory/turns
    if method == 'POST' and 'turns' in path:
        try:
            body = json.loads(event.get('body', '{}') or '{}')
            sid  = body.get('session_id', str(uuid.uuid4()))
            table.put_item(Item={
                'PK': 'USER#'+uid, 'SK': 'SESSION#'+sid+'#TURN#'+str(uuid.uuid4()),
                'session_id': sid, 'question': body.get('question',''), 'answer': body.get('answer',''),
                'sources': body.get('sources',[]), 'created_at': datetime.now(timezone.utc).isoformat(), 'deleted': False
            })
            return ok({'saved': True})
        except Exception as e: return err(500, str(e))

    return err(404, f'Not found: {method} {path}')
