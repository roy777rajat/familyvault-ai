# Cost Dashboard Feature

Added: Session 8, Apr 4 2026

## Architecture
```
Browser
  └─ GET /costs?gran=DAILY&from=...&to=...
       └─ API Gateway (JWT auth)
            └─ fv-cost-handler Lambda (eu-west-1)
                 └─ boto3 ce.get_cost_and_usage()  ← LIVE, real-time
                      └─ AWS Cost Explorer API (us-east-1)
```

## UI Location
Sidebar → Account → 💰 Costs

## Tabs
1. **📈 Daily Chart** — Chart.js stacked bar, date range picker, monthly summary cards
2. **🗂️ By Service** — Donut chart + service list with Free/AI/Tax/Other badges
3. **📊 Table** — Full daily breakdown with totals row + projections box

## Key Points
- **100% live** — calls AWS Cost Explorer on every visit, no static data
- **buildCosts()** uses pure `document.createElement()` — zero app helper calls
- `fetch()` with `Authorization: Bearer S.token` — bypasses broken req() async
- `setTimeout(doLoad, 300)` ensures S.token is set before first fetch
- ↻ Refresh button re-fetches live data
- Status badge: Loading… → ✓ Live · YYYY-MM-DD → Error: message

## Services Categorised
| Category | Services |
|---|---|
| AI | Claude Haiku 4.5, Claude 3 Haiku, Claude Sonnet 4, Amazon Bedrock |
| S3 | Amazon Simple Storage Service |
| Textract | Amazon Textract |
| Infra (Free) | Lambda, API GW, DynamoDB, CloudFront, Cognito, SES, Rekognition |
| Tax | Tax |
| Other | Everything else |

## Cost Data (as of Apr 4 2026)
- March 2026: ~$0.58 (AI = 96%)
- April 2026: ~$0.22 (4 days)
- Apr 3 highest day: $0.1039
- All infra services: $0.00 (free tier)
