"""
FamilyVault AI — Download Handler v2
Fix: DDB lookup now uses Key={'token': token} to match the actual table schema.
The table partition key is 'token', not 'PK'.
"""
import json, boto3, os
from datetime import datetime, timezone
from urllib.parse import quote

dynamodb = boto3.resource('dynamodb', region_name='eu-west-1')
s3       = boto3.client('s3', region_name='eu-west-1')

BUCKET = os.environ.get('BUCKET', 'family-docs-raw')


def lambda_handler(event, context):
    method = event.get('requestContext', {}).get('http', {}).get('method', 'GET').upper()
    params = event.get('queryStringParameters') or {}
    token  = params.get('token', '').strip()

    if method == 'OPTIONS':
        return {'statusCode': 200, 'headers': {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET,OPTIONS'
        }, 'body': ''}

    if method != 'GET':
        return html_error(405, 'Method Not Allowed')

    if not token:
        return html_error(400, 'Missing download token. Please use the link from your FamilyVault email.')

    # Look up token in DynamoDB
    # Table partition key is 'token' (plain string, no prefix)
    try:
        table  = dynamodb.Table('DownloadTokens')
        result = table.get_item(Key={'token': token})
        item   = result.get('Item')
    except Exception as e:
        print('DDB lookup error: ' + str(e))
        return html_error(500, 'Failed to validate token. Please try again.')

    if not item:
        return html_error(404, 'Download link not found. It may have expired or already been used.')

    # Check expiry
    expires_at = item.get('expires_at', '')
    try:
        exp_dt = datetime.fromisoformat(expires_at)
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > exp_dt:
            return html_error(410, 'This download link has expired (24 hour limit). Please request a new link from FamilyVault AI.')
    except Exception as e:
        print('Expiry check error: ' + str(e))

    s3_key   = item.get('s3_key', '')
    filename = item.get('filename', 'document')
    uid      = item.get('uid', '')

    if not s3_key:
        return html_error(400, 'Invalid token data.')

    # Generate fresh presigned URL — short 2-minute window
    try:
        safe_fname = quote(filename, safe='')
        presigned  = s3.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': BUCKET,
                'Key':    s3_key,
                'ResponseContentDisposition': 'attachment; filename="' + safe_fname + '"'
            },
            ExpiresIn=120
        )
    except Exception as e:
        print('Presign error s3_key=' + s3_key + ': ' + str(e))
        return html_error(500, 'Failed to generate download link: ' + str(e))

    print('Download redirect: token=' + token[:8] + '... file=' + filename + ' uid=' + uid)

    return {
        'statusCode': 302,
        'headers': {
            'Location':      presigned,
            'Cache-Control': 'no-store, no-cache, must-revalidate',
            'Pragma':        'no-cache',
        },
        'body': ''
    }


def html_error(code, message):
    icon = '\u23f0' if code == 410 else '\U0001f517' if code == 404 else '\u26a0\ufe0f'
    title = 'Link Expired' if code == 410 else 'Link Not Found' if code == 404 else 'Download Error'
    html = ('<!DOCTYPE html>\n<html lang="en">\n<head>\n'
            '  <meta charset="UTF-8">\n'
            '  <meta name="viewport" content="width=device-width,initial-scale=1">\n'
            '  <title>FamilyVault \u2014 ' + title + '</title>\n'
            '  <style>\n'
            '    body{font-family:Arial,sans-serif;display:flex;align-items:center;\n'
            '         justify-content:center;min-height:100vh;margin:0;background:#f9fafb;}\n'
            '    .card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:40px 36px;\n'
            '          max-width:440px;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,.06);}\n'
            '    .icon{font-size:48px;margin-bottom:14px;}\n'
            '    h2{color:#111;font-size:20px;margin:0 0 10px;}\n'
            '    p{color:#6b7280;font-size:14px;line-height:1.6;margin:0;}\n'
            '    .code{font-size:11px;color:#9ca3af;margin-top:18px;}\n'
            '  </style>\n</head>\n<body>\n'
            '  <div class="card">\n'
            '    <div class="icon">' + icon + '</div>\n'
            '    <h2>' + title + '</h2>\n'
            '    <p>' + message + '</p>\n'
            '    <p class="code">Error ' + str(code) + ' \u00b7 FamilyVault AI \u00b7 eu-west-1</p>\n'
            '  </div>\n</body>\n</html>')
    return {'statusCode': code, 'headers': {'Content-Type': 'text/html; charset=utf-8'}, 'body': html}
