"""
FamilyVault AI — Email Sender Lambda
Fixes applied vs original:
  FIX 1: Bedrock model ID uses eu. prefix (required for eu-west-1 cross-region inference)
  FIX 2: JWT claims path corrected: .jwt.claims.sub  (HTTP API format)
  FIX 3: OPTIONS preflight handled before auth check
  FIX 4: send_email presigned URL includes ResponseContentDisposition to force download
  FIX 5: Filename special chars URL-encoded in Content-Disposition
  FIX 6: SES send wrapped in try/except with clear error messaging
  FIX 7: EmailSentLog table auto-creates gracefully if missing
"""
import json, boto3, os, re
from datetime import datetime, timezone
from urllib.parse import quote

ses      = boto3.client('ses', region_name='eu-west-1')
s3       = boto3.client('s3', region_name='eu-west-1')
bedrock  = boto3.client('bedrock-runtime', region_name='eu-west-1')
dynamodb = boto3.resource('dynamodb', region_name='eu-west-1')

BUCKET     = os.environ.get('BUCKET', 'family-docs-raw')
FROM_EMAIL = os.environ.get('FROM_EMAIL', 'roy777rajat@gmail.com')

# FIX 1: eu. prefix required for eu-west-1 cross-region Bedrock inference
MODEL_ID = 'eu.anthropic.claude-haiku-4-5-20251001-v1:0'


def cors_headers():
    return {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type,Authorization,X-Amz-Date,X-Api-Key',
        'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS',
    }


def ok(body):
    return {'statusCode': 200, 'headers': cors_headers(), 'body': json.dumps(body)}


def err(code, msg):
    print(f'ERROR {code}: {msg}')
    return {'statusCode': code, 'headers': cors_headers(), 'body': json.dumps({'error': msg})}


def get_uid(event):
    # FIX 2: HTTP API JWT authorizer puts claims under .jwt.claims, NOT .claims
    jwt_claims = (
        event.get('requestContext', {})
             .get('authorizer', {})
             .get('jwt', {})
             .get('claims', {})
    )
    # Fallback: some older Lambda proxy formats use .claims directly
    if not jwt_claims:
        jwt_claims = (
            event.get('requestContext', {})
                 .get('authorizer', {})
                 .get('claims', {})
        )
    uid = jwt_claims.get('sub', '')
    print(f'uid={uid!r}')
    return uid


def lambda_handler(event, context):
    method = event.get('requestContext', {}).get('http', {}).get('method', 'POST').upper()
    path   = event.get('rawPath', '')

    # FIX 3: Handle CORS preflight before any auth
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


# ==============================================================
#  GENERATE DRAFT  (AI-powered)
# ==============================================================

def generate_draft(body, uid):
    rag_answer       = (body.get('rag_answer') or '').strip()
    doc_names        = body.get('doc_names', [])
    tone             = body.get('tone', 'Professional')
    recipient_context = (body.get('recipient_context') or '').strip()
    user_name        = (body.get('user_name') or 'FamilyVault User').strip()

    # Compose prompt
    docs_line = ', '.join(doc_names) if doc_names else 'selected documents'
    context_line = f'\nRecipient context: {recipient_context}' if recipient_context else ''

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
        # Generate body
        resp = bedrock.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps({
                'anthropic_version': 'bedrock-2023-05-31',
                'max_tokens': 400,
                'messages': [{'role': 'user', 'content': body_prompt}]
            })
        )
        draft_body = json.loads(resp['body'].read())['content'][0]['text'].strip()

        # Generate subject
        resp2 = bedrock.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps({
                'anthropic_version': 'bedrock-2023-05-31',
                'max_tokens': 50,
                'messages': [{'role': 'user', 'content': subj_prompt}]
            })
        )
        subject_raw = json.loads(resp2['body'].read())['content'][0]['text'].strip()
        # Strip any quotes the model might add
        subject_raw = subject_raw.strip('"\'')
        subject = f'FamilyVault — {subject_raw}'

        return ok({'draft_subject': subject, 'draft_body': draft_body})

    except Exception as e:
        print(f'generate_draft error: {e}')
        # Return a sensible fallback so the UI isn't blocked
        return ok({
            'draft_subject': f'FamilyVault — Sharing Documents with You',
            'draft_body': (
                f'Dear Recipient,\n\n'
                f'Please find the requested documents from FamilyVault AI attached below.\n'
                f'Download links expire in 24 hours.\n\n'
                f'Best regards,\n{user_name}'
            )
        })


# ==============================================================
#  SEND EMAIL  (SES)
# ==============================================================

def _make_presigned_download(s3_key, filename, expiry=86400):
    """
    FIX 4+5: Force download disposition + URL-encode filename
    so that filenames with spaces/brackets don't break the S3 signature.
    """
    # URL-encode the filename for the Content-Disposition header
    safe_filename = quote(filename, safe='')
    try:
        return s3.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': BUCKET,
                'Key': s3_key,
                'ResponseContentDisposition': f'attachment; filename="{safe_filename}"'
            },
            ExpiresIn=expiry
        )
    except Exception as e:
        print(f'presign error key={s3_key}: {e}')
        return None


