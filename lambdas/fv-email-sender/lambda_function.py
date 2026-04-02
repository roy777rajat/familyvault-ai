"""
FamilyVault AI — Email Sender v4

Fix in v4: EmailSentLog now sets read=False on every new email so it
immediately appears in the Activity > Emails Sent screen.
"""
import json, boto3, os, uuid
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

ses      = boto3.client('ses', region_name='eu-west-1')
s3       = boto3.client('s3', region_name='eu-west-1')
bedrock  = boto3.client('bedrock-runtime', region_name='eu-west-1')
dynamodb = boto3.resource('dynamodb', region_name='eu-west-1')

BUCKET     = os.environ.get('BUCKET', 'family-docs-raw')
FROM_EMAIL = os.environ.get('FROM_EMAIL', 'roy777rajat@gmail.com')
API_URL    = os.environ.get('API_URL', 'https://1oj10740w0.execute-api.eu-west-1.amazonaws.com')
MODEL_ID   = 'eu.anthropic.claude-haiku-4-5-20251001-v1:0'


def cors_headers():
    return {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type,Authorization,X-Amz-Date,X-Api-Key',
        'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS',
    }

def ok(body):  return {'statusCode': 200, 'headers': cors_headers(), 'body': json.dumps(body)}
def err(c, m): print(f'ERROR {c}: {m}'); return {'statusCode': c, 'headers': cors_headers(), 'body': json.dumps({'error': m})}

def get_uid(event):
    jwt_claims = (event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {})
                  or event.get('requestContext', {}).get('authorizer', {}).get('claims', {}))
    uid = jwt_claims.get('sub', '')
    print(f'uid={uid!r}')
    return uid


def lambda_handler(event, context):
    method = event.get('requestContext', {}).get('http', {}).get('method', 'POST').upper()
    path   = event.get('rawPath', '')
    if method == 'OPTIONS':
        return {'statusCode': 200, 'headers': cors_headers(), 'body': ''}
    uid  = get_uid(event)
    body = json.loads(event.get('body', '{}') or '{}')
    print(f'method={method} path={path} uid={uid}')
    if '/email/draft' in path and method == 'POST':
        return generate_draft(body, uid)
    elif '/email/send' in path and method == 'POST':
        if not uid:
            return err(401, 'Unauthorised: missing user identity')
        return send_email(uid, body)
    return err(404, f'Unknown route: {method} {path}')


# ─── Generate AI draft ────────────────────────────────────────────────────────
def generate_draft(body, uid):
    rag_answer        = (body.get('rag_answer') or '').strip()
    doc_names         = body.get('doc_names', [])
    tone              = body.get('tone', 'Professional')
    recipient_context = (body.get('recipient_context') or '').strip()
    user_name         = (body.get('user_name') or 'FamilyVault User').strip()
    docs_line         = ', '.join(doc_names) if doc_names else 'selected documents'
    context_line      = f'\nRecipient context: {recipient_context}' if recipient_context else ''

    body_prompt = (
        f'Write a {tone} email that:\n'
        f'1. Shares information about: {rag_answer[:500] or "the attached documents"}\n'
        f'2. Mentions these attached documents: {docs_line}\n'
        f'3. Notes that document download links expire in 24 hours\n'
        f'{context_line}\n'
        f'4. Signs off as: {user_name}\n\n'
        f'Return ONLY the email body text, no subject line, under 200 words.'
    )
    subj_prompt = (
        f'Generate a concise email subject line (max 8 words) for an email about: '
        f'{rag_answer[:200] or docs_line}. Return ONLY the subject line text, nothing else.'
    )
    try:
        resp  = bedrock.invoke_model(modelId=MODEL_ID, body=json.dumps({
            'anthropic_version': 'bedrock-2023-05-31', 'max_tokens': 400,
            'messages': [{'role': 'user', 'content': body_prompt}]
        }))
        draft_body = json.loads(resp['body'].read())['content'][0]['text'].strip()
        resp2 = bedrock.invoke_model(modelId=MODEL_ID, body=json.dumps({
            'anthropic_version': 'bedrock-2023-05-31', 'max_tokens': 50,
            'messages': [{'role': 'user', 'content': subj_prompt}]
        }))
        subject_raw = json.loads(resp2['body'].read())['content'][0]['text'].strip().strip('"\'')
        return ok({'draft_subject': f'FamilyVault — {subject_raw}', 'draft_body': draft_body})
    except Exception as e:
        print(f'generate_draft error: {e}')
        return ok({
            'draft_subject': 'FamilyVault — Sharing Documents with You',
            'draft_body': f'Dear Recipient,\n\nPlease find the requested documents below.\nDownload links expire in 24 hours.\n\nBest regards,\n{user_name}'
        })


# ─── Token store ─────────────────────────────────────────────────────────────
def _store_download_token(uid, s3_key, filename, ttl_hours=24):
    token      = str(uuid.uuid4())
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat()
    try:
        dynamodb.Table('DownloadTokens').put_item(Item={
            'PK': f'TOKEN#{token}', 'token': token, 'uid': uid,
            's3_key': s3_key, 'filename': filename,
            'expires_at': expires_at,
            'created_at': datetime.now(timezone.utc).isoformat(),
        })
        print(f'Token stored: {token} → {filename}')
        return token
    except Exception as e:
        print(f'Token store error: {e}')
        return None


