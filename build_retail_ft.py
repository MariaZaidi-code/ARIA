#!/usr/bin/env python3
"""Build a retail/sales fine-tune JSONL from CSVs in `data/kaggle_retail_sales`.

This script picks numeric metrics and categorical dimensions from each CSV,
computes lightweight KPIs (sum, mean, min, max, std), detects simple trends,
and writes instruction/output pairs suitable for the Mistral storytelling fine-tune.

Usage:
    python build_retail_ft.py --out data/aria_retail_story_train.jsonl --max-per-file 10

Run this locally; it may require `pandas` and `numpy` installed.
"""

import argparse
import json
import math
import os
from pathlib import Path

import pandas as pd


SYSTEM_PROMPT = (
    "You are ARIA's Insight Agent. Write only a concise business story for a "
    "non-technical manager. Start with the headline finding, explain the leading "
    "hypothesis, mention anomalies if relevant, and stay under 250 words."
)


def summarize_df(df: pd.DataFrame):
    numerics = df.select_dtypes(include=["number"]).columns.tolist()
    categoricals = df.select_dtypes(include=["object", "category"]).columns.tolist()
    return numerics, categoricals


def make_kpi(series: pd.Series):
    s = series.dropna()
    if s.empty:
        return None
    return {
        "column": series.name,
        "sum": float(s.sum()),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "min": float(s.min()),
        "max": float(s.max()),
        "std": float(s.std(ddof=0)) if len(s) > 1 else 0.0,
        "count": int(s.count()),
        "null_count": int(series.isna().sum()),
    }


def detect_simple_trend(series: pd.Series):
    s = series.dropna()
    if len(s) < 3:
        return None
    # crude trend: slope between first and last
    try:
        first = float(s.iloc[0])
        last = float(s.iloc[-1])
    except Exception:
        return None
    if math.isclose(first, 0.0):
        return None
    pct = ((last - first) / (abs(first) + 1e-9)) * 100.0
    direction = "increasing" if pct > 2 else "decreasing" if pct < -2 else "mixed"
    return {"dimension": "time", "direction": direction, "pct_change": round(pct, 2), "columns": [series.name]}


def make_instruction(context: dict) -> str:
    return SYSTEM_PROMPT + "\n\nContext:\n" + json.dumps(context, indent=2)


def make_story(context: dict) -> str:
    k = context.get("kpis", [])[0]
    lines = [f"Headline: {k['column']} shows a clear business signal in {context.get('dataset')}.", ""]
    lines.append(
        f"The leading hypothesis is that the strongest segment drives {k['column']}. The data shows an average of {k['mean']:.2f} and a max of {k['max']:.2f}, so teams should compare the leader with weaker segments before changing strategy."
    )
    if context.get("trends"):
        t = context["trends"][0]
        lines.append(f"The trend appears {t['direction']} ({t['pct_change']}% change), which indicates whether this is momentum or a short-term shift.")
    if context.get("anomalies"):
        lines.append("One or more unusually large values were detected and should be checked for data quality or special events.")
    return "\n\n".join(lines)


def process_file(path: Path, out_handle, max_per_file=10):
    try:
        df = pd.read_csv(path)
    except Exception:
        return 0
    numerics, cats = summarize_df(df)
    if not numerics:
        return 0
    count = 0
    for metric in numerics[:3]:
        for dim in (cats[:3] if cats else [None]):
            context = {"dataset": path.stem, "source_file": path.name, "user_goal": f"explain {metric} by {dim or 'overall'}", "row_count": int(len(df))}
            kpi = make_kpi(df[metric])
            if not kpi:
                continue
            context["kpis"] = [kpi]
            trend = None
            # try find a time-like column
            time_cols = [c for c in df.columns if "date" in c.lower() or "time" in c.lower()]
            if time_cols:
                try:
                    tcol = time_cols[0]
                    series = pd.to_datetime(df[tcol], errors="coerce")
                    # use numeric column ordered by time
                    ordered = df.sort_values(by=tcol)[metric]
                    trend = detect_simple_trend(ordered)
                except Exception:
                    trend = None
            if trend:
                context["trends"] = [trend]
            else:
                context["trends"] = []
            # anomalies: simple z-score > 2
            try:
                s = df[metric].dropna()
                if len(s) > 1:
                    mean = s.mean()
                    std = s.std(ddof=0)
                    anomalies = []
                    if std > 0:
                        z = (s - mean).abs() / std
                        idx = z[z > 2].index.tolist()[:3]
                        for i in idx:
                            anomalies.append({"column": metric, "row": int(i), "value": float(s.loc[i]), "z_score": float(z.loc[i])})
                    context["anomalies"] = anomalies
                else:
                    context["anomalies"] = []
            except Exception:
                context["anomalies"] = []

            context["hypotheses"] = [{"hypothesis": f"Top segment drives {metric}.", "basis": f"grouped analysis on {metric}", "confidence": "medium", "score": 12.0}]

            row = {"instruction": make_instruction(context), "output": make_story(context)}
            out_handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
            if count >= max_per_file:
                return count
    return count


def main():
    parser = argparse.ArgumentParser(description="Build retail fine-tune JSONL from CSVs")
    parser.add_argument("--data-dir", default="data/kaggle_retail_sales", help="Directory with retail CSVs")
    parser.add_argument("--out", default="data/aria_retail_story_train.jsonl", help="Output JSONL file")
    parser.add_argument("--max-per-file", type=int, default=8)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    with open(out_path, "w", encoding="utf-8") as oh:
        for csv in sorted(data_dir.rglob("*.csv")):
            written = process_file(csv, oh, max_per_file=args.max_per_file)
            total += written

    print(f"Wrote {total} examples to {out_path}")


if __name__ == "__main__":
    main()
