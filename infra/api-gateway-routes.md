# FamilyVault API Gateway Routes

API ID: `1oj10740w0`  
Base URL: `https://1oj10740w0.execute-api.eu-west-1.amazonaws.com`  
Authorizer: `kj2taa` (JWT / Cognito)

| Route | Integration | Auth | Lambda |
|---|---|---|---|
| `GET /documents` | `cw000te` | JWT | fv-upload-handler |
| `GET /notifications` | `cw000te` | JWT | fv-upload-handler |
| `POST /notifications/read` | `cw000te` | JWT | fv-upload-handler |
| `GET /download` | `bllt1be` | NONE | fv-download-handler |
| `GET /costs` | `3jzgrsa` | JWT | fv-cost-handler |

## fv-cost-handler
- ARN: `arn:aws:lambda:eu-west-1:141571819444:function:fv-cost-handler`
- Route ID: `ju6w4kq`
- Integration ID: `3jzgrsa`
- IAM: `CostExplorerReadAccess` inline policy on `FamilyVaultLambdaRole`
- Query params: `?gran=DAILY|MONTHLY &from=YYYY-MM-DD &to=YYYY-MM-DD`
- Response: `{daily[], services[], monthly[], grand_total, date_from, date_to, granularity, generated_at}`