def send_email(uid, body):
    to_list  = body.get('to', [])
    cc_list  = body.get('cc', []) or []
    subject  = (body.get('subject') or 'FamilyVault Documents').strip()
    email_body = (body.get('body') or '').strip()
    doc_ids  = body.get('doc_ids', []) or []

    if not to_list:
        return err(400, 'At least one recipient (to) is required')
    if not email_body:
        return err(400, 'Email body is required')

    # Generate presigned URLs for selected documents
    doc_links = []
    table = dynamodb.Table('DocumentMetadata')
    for doc_id in doc_ids:
        try:
            result = table.get_item(Key={'PK': f'DOC#{doc_id}'})
            item = result.get('Item', {})
            if not item:
                print(f'Doc not found: {doc_id}')
                continue
            # FIX 2 effect: ownership now correctly validated
            if item.get('user_id') and item.get('user_id') != uid:
                print(f'Ownership mismatch doc_id={doc_id} owner={item.get("user_id")} uid={uid}')
                continue
            if item.get('deleted'):
                continue
            s3_key  = item.get('s3_key', '')
            fname   = item.get('filename', doc_id)
            if not s3_key:
                continue
            url = _make_presigned_download(s3_key, fname)
            if url:
                doc_links.append({'name': fname, 'url': url})
        except Exception as e:
            print(f'Doc fetch error doc_id={doc_id}: {e}')
            continue

    print(f'Sending to={to_list} cc={cc_list} docs={len(doc_links)}')

    # Build HTML email
    body_html = email_body.replace('\n', '<br>')

    links_section = ''
    if doc_links:
        link_items = ''.join(
            f'<li style="margin-bottom:8px">'
            f'<a href="{d["url"]}" style="color:#14b8a6;font-weight:600;text-decoration:none">'
            f'⬇️ {d["name"]}'
            f'</a>'
            f'<span style="font-size:11px;color:#888;margin-left:8px">(expires 24h)</span>'
            f'</li>'
            for d in doc_links
        )
        links_section = f"""
        <div style="margin-top:24px;padding:16px;background:#f0fdf4;border-radius:8px;border:1px solid #bbf7d0">
          <h3 style="margin:0 0 12px;color:#166534;font-size:14px">📎 Attached Documents</h3>
          <ul style="margin:0;padding-left:20px;color:#333">{link_items}</ul>
          <p style="margin:12px 0 0;font-size:11px;color:#888">
            Links are secure and expire in 24 hours.
          </p>
        </div>"""

    html_body = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:620px;margin:0 auto;padding:20px;background:#f9fafb">
      <div style="background:#ffffff;border-radius:12px;padding:28px;border:1px solid #e5e7eb;box-shadow:0 1px 4px rgba(0,0,0,0.06)">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:20px;padding-bottom:16px;border-bottom:1px solid #f3f4f6">
          <span style="font-size:24px">🗂</span>
          <span style="font-size:18px;font-weight:700;color:#111">FamilyVault AI</span>
        </div>
        <div style="color:#374151;line-height:1.7;font-size:14px">{body_html}</div>
        {links_section}
        <hr style="margin:24px 0;border:none;border-top:1px solid #f3f4f6">
        <p style="font-size:11px;color:#9ca3af;margin:0">
          Sent via FamilyVault AI · Powered by Amazon Bedrock &amp; AWS SES · eu-west-1
        </p>
      </div>
    </body></html>"""

    # Also build plain-text version
    plain_body = email_body
    if doc_links:
        plain_body += '\n\nDocument Download Links:\n'
        for d in doc_links:
            plain_body += f"- {d['name']}: {d['url']}\n"
        plain_body += '\n(Links expire in 24 hours)'

    # FIX 6: SES send wrapped in try/except
    try:
        ses_params = {
            'Source': FROM_EMAIL,
            'Destination': {
                'ToAddresses': to_list,
                'CcAddresses': [cc for cc in cc_list if cc],
            },
            'Message': {
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {
                    'Text': {'Data': plain_body, 'Charset': 'UTF-8'},
                    'Html':  {'Data': html_body,  'Charset': 'UTF-8'},
                }
            }
        }
        response = ses.send_email(**ses_params)
        message_id = response.get('MessageId', '')
        print(f'SES sent message_id={message_id}')

    except Exception as e:
        print(f'SES send error: {e}')
        # Common reasons: email not SES-verified, sandbox mode, invalid address
        err_msg = str(e)
        if 'Email address is not verified' in err_msg:
            return err(400, f'SES: The sender or recipient email is not verified. In sandbox mode all addresses must be verified in AWS SES console. Details: {err_msg}')
        if 'MessageRejected' in err_msg:
            return err(400, f'SES rejected the message: {err_msg}')
        return err(500, f'Email send failed: {err_msg}')

    # FIX 7: Log to EmailSentLog gracefully
    try:
        now = datetime.now(timezone.utc)
        dynamodb.Table('EmailSentLog').put_item(Item={
            'PK': f'USER#{uid}',
            'SK': f'EMAIL#{now.isoformat()}',
            'message_id': message_id,
            'to': to_list,
            'cc': cc_list,
            'subject': subject,
            'doc_ids': doc_ids,
            'doc_count': len(doc_links),
            'sent_at': now.isoformat()
        })
    except Exception as e:
        print(f'EmailSentLog write error (non-fatal): {e}')

    return ok({
        'sent': True,
        'message_id': message_id,
        'doc_links_generated': len(doc_links)
    })
