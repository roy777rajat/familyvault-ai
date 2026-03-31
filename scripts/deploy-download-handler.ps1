<#
.SYNOPSIS
  FamilyVault AI — Deploy fv-download-handler Lambda (Session 4 pending item)

.DESCRIPTION
  Performs all 4 steps needed to wire secure email download links:
    Step 1: Create DownloadTokens DynamoDB table
    Step 2: Zip + upload + create fv-download-handler Lambda
    Step 3: Create GET /download route in API Gateway (no auth — token IS the credential)
    Step 4: Verify fv-email-sender v3 has API_URL env var

.NOTES
  Prerequisites:
    - AWS CLI configured with credentials for account 141571819444
    - PowerShell 5.1+ or PowerShell Core
    - Run from repo root: .\scripts\deploy-download-handler.ps1

  AWS context:
    Region      : eu-west-1
    Account     : 141571819444
    Lambda role : arn:aws:iam::141571819444:role/FamilyVaultLambdaRole
    HTTP API ID : 1oj10740w0
    S3 bucket   : family-docs-raw
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$REGION      = 'eu-west-1'
$ACCOUNT     = '141571819444'
$ROLE_ARN    = "arn:aws:iam::${ACCOUNT}:role/FamilyVaultLambdaRole"
$API_ID      = '1oj10740w0'
$BUCKET      = 'family-docs-raw'
$API_URL     = "https://${API_ID}.execute-api.${REGION}.amazonaws.com"
$FUNC        = 'fv-download-handler'
$DDB_TABLE   = 'DownloadTokens'
$ZIP_NAME    = 'fv-download-handler.zip'
$SRC         = 'lambdas\fv-download-handler\lambda_function.py'

function Write-Step($n, $msg) { Write-Host "`n=== Step $n: $msg ===" -ForegroundColor Cyan }
function Write-Ok($msg)       { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Skip($msg)     { Write-Host "  [SKIP] $msg" -ForegroundColor Yellow }
function Write-Fail($msg)     { Write-Host "  [FAIL] $msg" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------------------
# Step 1 — Create DownloadTokens DynamoDB table
# ---------------------------------------------------------------------------
Write-Step 1 "Create DownloadTokens DynamoDB table"

$tableExists = $false
try {
    aws dynamodb describe-table --table-name $DDB_TABLE --region $REGION 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $tableExists = $true }
} catch {}

if ($tableExists) {
    Write-Skip "Table $DDB_TABLE already exists — skipping create"
} else {
    aws dynamodb create-table `
      --table-name $DDB_TABLE `
      --attribute-definitions AttributeName=PK,AttributeType=S `
      --key-schema AttributeName=PK,KeyType=HASH `
      --billing-mode PAY_PER_REQUEST `
      --region $REGION | Out-Null

    if ($LASTEXITCODE -ne 0) { Write-Fail "DDB create-table failed" }

    Write-Host "  Waiting for table to become ACTIVE ..."
    aws dynamodb wait table-exists --table-name $DDB_TABLE --region $REGION

    # Enable TTL on expires_epoch (auto-cleanup expired tokens — free)
    aws dynamodb update-time-to-live `
      --table-name $DDB_TABLE `
      --time-to-live-specification "Enabled=true,AttributeName=expires_epoch" `
      --region $REGION | Out-Null

    Write-Ok "Table $DDB_TABLE created with TTL on expires_epoch"
}

# ---------------------------------------------------------------------------
# Step 2 — Build zip, upload to S3, create/update Lambda
# ---------------------------------------------------------------------------
Write-Step 2 "Build + deploy $FUNC Lambda"

if (-not (Test-Path $SRC)) {
    Write-Fail "Source not found: $SRC  (run script from repo root)"
}

# Build zip using PowerShell-native Compress-Archive (no Python needed)
if (Test-Path $ZIP_NAME) { Remove-Item $ZIP_NAME }
Compress-Archive -Path $SRC -DestinationPath $ZIP_NAME
Write-Ok "Built $ZIP_NAME"

# Upload to S3
aws s3 cp $ZIP_NAME "s3://${BUCKET}/lambda-packages/${ZIP_NAME}" --region $REGION
if ($LASTEXITCODE -ne 0) { Write-Fail "S3 upload failed" }
Write-Ok "Uploaded to s3://${BUCKET}/lambda-packages/${ZIP_NAME}"

# Check if Lambda already exists
$funcExists = $false
try {
    aws lambda get-function-configuration --function-name $FUNC --region $REGION 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $funcExists = $true }
} catch {}