# ─── Send email ───────────────────────────────────────────────────────────────
def send_email(uid, body):
    to_list    = body.get('to', [])
    cc_list    = body.get('cc', []) or []
    subject    = (body.get('subject') or 'FamilyVault Documents').strip()
    email_body = (body.get('body') or '').strip()
    doc_ids    = body.get('doc_ids', []) or []

    if not to_list:    return err(400, 'At least one recipient (to) is required')
    if not email_body: return err(400, 'Email body is required')

    # Build token-based links
    doc_links = []
    table = dynamodb.Table('DocumentMetadata')
    for doc_id in doc_ids:
        try:
            result = table.get_item(Key={'PK': f'DOC#{doc_id}'})
            item   = result.get('Item', {})
            if not item: continue
            if item.get('user_id') and item.get('user_id') != uid: continue
            if item.get('deleted'): continue
            s3_key = item.get('s3_key', '')
            fname  = item.get('filename', doc_id)
            if not s3_key: continue
            token = _store_download_token(uid, s3_key, fname)
            if token:
                doc_links.append({'name': fname, 'url': f'{API_URL}/download?token={token}'})
        except Exception as e:
            print(f'Doc fetch error doc_id={doc_id}: {e}')

    print(f'Sending to={to_list} docs={len(doc_links)}')

    body_html = email_body.replace('\n', '<br>')
    links_section = ''
    if doc_links:
        link_items = ''.join(
            f'<li style="margin-bottom:10px">'
            f'<a href="{d["url"]}" '
            f'style="display:inline-block;padding:9px 18px;background:#14b8a6;color:#fff;'
            f'font-weight:700;text-decoration:none;border-radius:6px;font-size:13px">'
            f'\u2b07 Download {d["name"]}'
            f'</a>'
            f'<span style="font-size:11px;color:#6b7280;display:block;margin-top:4px">'
            f'Secure · expires 24 hours</span></li>'
            for d in doc_links
        )
        links_section = (
            '<div style="margin-top:24px;padding:20px;background:#f0fdf9;border-radius:8px;border:1px solid #99f6e4">'
            '<h3 style="margin:0 0 14px;color:#0f766e;font-size:15px">📎 Document Downloads</h3>'
            f'<ul style="margin:0;padding:0;list-style:none">{link_items}</ul>'
            '<p style="margin:14px 0 0;font-size:11px;color:#6b7280">'
            'Click each button to download. Links expire in 24 hours.</p></div>'
        )

    html_body = (
        '<html><body style="font-family:Arial,sans-serif;max-width:620px;margin:0 auto;padding:20px;background:#f9fafb">'
        '<div style="background:#fff;border-radius:12px;padding:28px;border:1px solid #e5e7eb">'
        '<div style="border-bottom:2px solid #14b8a6;padding-bottom:14px;margin-bottom:20px">'
        '<span style="font-size:20px;font-weight:800;color:#0f766e">🗂 FamilyVault AI</span></div>'
        f'<div style="color:#374151;line-height:1.7;font-size:14px">{body_html}</div>'
        f'{links_section}'
        '<hr style="margin:24px 0;border:none;border-top:1px solid #f3f4f6">'
        '<p style="font-size:11px;color:#9ca3af;margin:0">'
        'Sent via FamilyVault AI · Powered by Amazon Bedrock & AWS SES · eu-west-1</p>'
        '</div></body></html>'
    )

    plain_body = email_body
    if doc_links:
        plain_body += '\n\nDocument Download Links:\n'
        for d in doc_links:
            plain_body += f"- {d['name']}: {d['url']}\n"
        plain_body += '\n(Links expire in 24 hours)'

    try:
        response   = ses.send_email(
            Source=FROM_EMAIL,
            Destination={'ToAddresses': to_list, 'CcAddresses': [cc for cc in cc_list if cc]},
            Message={
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {
                    'Text': {'Data': plain_body, 'Charset': 'UTF-8'},
                    'Html': {'Data': html_body,  'Charset': 'UTF-8'},
                }
            }
        )
        message_id = response.get('MessageId', '')
        print(f'SES sent message_id={message_id}')
    except Exception as e:
        print(f'SES send error: {e}')
        err_msg = str(e)
        if 'not verified' in err_msg: return err(400, f'SES: email not verified. {err_msg}')
        if 'MessageRejected' in err_msg: return err(400, f'SES rejected message: {err_msg}')
        return err(500, f'Email send failed: {err_msg}')

    # ── Log to EmailSentLog — read=False so it appears in Activity immediately ──
    try:
        now = datetime.now(timezone.utc)
        dynamodb.Table('EmailSentLog').put_item(Item={
            'PK': f'USER#{uid}', 'SK': f'EMAIL#{now.isoformat()}',
            'message_id': message_id, 'to': to_list, 'cc': cc_list,
            'subject': subject, 'doc_ids': doc_ids,
            'doc_count': len(doc_links), 'sent_at': now.isoformat(),
            'read': False,   # ← v4 fix: always set so Activity tab shows it
        })
    except Exception as e:
        print(f'EmailSentLog write error (non-fatal): {e}')

    return ok({'sent': True, 'message_id': message_id, 'doc_links_generated': len(doc_links)})
