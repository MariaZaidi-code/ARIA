#!/usr/bin/env python3
"""Generate ARIA story-training data for fine-tuning Mistral-7B (Insight Agent).

Merges REAL examples extracted from the pipeline's `insights_*.json` files with
synthetic template examples, and writes them as `{instruction, output}` JSONL
matching the format the Kaggle fine-tune notebook expects.

Usage:
    python prepare_aria_story_data.py --output aria_story_training_data.jsonl
"""

import argparse
import json
import random
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

SYSTEM_PROMPT = (
    "You are ARIA's Insight Agent. Write only a concise business story for a "
    "non-technical manager. Start with the headline finding, explain the leading "
    "hypothesis, mention anomalies if relevant, and stay under 250 words."
)

ANOMALY_SYSTEM_PROMPT = (
    "You are ARIA's Insight Agent. Analyze the data below and report only the "
    "anomalies. For each one state: what is unusual, how large the deviation is "
    "(z-score), which possible business causes are most likely, and whether the "
    "team should act now or just monitor. Be specific and concise."
)

PRESCRIPTION_SYSTEM_PROMPT = (
    "You are ARIA's Insight Agent. Based on the analysis below, recommend 3 to 5 "
    "concrete, prioritized next actions a manager should take. Tie each action to "
    "the actual numbers and say what outcome it should produce."
)


def build_instruction(context: dict) -> str:
    return f"{SYSTEM_PROMPT}\n\nContext:\n{json.dumps(context, separators=(',', ':'))}"


def build_anomaly_instruction(context: dict) -> str:
    return f"{ANOMALY_SYSTEM_PROMPT}\n\nContext:\n{json.dumps(context, separators=(',', ':'))}"


def build_prescription_instruction(context: dict) -> str:
    return f"{PRESCRIPTION_SYSTEM_PROMPT}\n\nContext:\n{json.dumps(context, separators=(',', ':'))}"


def kpi(column, total, mean, median, lo, hi, std, count):
    return {
        "column": column, "sum": total, "mean": mean, "median": median,
        "min": lo, "max": hi, "std": std, "count": count, "null_count": 0,
    }


# ---------------------------------------------------------------------------
# Real examples from the pipeline's insight outputs
# ---------------------------------------------------------------------------