$ENV_VARS = "Variables={BUCKET=${BUCKET},API_URL=${API_URL}}"

if ($funcExists) {
    Write-Host "  Lambda $FUNC exists — updating code + config ..."
    aws lambda update-function-code `
      --function-name $FUNC `
      --s3-bucket $BUCKET `
      --s3-key "lambda-packages/${ZIP_NAME}" `
      --region $REGION | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Fail "update-function-code failed" }

    aws lambda wait function-updated --function-name $FUNC --region $REGION

    aws lambda update-function-configuration `
      --function-name $FUNC `
      --timeout 30 --memory-size 256 `
      --environment $ENV_VARS `
      --region $REGION | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Fail "update-function-configuration failed" }
    Write-Ok "Lambda $FUNC updated"
} else {
    aws lambda create-function `
      --function-name $FUNC `
      --runtime python3.11 `
      --role $ROLE_ARN `
      --handler lambda_function.lambda_handler `
      --code "S3Bucket=${BUCKET},S3Key=lambda-packages/${ZIP_NAME}" `
      --timeout 30 --memory-size 256 `
      --environment $ENV_VARS `
      --region $REGION | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Fail "create-function failed" }
    Write-Ok "Lambda $FUNC created"
}

# Add invoke permission for API Gateway (idempotent — ignore AlreadyExists error)
Write-Host "  Adding API Gateway invoke permission ..."
$SOURCE_ARN = "arn:aws:execute-api:${REGION}:${ACCOUNT}:${API_ID}/*"
try {
    aws lambda add-permission `
      --function-name $FUNC `
      --statement-id apigw-invoke `
      --action lambda:InvokeFunction `
      --principal apigateway.amazonaws.com `
      --source-arn $SOURCE_ARN `
      --region $REGION 2>&1 | Out-Null
} catch {}
Write-Ok "Invoke permission ensured"

# ---------------------------------------------------------------------------
# Step 3 — Wire GET /download route in API Gateway (no auth — token IS the credential)
# ---------------------------------------------------------------------------
Write-Step 3 "Wire GET /download route in HTTP API $API_ID"

$routes   = aws apigatewayv2 get-routes --api-id $API_ID --region $REGION | ConvertFrom-Json
$existing = $routes.Items | Where-Object { $_.RouteKey -eq 'GET /download' }

if ($existing) {
    Write-Skip "Route 'GET /download' already exists (RouteId: $($existing.RouteId))"
} else {
    $LAMBDA_ARN       = (aws lambda get-function-configuration `
      --function-name $FUNC --region $REGION | ConvertFrom-Json).FunctionArn
    $INTEGRATION_URI  = "arn:aws:apigateway:${REGION}:lambda:path/2015-03-31/functions/${LAMBDA_ARN}/invocations"

    $integ = aws apigatewayv2 create-integration `
      --api-id $API_ID `
      --integration-type AWS_PROXY `
      --integration-uri $INTEGRATION_URI `
      --payload-format-version '2.0' `
      --region $REGION | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { Write-Fail "create-integration failed" }
    $INTEGRATION_ID = $integ.IntegrationId
    Write-Ok "Integration created: $INTEGRATION_ID"

    # GET /download — NO authorization (the token uuid IS the credential)
    aws apigatewayv2 create-route `
      --api-id $API_ID `
      --route-key 'GET /download' `
      --target "integrations/${INTEGRATION_ID}" `
      --region $REGION | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Fail "create-route GET failed" }
    Write-Ok "Route 'GET /download' → integration $INTEGRATION_ID (no auth)"

    # OPTIONS /download for browser CORS preflight
    try {
        aws apigatewayv2 create-route `
          --api-id $API_ID `
          --route-key 'OPTIONS /download' `
          --target "integrations/${INTEGRATION_ID}" `
          --region $REGION | Out-Null
        Write-Ok "Route 'OPTIONS /download' created"
    } catch {
        Write-Skip "OPTIONS /download — may already exist, skipping"
    }
}

