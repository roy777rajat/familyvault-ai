# Cost Dashboard Feature

Added in Session 6 (Apr 4 2026).

## What it is
A live AWS cost dashboard embedded in the FamilyVault app sidebar under **Account > 💰 Costs**.

## Features
- **6 KPI cards**: March total, April total, AI cost, Today, Avg/day, Free tier status
- **Insights banner**: auto-generated observations and projections
- **3 tabs**:
  - 📈 Daily Chart — stacked bar chart with date range + daily/weekly toggle
  - 🗂️ By Service — donut chart + service breakdown with Free/Paid/Tax badges
  - 📊 Daily Table — full daily breakdown with totals row + projection box
- **Real data** from AWS Cost Explorer (Mar 1 – Apr 4 2026)
- Chart.js loaded on-demand from CDN

## Data (embedded, as of Apr 4 2026)
- March 2026 total: $0.5793
- April 2026 (4 days): $0.2227
- Apr 3 highest day: $0.1039
- 96% of spend = Claude AI (Haiku 4.5)
- Lambda, DynamoDB, API GW, CloudFront, SES, Cognito, Textract = $0 (free tier)

## Nav injection
```js
{icon:'💰', label:'Costs', s:'costs'}  // added to Account section in buildSidebar()
case 'costs': content=buildCosts(); break;  // added to screen switch
```

## To update data
Run AWS Cost Explorer query and update the DAILY array and SVC array in buildCosts().