def real_examples():
    rows = []
    for path in sorted(BASE_DIR.glob("insights_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        story = data.get("business_story")
        goal = data.get("user_goal")
        if not story or not goal:
            continue
        context = {
            "user_goal": goal,
            "row_count": (data.get("summary") or {}).get("rows", 0),
            "kpis": data.get("kpis", []),
            "trends": data.get("trends", []),
            "anomalies": data.get("anomalies", []),
            "hypotheses": data.get("hypotheses", []),
        }
        if context["kpis"]:
            rows.append({"instruction": build_instruction(context), "output": story.strip()})
    return rows


# ---------------------------------------------------------------------------
# Synthetic examples (templated, following the sample style)
# ---------------------------------------------------------------------------

_METRICS = [
    ("revenue", "total_revenue", "revenue", "top"),
    ("sales", "sales", "sales performance", "strongest"),
    ("orders", "order_count", "order volumes", "busiest"),
    ("profit", "profit", "profitability", "most profitable"),
    ("avg order value", "avg_order_value", "average order value", "highest-value"),
]

_DIMS = {
    "region": ["North", "South", "East", "West", "Central"],
    "product": ["Electronics", "Furniture", "Apparel", "Groceries", "Beauty"],
    "country": ["US", "UK", "Germany", "Japan", "Brazil", "Australia"],
    "category": ["Beverages", "Dairy", "Snacks", "Meat", "Produce", "Bakery"],
}


def _round2(v):
    return round(v, 2)


def synthetic_examples(n=48, seed=7):
    rng = random.Random(seed)
    rows = []

    headline_templates = [
        "{Metric} is concentrated in a handful of {dim}, with the leading one standing well above the rest.",
        "{Metric} varies meaningfully across {dim}, and one {dim} stands out from the rest.",
        "Overall {Metric} is healthy, but performance is not evenly spread across {dim}.",
        "The numbers show a clear gap between the strongest and weakest {dim}.",
    ]
    hyp_templates = [
        "The leading hypothesis is that {top} {dim} is the main driver of the current results.",
        "Most of the performance is explained by a small number of {dim} rather than broad strength everywhere.",
        "The pattern suggests the business should look closely at {top} {dim} before setting one strategy everywhere.",
        "It looks like {top} {dim} is pulling the average up, while the rest trail behind.",
    ]
    anomaly_sentences = [
        "One observation is unusually high compared with the rest of the set. That is not automatically a problem, but it is worth checking whether it came from a seasonal order, a bulk purchase, or a repeatable pattern.",
        "There is one value that stands out from the rest. The team should confirm whether it reflects a genuine outlier or a recording error.",
    ]
    trend_sentences = [
        "The trend is also positive, with {Metric} {direction} by {pct}% over the period.",
        "On top of that, the trend points {direction}, around {pct}% over the period.",
    ]
    close_sentences = [
        "In short, the data points to {top} {dim} as the priority area for management attention.",
        "The practical takeaway is to treat {top} {dim} as a priority for availability, pricing, and promotion.",
        "Overall, this suggests focusing resources on {top} {dim} while watching the weaker {dim}.",
    ]

    for _ in range(n):
        metric_name, col, metric_label, top_label = rng.choice(_METRICS)
        dim_key, dims = rng.choice(list(_DIMS.items()))
        top_dim = rng.choice(dims)
        count = rng.randint(3, 8)
        mean = round(rng.uniform(800, 40000), 2)
        lo = round(mean * rng.uniform(0.25, 0.6), 2)
        hi = round(mean * rng.uniform(1.6, 3.2), 2)
        median = round((lo + mean) / 2 + rng.uniform(-mean * 0.1, mean * 0.1), 2)
        total = round(mean * count, 2)
        std = round(mean * rng.uniform(0.25, 0.6), 2)

        anomalies = []
        if rng.random() < 0.55:
            anomalies.append({
                "column": col, "row": count - 1, "value": hi,
                "z_score": round(rng.uniform(2.2, 3.4), 2),
                "note": "beyond 2 standard deviations",
            })

        trends = []
        if rng.random() < 0.5:
            trends.append({
                "dimension": "month", "direction": rng.choice(["increasing", "declining"]),
                "pct_change": round(rng.uniform(4.0, 25.0), 2), "columns": [col],
            })

        hypotheses = [{
            "hypothesis": f"{top_dim} is the main driver of current {metric_label}.",
            "basis": f"grouped comparison across {dim_key}",
            "confidence": rng.choice(["high", "medium"]),
            "score": round(rng.uniform(8.0, 18.0), 2),
        }]

        if not hypotheses:
            hypotheses = [{"hypothesis": "No strong single driver was identified.", "basis": "exploratory analysis", "confidence": "low", "score": 2.0}]

        context = {
            "user_goal": f"{metric_name} by {dim_key}",
            "row_count": count,
            "kpis": [kpi(col, total, mean, median, lo, hi, std, count)],
            "trends": trends,
            "anomalies": anomalies,
            "hypotheses": hypotheses,
        }

        parts = [
            rng.choice(headline_templates).format(Metric=metric_label, dim=dim_key),
            rng.choice(hyp_templates).format(top=top_label, dim=dim_key),
        ]
        if anomalies:
            parts.append(rng.choice(anomaly_sentences))
        if trends:
            t = trends[0]
            parts.append(rng.choice(trend_sentences).format(Metric=metric_label, direction=t["direction"], pct=t["pct_change"]))
        parts.append(rng.choice(close_sentences).format(top=top_dim, dim=dim_key))

        story = " ".join(parts)
        rows.append({"instruction": build_instruction(context), "output": story})

    return rows


_CAUSES = [
    "a large one-off order placed in that period",
    "a promotional or discount campaign concentrated on that segment",
    "a seasonal spike (holiday or end-of-month billing)",
    "a data-entry or ingestion error (duplicate rows, wrong unit)",
    "a pricing change that moved demand in that group",
    "an inventory gap that suppressed orders elsewhere",
]


def anomaly_examples(n=60, seed=11):
    rng = random.Random(seed)
    rows = []

    report_templates = [
        "{metric} shows {n} anomal{plural}: the most striking is {dim_name}, where the value of {value} is {z}z-score above normal. The likely cause is {cause}. Recommended action: {action}",
        "There are {n} unusual movement{plural} in {metric}. {dim_name} stands out at {value} ({z} standard deviations), most plausibly explained by {cause}. {action}",
    ]
    actions = [
        "verify the source data before reacting; if confirmed, treat it as a real signal and act on it",
        "flag it to the owning team and re-check next period before making it a headline",
        "act now: investigate the segment immediately because it materially shifts the total",
        "monitor only for now, since the deviation does not change the overall picture",
    ]
    cause_specific = {
        "seasonal": "seasonality (monthly/holiday patterns)",
        "promo": "a promotion concentrated on that group",
        "data": "a data issue rather than a true business change",
        "oneoff": "a single large transaction rather than a trend",
    }

    for _ in range(n):
        metric_name, col, metric_label, _top = rng.choice(_METRICS)
        dim_key, dims = rng.choice(list(_DIMS.items()))
        count = rng.randint(4, 9)
        mean = round(rng.uniform(800, 40000), 2)
        lo = round(mean * rng.uniform(0.3, 0.6), 2)
        hi = round(mean * rng.uniform(1.5, 3.0), 2)
        median = round((lo + mean) / 2, 2)
        total = round(mean * count, 2)
        std = round(mean * rng.uniform(0.2, 0.5), 2)

        anomalies = []
        n_anom = rng.randint(1, 3)
        for i in range(n_anom):
            dim_name = rng.choice(dims)
            z = round(rng.uniform(2.0, 4.5), 2)
            anomalies.append({
                "column": col, "dimension": dim_key, "dimension_value": dim_name,
                "value": round(mean * rng.uniform(1.5, 3.4), 2), "z_score": z,
                "note": "beyond 2 standard deviations",
            })

        trends = []
        if rng.random() < 0.5:
            trends.append({
                "dimension": "month", "direction": rng.choice(["increasing", "declining"]),
                "pct_change": round(rng.uniform(4.0, 25.0), 2), "columns": [col],
            })

        hypotheses = [{
            "hypothesis": f"the anomalous {dim_key} values are single events rather than sustained shifts",
            "basis": "z-score and recent-period comparison",
            "confidence": rng.choice(["medium", "high"]),
            "score": round(rng.uniform(8.0, 18.0), 2),
        }]

        context = {
            "user_goal": f"{metric_name} by {dim_key}",
            "row_count": count,
            "kpis": [kpi(col, total, mean, median, lo, hi, std, count)],
            "trends": trends,
            "anomalies": anomalies,
            "hypotheses": hypotheses,
        }

        parts = []
        for a in anomalies:
            cause = rng.choice(_CAUSES)
            action = rng.choice(actions)
            phrase = (
                f"{a['dimension_value']} is anomalous: {metric_label} of {a['value']} "
                f"is {a['z_score']} standard deviations above the typical level. "
                f"The most likely cause is {cause}. {action.capitalize()}."
            )
            parts.append(phrase)
        if trends:
            t = trends[0]
            parts.append(
                f"Trend context: {metric_label} has been {t['direction']} about {t['pct_change']}% over the period, so the anomalies should be read against that movement."
            )
        if not anomalies:
            parts.append("No statistically significant anomalies were detected; the data is within normal bounds.")
        rows.append({"instruction": build_anomaly_instruction(context), "output": " ".join(parts)})

    return rows


def prescription_examples(n=45, seed=13):
    rng = random.Random(seed)
    rows = []

    action_pool = [
        "Focus replenishment and staffing on the leading {top} {dim}, which drives the bulk of results.",
        "Pull the anomalous {col} values and validate them against the source system before changing any plan.",
        "Extend the current campaign into the weaker {dim} groups to close the gap behind the leaders.",
        "Set a weekly review on {col} by {dim} so a real change in the anomaly is caught within days.",
        "Re-run the analysis after the next period to confirm the trend is persistent and not a blip.",
        "Check the pricing and promotion mix for the {top} {dim} segment before scaling it globally.",
        "Ask the operations team whether the declining {dim} group lost inventory or promotion coverage.",
        "Model the financial impact of shifting 10% of effort from the weakest {dim} to the strongest.",
    ]
    openers = [
        "Based on the analysis, the manager should act on three fronts.",
        "The numbers support these prioritized actions.",
        "Given the findings, I recommend the following next steps.",
    ]
    closers = [
        "Executing these in order should improve the headline {col} number within two periods.",
        "These steps should stabilize the anomaly and lift the trailing {dim} groups.",
    ]

    for _ in range(n):
        metric_name, col, metric_label, top_label = rng.choice(_METRICS)
        dim_key, dims = rng.choice(list(_DIMS.items()))
        top_dim = rng.choice(dims)
        weak_dim = rng.choice(dims)
        count = rng.randint(4, 9)
        mean = round(rng.uniform(800, 40000), 2)
        lo = round(mean * 0.35, 2)
        hi = round(mean * 2.2, 2)
        total = round(mean * count, 2)
        std = round(mean * 0.35, 2)

        anomalies = []
        if rng.random() < 0.6:
            anomalies.append({
                "column": col, "dimension": dim_key, "dimension_value": top_dim,
                "value": hi, "z_score": round(rng.uniform(2.2, 3.8), 2),
                "note": "beyond 2 standard deviations",
            })

        trends = []
        if rng.random() < 0.6:
            trends.append({
                "dimension": "month", "direction": rng.choice(["increasing", "declining"]),
                "pct_change": round(rng.uniform(4.0, 25.0), 2), "columns": [col],
            })

        context = {
            "user_goal": f"{metric_name} by {dim_key}",
            "row_count": count,
            "kpis": [kpi(col, total, mean, median := round((lo + mean) / 2, 2), lo, hi, std, count)],
            "trends": trends,
            "anomalies": anomalies,
            "hypotheses": [{
                "hypothesis": f"{top_dim} is the main driver of current {metric_label}.",
                "basis": "grouped comparison across " + dim_key,
                "confidence": "high", "score": round(rng.uniform(9.0, 18.0), 2),
            }],
        }

        chosen = rng.sample(action_pool, rng.randint(3, 4))
        fmt = {"top": top_dim, "dim": dim_key, "col": col}
        lines = [c.format(**fmt) for c in chosen]
        out = f"{rng.choice(openers)} " + " ".join(lines) + " " + rng.choice(closers).format(**fmt)
        rows.append({"instruction": build_prescription_instruction(context), "output": out})

    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="aria_story_training_data.jsonl")
    args = parser.parse_args()

    rows = real_examples() + synthetic_examples() + anomaly_examples() + prescription_examples()
    out = BASE_DIR / args.output
    with open(out, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    real_count = len(real_examples())
    print(f"Wrote {len(rows)} examples ({real_count} real, {len(rows) - real_count} synthetic) to {out}")


if __name__ == "__main__":
    main()