# ---------------------------------------------------------------------------
# Step 4 — Verify fv-email-sender v3 has API_URL env var
# ---------------------------------------------------------------------------
Write-Step 4 "Verify fv-email-sender environment"

$emailCfg  = aws lambda get-function-configuration `
  --function-name fv-email-sender --region $REGION | ConvertFrom-Json
$envVars   = $emailCfg.Environment.Variables
$hasApiUrl = $envVars.PSObject.Properties.Name -contains 'API_URL'

if ($hasApiUrl) {
    Write-Ok "fv-email-sender has API_URL = $($envVars.API_URL)"
} else {
    Write-Host "  fv-email-sender missing API_URL — patching ..."
    aws lambda wait function-updated --function-name fv-email-sender --region $REGION

    # Build merged var string: existing vars + API_URL
    $pairs = $envVars.PSObject.Properties | ForEach-Object { "$($_.Name)=$($_.Value)" }
    $pairs += "API_URL=$API_URL"
    $varStr = $pairs -join ','

    aws lambda update-function-configuration `
      --function-name fv-email-sender `
      --environment "Variables={$varStr}" `
      --region $REGION | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Fail "Failed to patch fv-email-sender" }
    Write-Ok "Patched fv-email-sender with API_URL=$API_URL"
}

# ---------------------------------------------------------------------------
# Smoke test — hit /download with no token, expect 400
# ---------------------------------------------------------------------------
Write-Host "`n=== Smoke Test ===" -ForegroundColor Cyan
Write-Host "  Hitting GET ${API_URL}/download (no token) ..."
try {
    $resp = Invoke-WebRequest -Uri "${API_URL}/download" -Method GET -ErrorAction SilentlyContinue
    Write-Host "  HTTP $($resp.StatusCode)"
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code -eq 400) {
        Write-Ok "Smoke test PASSED — Lambda returned 400 for missing token"
    } else {
        Write-Host "  HTTP $code (expected 400 — check Lambda logs)" -ForegroundColor Yellow
    }
}

# ---------------------------------------------------------------------------
# Done — print verification commands
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== DEPLOYMENT COMPLETE ===" -ForegroundColor Green
Write-Host ""
Write-Host "Verification commands:"
Write-Host ""
Write-Host "  1. DDB table status:"
Write-Host "     aws dynamodb describe-table --table-name DownloadTokens --region eu-west-1 --query Table.TableStatus"
Write-Host ""
Write-Host "  2. Lambda config:"
Write-Host "     aws lambda get-function-configuration --function-name fv-download-handler --region eu-west-1 --query '[State, Environment.Variables]'"
Write-Host ""
Write-Host "  3. API route:"
Write-Host "     aws apigatewayv2 get-routes --api-id 1oj10740w0 --region eu-west-1 --query 'Items[?RouteKey==``GET /download``]'"
Write-Host ""
Write-Host "  4. End-to-end test:"
Write-Host "     Open https://d38ys5d9amc45p.cloudfront.net/app/index.html"
Write-Host "     Send yourself a document by email → click the link → file should download"
Write-Host ""
Write-Host "  5. Direct token test:"
Write-Host "     aws dynamodb scan --table-name DownloadTokens --region eu-west-1 --limit 1"
Write-Host "     # Grab a token PK value, strip 'TOKEN#' prefix, then:"
Write-Host "     curl -v 'https://1oj10740w0.execute-api.eu-west-1.amazonaws.com/download?token=<UUID>'"
Write-Host "     # Expect: HTTP 302 Location: https://family-docs-raw.s3... (presigned URL)"

Remove-Item $ZIP_NAME -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "Done. fv-download-handler is live." -ForegroundColor Green
