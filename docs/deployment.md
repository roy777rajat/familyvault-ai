# FamilyVault AI — Deployment Runbook

## Deploy a Lambda Function
```powershell
# 1. Upload zip to S3
aws s3 cp fv-chat-v12.zip s3://family-docs-raw/lambda-packages/fv-chat-v12.zip --region eu-west-1

# 2. Update Lambda code
aws lambda update-function-code `
  --function-name fv-chat-handler `
  --s3-bucket family-docs-raw `
  --s3-key lambda-packages/fv-chat-v12.zip `
  --region eu-west-1

# 3. Verify deployment
aws lambda get-function-configuration `
  --function-name fv-chat-handler `
  --region eu-west-1 `
  --query "[CodeSize,LastModified]"
```

## Deploy the UI
```powershell
# Upload
aws s3 cp index.html `
  s3://family-docs-ui/app/index.html `
  --content-type text/html `
  --region eu-west-1

# Bust CloudFront cache
aws cloudfront create-invalidation `
  --distribution-id E6U4KTUCXF1Q3 `
  --paths "/app/*" `
  --region us-east-1
```

## Add Lambda Invoke Permission
```bash
aws lambda add-permission \
  --function-name fv-<name> \
  --statement-id apigw-invoke \
  --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:eu-west-1:141571819444:1oj10740w0/*" \
  --region eu-west-1
```

## Stamp user_id on Existing Docs
```bash
# Already done for all 31 docs — user: f2558464-7001-7088-8818-16f339b84fb6
aws dynamodb update-item \
  --table-name DocumentMetadata \
  --region eu-west-1 \
  --key "{\"PK\":{\"S\":\"DOC#<doc_id>\"}}" \
  --update-expression "SET user_id=:u,#s=:s" \
  --expression-attribute-names "{\"#s\":\"status\"}" \
  --expression-attribute-values "{\":u\":{\"S\":\"f2558464-7001-7088-8818-16f339b84fb6\"},\":s\":{\"S\":\"INDEXED\"}}"
```

## Set S3 CORS (required for browser direct upload)
```bash
aws s3api put-bucket-cors \
  --bucket family-docs-raw \
  --region eu-west-1 \
  --cors-configuration '{"CORSRules":[{"AllowedHeaders":["*"],"AllowedMethods":["GET","PUT","POST","DELETE","HEAD"],"AllowedOrigins":["*"],"ExposeHeaders":["ETag","x-amz-request-id"],"MaxAgeSeconds":3600}]}'
```

## Trigger Backfill
```bash
# Copy-to-self triggers S3 event which fires vector_processor_lambda
aws s3 cp s3://family-docs-raw/year=2026/ s3://family-docs-raw/year=2026/ \
  --recursive --metadata-directive COPY \
  --region eu-west-1
```

## Check Bedrock KB Health
```bash
# Test semantic search
aws bedrock-agent-runtime retrieve \
  --knowledge-base-id PYV06IINGT \
  --retrieval-query text="PAN card number" \
  --retrieval-configuration vectorSearchConfiguration={numberOfResults=5} \
  --region eu-west-1 \
  --query "retrievalResults[*].[score,metadata.filename]"
```
