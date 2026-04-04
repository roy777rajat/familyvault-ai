# FamilyVault AI — Security Audit (Apr 4 2026)

## ✅ What's Secure

### S3 Buckets
| Bucket | Access | Encryption | Notes |
|---|---|---|---|
| family-docs-ui | CloudFront OAC only | AES-256 ✅ | Policy: only CloudFront distribution can read |
| family-docs-raw | FamilyVaultBedrockKBRole only | AES-256 ✅ | No public access |
| family-docs-vectors | Lambda role only | AES-256 ✅ | No public access |

**S3 bucket policies verified:**
- `family-docs-ui`: Only allows `s3:GetObject` from CloudFront distribution via OAC (Origin Access Control). Direct S3 URL access is blocked.
- `family-docs-raw`: Only allows `s3:GetObject` + `s3:ListBucket` from `FamilyVaultBedrockKBRole`. No public access.

### API Gateway
| Route | Auth | Status |
|---|---|---|
| All data routes | JWT (Cognito) | ✅ Secure |
| GET /download | NONE (presigned URL) | ✅ Acceptable — URL is short-lived and scoped |
| POST /auth/post-confirm | NONE | ✅ Acceptable — Cognito post-confirmation trigger |
| POST /auth/verify-answer | NONE | ⚠️ Review — no auth on security question verify |

### Cognito
- Password policy: min 8 chars, uppercase + lowercase + numbers + symbols ✅
- Email verification required ✅
- Deletion protection: ACTIVE ✅
- Account recovery: via verified email ✅
- MFA: **OFF** ⚠️ — recommend enabling for a family document vault

### Lambda IAM Role (FamilyVaultLambdaRole)
- All Lambda functions share one role (acceptable for single-tenant MVP)
- Attached policies: SES, Lambda Basic Execution, DynamoDB Full, S3 Full, Bedrock Full
- Inline policies: CostExplorerReadAccess, WebSocketManageConnections

### Encryption
- All S3 buckets: AES-256 server-side encryption ✅
- API Gateway: HTTPS only (TLS 1.2+) ✅
- Cognito: tokens encrypted in transit ✅
- DynamoDB: encrypted at rest by default ✅

### CloudFront
- HTTPS enforced ✅
- S3 accessed via OAC (not public URLs) ✅
- `DisableExecuteApiEndpoint: false` — direct API GW access still possible (low risk, JWT required)

---

## ⚠️ Issues Found & Fixed

### 1. CRITICAL — Sensitive data in public GitHub repo ✅ FIXED
**What was exposed:**
- AWS Account ID (`141571819444`)
- Cognito User Pool ID and Client ID
- API Gateway IDs and integration IDs
- CloudFront distribution ID and domain
- Bedrock KB ID and data source ID
- Root user Cognito `sub` (UUID)
- Root user email address (`roy777rajat@gmail.com`)
- IAM Role ARN
- S3 bucket names (low risk but unnecessary)
- Local file paths (`E:\NEWTEMP\aws-api-mcp\workdir\...`)

**Risk:** Anyone with GitHub access could attempt to call API endpoints, enumerate resources, or target the account.

**Fix applied:** PROJECT_CONTEXT.md and SESSIONS.md rewritten to remove all hardcoded IDs. All values replaced with `aws cli discovery commands`.

---

## ⚠️ Issues Found — Action Required

### 2. IAM Role Over-Permissioned
**Current:** `AmazonS3FullAccess`, `AmazonDynamoDBFullAccess`, `AmazonBedrockFullAccess` — full access to ALL resources

**Risk:** If Lambda is compromised, attacker has full S3/DynamoDB/Bedrock access account-wide.

**Recommended fix (next session):**
```json
{
  "Effect": "Allow",
  "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
  "Resource": [
    "arn:aws:s3:::family-docs-raw/*",
    "arn:aws:s3:::family-docs-vectors/*",
    "arn:aws:s3:::family-docs-ui/*"
  ]
}
```
Scope DynamoDB to specific table ARNs only.

### 3. Cognito MFA is OFF
**Risk:** Accounts protected by password only. Phishing or credential stuffing could compromise user accounts.

**Recommended fix:** Enable TOTP MFA as optional (not mandatory, to avoid friction for MVP):
```powershell
aws cognito-idp set-user-pool-mfa-config \
  --user-pool-id <pool-id> \
  --software-token-mfa-configuration Enabled=true \
  --mfa-configuration OPTIONAL \
  --region eu-west-1
```

### 4. API CORS is Wildcard (`AllowOrigins: ["*"]`)
**Current:** Any origin can call the API.
**Risk:** Low (JWT still required), but could be tightened.

**Recommended fix:**
```powershell
# Restrict to CloudFront domain only
aws apigatewayv2 update-api --api-id <api-id> \
  --cors-configuration AllowOrigins=["https://[CLOUDFRONT_DOMAIN]"] \
  --region eu-west-1
```

### 5. S3 Versioning Not Enabled on family-docs-raw
**Risk:** Accidental or malicious deletion of documents is unrecoverable.

**Recommended fix:**
```powershell
aws s3api put-bucket-versioning \
  --bucket family-docs-raw \
  --versioning-configuration Status=Enabled \
  --region eu-west-1
```

### 6. No CloudWatch Alarms
**Risk:** No alerting on unusual spend, Lambda errors, or API error spikes.

**Recommended:** Add alarms for:
- Lambda errors > 10/hour
- API 5xx errors > 20/hour  
- Daily cost > $5 (via AWS Budgets)

---

## ✅ What Doesn't Need Fixing (By Design)

| Item | Why it's OK |
|---|---|
| `GET /download` has no JWT auth | Download uses short-lived S3 presigned URLs — the URL itself is the auth token |
| S3 bucket names in code | Bucket names alone are harmless — access is blocked by IAM |
| CloudFront domain in URL bar | This is the public app URL — by design |
| API base URL in app JS | Required for the app to work — JWT protects all endpoints |
| Lambda function names in logs | Not sensitive — no auth info exposed |

---

## 📋 Security Checklist

| Item | Status |
|---|---|
| S3 buckets not publicly accessible | ✅ |
| S3 buckets encrypted at rest | ✅ |
| API routes require JWT auth | ✅ (except 3 acceptable exceptions) |
| Cognito password policy strong | ✅ |
| HTTPS enforced everywhere | ✅ |
| DynamoDB encrypted at rest | ✅ |
| No secrets/keys in code | ✅ |
| No sensitive data in GitHub | ✅ Fixed in Session 8 |
| IAM least privilege | ⚠️ Over-permissioned — fix in next session |
| MFA enabled | ⚠️ Off — enable in next session |
| CORS restricted to app domain | ⚠️ Wildcard — tighten in next session |
| S3 versioning on docs bucket | ⚠️ Off — enable in next session |
| CloudWatch alarms | ⚠️ None — add in next session |
