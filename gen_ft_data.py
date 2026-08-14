"""Generate starter JSONL data for ARIA's Mistral storytelling fine-tune.

This creates only Insight Agent story examples. Do not mix SQL or schema tasks
into this dataset, because the target model should learn ARIA's business
storytelling voice only.
"""

import argparse
import json
import random


random.seed(42)

GOALS = [
    "sales by region",
    "top products by revenue",
    "orders over time",
    "revenue by category",
    "customer count by country",
    "average order value",
    "monthly profit trend",
    "supplier contribution to revenue",
]

DIMENSIONS = ["region", "country", "category", "product", "customer segment", "month"]
METRICS = ["sales", "revenue", "orders", "profit", "avg_order_value", "quantity"]


def make_context():
    metric = random.choice(METRICS)
    dimension = random.choice(DIMENSIONS)
    high = round(random.uniform(80_000, 900_000), 2)
    low = round(high * random.uniform(0.18, 0.65), 2)
    mean = round((high + low) / random.uniform(2.4, 4.2), 2)
    leader = random.choice(["West", "USA", "Beverages", "Enterprise", "Seafood", "Q4"])

    anomalies = []
    if random.random() > 0.35:
        anomalies.append({
            "column": metric,
            "row": random.randint(1, 60),
            "value": high,
            "z_score": round(random.uniform(2.1, 4.8), 2),
            "note": "beyond 2 standard deviations",
        })

    trends = []
    if random.random() > 0.25:
        trends.append({
            "dimension": random.choice(["month", "quarter", "order_date"]),
            "direction": random.choice(["increasing", "decreasing", "mixed"]),
            "pct_change": round(random.uniform(4, 38), 1),
            "columns": [metric],
        })

    return {
        "user_goal": random.choice(GOALS),
        "row_count": random.randint(5, 80),
        "kpis": [{
            "column": metric,
            "sum": round(high + low + random.uniform(25_000, 500_000), 2),
            "mean": mean,
            "median": round(mean * random.uniform(0.8, 1.1), 2),
            "min": low,
            "max": high,
            "std": round(mean * random.uniform(0.15, 0.7), 2),
            "count": random.randint(5, 80),
            "null_count": 0,
        }],
        "trends": trends,
        "anomalies": anomalies,
        "hypotheses": [{
            "hypothesis": f"{leader} is likely the main driver of {metric} by {dimension}.",
            "basis": f"grouped analysis of {metric} by {dimension}",
            "confidence": random.choice(["medium", "high"]),
            "score": round(random.uniform(8, 18), 2),
        }],
    }


def make_story(context):
    kpi = context["kpis"][0]
    hypothesis = context["hypotheses"][0]["hypothesis"]
    trend = context["trends"][0] if context["trends"] else None
    anomaly = context["anomalies"][0] if context["anomalies"] else None

    lines = [
        f"The main finding is that {kpi['column']} is concentrated around a clear business driver.",
        "",
        f"The strongest explanation is: {hypothesis} The data shows an average of {kpi['mean']} with a high point of {kpi['max']}, so management should compare the leading segment with weaker segments before changing the overall strategy.",
    ]
    if trend:
        lines.append(
            f"The trend is {trend['direction']}, with a {trend['pct_change']}% change across {trend['dimension']}. That gives the team a useful signal about whether this is momentum or a short-term shift."
        )
    if anomaly:
        lines.append(
            f"There is also an unusual {anomaly['column']} value of {anomaly['value']}. It should be checked to see whether it is a real business opportunity, a seasonal effect, or a data quality issue."
        )
    return "\n\n".join(lines)


def make_instruction(context):
    return (
        "You are ARIA's Insight Agent. Write only a concise business story for "
        "a non-technical manager. Start with the headline finding, explain the "
        "leading hypothesis, mention anomalies if relevant, and stay under 250 words.\n\n"
        f"Context:\n{json.dumps(context, indent=2)}"
    )


def main():
    parser = argparse.ArgumentParser(description="Create ARIA story-only fine-tuning data.")
    parser.add_argument("--count", type=int, default=300)
    parser.add_argument("--output", default="ft_story_data.jsonl")
    args = parser.parse_args()

    with open(args.output, "w", encoding="utf-8") as handle:
        for _ in range(args.count):
            context = make_context()
            row = {"instruction": make_instruction(context), "output": make_story(context)}
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Wrote {args.count} ARIA storytelling examples to {args.output}")


if __name__ == "__main__":
    main()
