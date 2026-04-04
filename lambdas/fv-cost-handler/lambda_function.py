import json, boto3
from datetime import datetime, timezone, timedelta

ce = boto3.client("ce", region_name="us-east-1")

def cors():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Amz-Date,X-Api-Key",
        "Access-Control-Allow-Methods": "GET,OPTIONS"
    }

def lambda_handler(event, context):
    method = event.get("requestContext",{}).get("http",{}).get("method","GET").upper()
    if method == "OPTIONS":
        return {"statusCode":200,"headers":cors(),"body":""}

    params = event.get("queryStringParameters") or {}
    today = datetime.now(timezone.utc).date()

    date_from = params.get("from", (today - timedelta(days=60)).isoformat())
    date_to   = params.get("to",   today.isoformat())
    gran      = params.get("gran", "DAILY").upper()
    if gran not in ("DAILY","MONTHLY"):
        gran = "DAILY"
    if date_to > today.isoformat():
        date_to = today.isoformat()

    end_excl = (datetime.fromisoformat(date_to) + timedelta(days=1)).date().isoformat()

    AI_SVCS    = {"Claude Haiku 4.5 (Amazon Bedrock Edition)","Claude 3 Haiku (Amazon Bedrock Edition)","Claude Sonnet 4 (Amazon Bedrock Edition)","Amazon Bedrock"}
    S3_SVCS    = {"Amazon Simple Storage Service"}
    TEXT_SVCS  = {"Amazon Textract"}
    INFRA_SVCS = {"AWS Lambda","Amazon API Gateway","Amazon DynamoDB","Amazon CloudFront",
                  "Amazon Cognito","Amazon Simple Email Service","Amazon SES","Amazon Rekognition"}

    try:
        resp = ce.get_cost_and_usage(
            TimePeriod={"Start": date_from, "End": end_excl},
            Granularity=gran,
            Metrics=["BlendedCost"],
            GroupBy=[{"Type":"DIMENSION","Key":"SERVICE"}]
        )
    except Exception as e:
        print(f"CE error: {e}")
        return {"statusCode":500,"headers":cors(),"body":json.dumps({"error":str(e)})}

    daily = []
    svc_agg = {}
    grand_total = 0

    for period in resp["ResultsByTime"]:
        day_start = period["TimePeriod"]["Start"]
        day = {"date":day_start,"ai":0,"s3":0,"textract":0,"infra":0,"tax":0,"other":0,"total":0,"estimated":period.get("Estimated",False)}
        for grp in period["Groups"]:
            svc  = grp["Keys"][0]
            cost = float(grp["Metrics"]["BlendedCost"]["Amount"])
            if cost <= 0: continue
            svc_agg[svc] = svc_agg.get(svc, 0) + cost
            if svc in AI_SVCS:    day["ai"]      += cost
            elif svc in S3_SVCS:  day["s3"]      += cost
            elif svc in TEXT_SVCS:day["textract"] += cost
            elif svc in INFRA_SVCS:day["infra"]   += cost
            elif svc == "Tax":    day["tax"]      += cost
            else:                  day["other"]    += cost
            day["total"] += cost
        for k in ("ai","s3","textract","infra","tax","other","total"):
            day[k] = round(day[k], 6)
        daily.append(day)
        grand_total += day["total"]

    services = sorted(
        [{"name":k,"cost":round(v,6)} for k,v in svc_agg.items() if v > 0],
        key=lambda x: x["cost"], reverse=True
    )

    monthly_start = (today.replace(day=1) - timedelta(days=90)).isoformat()
    monthly_resp = ce.get_cost_and_usage(
        TimePeriod={"Start":monthly_start,"End":end_excl},
        Granularity="MONTHLY",
        Metrics=["BlendedCost"],
        GroupBy=[{"Type":"DIMENSION","Key":"SERVICE"}]
    )
    monthly = []
    for period in monthly_resp["ResultsByTime"]:
        m = {"month":period["TimePeriod"]["Start"][:7],"total":0,"ai":0,"estimated":period.get("Estimated",False)}
        for grp in period["Groups"]:
            svc  = grp["Keys"][0]
            cost = float(grp["Metrics"]["BlendedCost"]["Amount"])
            if cost <= 0: continue
            m["total"] += cost
            if svc in AI_SVCS: m["ai"] += cost
        m["total"] = round(m["total"], 6)
        m["ai"]    = round(m["ai"], 6)
        monthly.append(m)

    return {
        "statusCode": 200,
        "headers": cors(),
        "body": json.dumps({
            "daily":       daily,
            "services":    services,
            "monthly":     monthly,
            "grand_total": round(grand_total, 6),
            "date_from":   date_from,
            "date_to":     date_to,
            "granularity": gran,
            "generated_at": datetime.now(timezone.utc).isoformat()
        })
    }
