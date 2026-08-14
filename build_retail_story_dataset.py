"""Build ARIA storytelling fine-tuning data from downloaded Kaggle retail datasets."""

import argparse
import json
import math
import re
from pathlib import Path

import pandas as pd


DATASET_NAMES = {
    "abbas829__ecommerce-sales-dataset": "ecommerce sales analytics",
    "benroshan__ecommerce-data": "ecommerce orders",
    "ihelon__coffee-sales": "coffee sales",
    "jmmvutu__summer-products-and-sales-in-ecommerce-wish": "Wish ecommerce products",
    "karkavelrajaj__amazon-sales-dataset": "Amazon product sales",
    "manjeetsingh__retaildataset": "retail store sales",
    "mikhail1681__walmart-sales": "Walmart weekly sales",
    "mohammadtalib786__retail-sales-dataset": "retail transactions",
    "olistbr__brazilian-ecommerce": "Brazilian ecommerce",
    "rohitsahoo__sales-forecasting": "Superstore sales forecasting",
    "surajjha101__stores-area-and-sales-data": "supermarket store branches",
    "thedevastator__unlock-profits-with-e-commerce-sales-data": "ecommerce profit operations",
    "vivek468__superstore-dataset-final": "Superstore sales",
    "yapwh1208__supermarket-sales-data": "fresh grocery supermarket sales",
}

REVENUE_HINTS = [
    "sales", "revenue", "amount", "profit", "price", "money", "gross",
    "value", "total", "payment", "weekly_sales", "store_sales",
]
QUANTITY_HINTS = ["quantity", "qty", "units", "sold", "pcs", "count"]
DATE_HINTS = ["date", "month", "time"]
DIMENSION_HINTS = [
    "category", "region", "country", "state", "city", "segment", "store",
    "product", "item", "customer", "seller", "department", "dept", "type",
]


def clean_name(value):
    return re.sub(r"\s+", " ", str(value).strip())


def safe_float(value):
    try:
        if pd.isna(value):
            return None
        value = float(value)
        if math.isfinite(value):
            return round(value, 2)
    except Exception:
        return None
    return None


def normalize_column(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def read_table(path):
    try:
        if path.suffix.lower() == ".csv":
            return pd.read_csv(path, encoding_errors="ignore", low_memory=False)
        if path.suffix.lower() in {".xls", ".xlsx"}:
            return pd.read_excel(path)
        if path.suffix.lower() == ".json":
            return pd.read_json(path)
    except Exception:
        return None
    return None


def coerce_numeric(series):
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    cleaned = series.astype(str).str.replace(r"[^0-9.\-]", "", regex=True)
    return pd.to_numeric(cleaned, errors="coerce")


def score_numeric_column(column):
    normalized = normalize_column(column)
    score = 0
    for hint in REVENUE_HINTS:
        if hint in normalized:
            score += 5
    for hint in QUANTITY_HINTS:
        if hint in normalized:
            score += 2
    return score


def choose_metrics(df, limit=4):
    candidates = []
    for column in df.columns:
        numeric = coerce_numeric(df[column])
        valid_ratio = numeric.notna().mean()
        if valid_ratio < 0.55:
            continue
        nonzero = numeric.fillna(0).abs().sum()
        if nonzero <= 0:
            continue
        candidates.append((score_numeric_column(column), valid_ratio, column, numeric))
    if not candidates:
        return []
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [(column, numeric) for _, __, column, numeric in candidates[:limit]]


def choose_dimensions(df, metric_col):
    choices = []
    for column in df.columns:
        if column == metric_col:
            continue
        normalized = normalize_column(column)
        unique_count = df[column].nunique(dropna=True)
        if unique_count < 2 or unique_count > 80:
            continue
        hint_score = sum(1 for hint in DIMENSION_HINTS if hint in normalized)
        if hint_score or df[column].dtype == "object":
            choices.append((hint_score, -unique_count, column))
    choices.sort(reverse=True)
    return [column for _, __, column in choices[:3]]


def choose_date_column(df):
    for column in df.columns:
        normalized = normalize_column(column)
        if any(hint in normalized for hint in DATE_HINTS):
            parsed = pd.to_datetime(df[column], errors="coerce", dayfirst=False)
            if parsed.notna().mean() > 0.45:
                return column, parsed
    return None, None


def kpi_payload(metric, numeric):
    valid = numeric.dropna()
    if valid.empty:
        return None
    return {
        "column": clean_name(metric),
        "sum": safe_float(valid.sum()),
        "mean": safe_float(valid.mean()),
        "median": safe_float(valid.median()),
        "min": safe_float(valid.min()),
        "max": safe_float(valid.max()),
        "std": safe_float(valid.std()),
        "count": int(valid.count()),
        "null_count": int(numeric.isna().sum()),
    }


def trend_payload(df, metric, numeric, date_col, dates):
    if date_col is None:
        return []
    temp = pd.DataFrame({"date": dates, "metric": numeric}).dropna()
    if len(temp) < 12:
        return []
    grouped = temp.groupby(temp["date"].dt.to_period("M"))["metric"].sum().sort_index()
    if len(grouped) < 3:
        return []
    first = float(grouped.iloc[0])
    last = float(grouped.iloc[-1])
    if first == 0:
        pct = 0.0
    else:
        pct = round(((last - first) / abs(first)) * 100, 2)
    if pct > 5:
        direction = "increasing"
    elif pct < -5:
        direction = "decreasing"
    else:
        direction = "mixed"
    return [{
        "dimension": clean_name(date_col),
        "direction": direction,
        "pct_change": pct,
        "columns": [clean_name(metric)],
    }]


def anomaly_payload(metric, numeric):
    valid = numeric.dropna()
    if len(valid) < 8:
        return []
    std = valid.std()
    if not std or pd.isna(std):
        return []
    z = (numeric - valid.mean()) / std
    rows = []
    for idx in z.abs().sort_values(ascending=False).head(3).index:
        if pd.isna(z.loc[idx]) or abs(z.loc[idx]) < 2.0:
            continue
        rows.append({
            "column": clean_name(metric),
            "row": int(idx),
            "value": safe_float(numeric.loc[idx]),
            "z_score": safe_float(z.loc[idx]),
            "note": "beyond 2 standard deviations",
        })
    return rows


def hypothesis_payload(df, metric, numeric, dimension):
    if not dimension:
        return [{
            "hypothesis": f"{clean_name(metric)} has meaningful variation across the selected records.",
            "basis": f"descriptive analysis of {clean_name(metric)}",
            "confidence": "medium",
            "score": 8,
        }]
    temp = pd.DataFrame({"dim": df[dimension], "metric": numeric}).dropna()
    if temp.empty:
        return []
    grouped = temp.groupby("dim")["metric"].sum().sort_values(ascending=False)
    if grouped.empty:
        return []
    leader = clean_name(grouped.index[0])
    total = float(grouped.sum())
    share = round(float(grouped.iloc[0] / total * 100), 2) if total else 0.0
    return [{
        "hypothesis": f"{leader} is the leading driver of {clean_name(metric)} by {clean_name(dimension)}.",
        "basis": f"grouped sum analysis on {clean_name(metric)}",
        "confidence": "high" if share >= 45 else "medium",
        "score": round(8 + share / 5, 2),
    }]


def story_from_context(dataset_name, context, variant=0):
    kpi = context["kpis"][0]
    hyp = context["hypotheses"][0] if context["hypotheses"] else {}
    trend = context["trends"][0] if context["trends"] else None
    anomaly = context["anomalies"][0] if context["anomalies"] else None

    openings = [
        f"The headline from {dataset_name} is that {kpi['column']} is not evenly distributed; a clear business driver stands out.",
        f"The key signal in {dataset_name} is that {kpi['column']} is being shaped by a small number of stronger business segments.",
        f"{dataset_name} points to a focused performance story: {kpi['column']} has a clear leader and a visible gap from the average.",
    ]
    explanations = [
        f"The strongest hypothesis is that {hyp.get('hypothesis', 'one segment is driving the result')} This is supported by {hyp.get('basis', 'the KPI analysis')}. The total is {kpi['sum']}, with an average of {kpi['mean']}, so leaders should compare the strongest segment with the rest before changing pricing, inventory, or campaign focus.",
        f"The leading explanation is: {hyp.get('hypothesis', 'one segment is driving the result')} Because the total reaches {kpi['sum']} and the average is {kpi['mean']}, the business should understand whether the top segment is winning because of demand, assortment, location, or execution.",
        f"The most useful hypothesis is that {hyp.get('hypothesis', 'one segment is driving the result')} The KPI spread, from {kpi['min']} to {kpi['max']}, suggests the team should look for practices that can be repeated in weaker segments.",
    ]

    parts = [openings[variant % len(openings)], explanations[variant % len(explanations)]]
    if trend:
        parts.append(
            f"The time pattern is {trend['direction']}, with a {trend['pct_change']}% change across {trend['dimension']}. That tells the team whether the signal looks like momentum, slowdown, or mixed demand."
        )
    if anomaly:
        parts.append(
            f"One unusual value also needs attention: {anomaly['column']} reaches {anomaly['value']} at row {anomaly['row']}. It may be a real opportunity, a seasonal spike, or a data quality issue worth checking."
        )
    else:
        parts.append("No major anomaly dominates the result, so the finding looks more like a repeatable business pattern than a one-off spike.")
    return "\n\n".join(parts)


def instruction_from_context(context):
    return (
        "You are ARIA's Insight Agent. Write only a concise business story for a "
        "non-technical manager. Start with the headline finding, explain the leading "
        "hypothesis, mention anomalies if relevant, and stay under 250 words.\n\n"
        f"Context:\n{json.dumps(context, indent=2)}"
    )


def examples_for_file(dataset_dir, file_path, max_examples):
    df = read_table(file_path)
    if df is None or df.empty:
        return []
    df = df.dropna(axis=1, how="all")
    metrics = choose_metrics(df, limit=4)
    if not metrics:
        return []

    date_col, dates = choose_date_column(df)
    dataset_name = DATASET_NAMES.get(dataset_dir.name, dataset_dir.name.replace("__", "/"))
    examples = []

    for metric, numeric in metrics:
        dimensions = choose_dimensions(df, metric)
        for dimension in dimensions[:max_examples] or [None]:
            kpi = kpi_payload(metric, numeric)
            if not kpi:
                continue
            context = {
                "dataset": dataset_name,
                "source_file": file_path.name,
                "user_goal": f"explain {clean_name(metric)} by {clean_name(dimension) if dimension else 'business segment'}",
                "row_count": int(len(df)),
                "kpis": [kpi],
                "trends": trend_payload(df, metric, numeric, date_col, dates),
                "anomalies": anomaly_payload(metric, numeric),
                "hypotheses": hypothesis_payload(df, metric, numeric, dimension),
            }
            variant = len(examples)
            examples.append({
                "instruction": instruction_from_context(context),
                "output": story_from_context(dataset_name, context, variant=variant),
            })
    return examples


def main():
    parser = argparse.ArgumentParser(description="Build ARIA retail/sales storytelling JSONL from Kaggle downloads.")
    parser.add_argument("--input-dir", default="data/kaggle_retail_sales")
    parser.add_argument("--output", default="data/aria_retail_story_train.jsonl")
    parser.add_argument("--max-files-per-dataset", type=int, default=3)
    parser.add_argument("--max-examples-per-file", type=int, default=3)
    args = parser.parse_args()

    root = Path(args.input_dir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    summary = {}
    for dataset_dir in sorted([p for p in root.iterdir() if p.is_dir()]):
        files = [
            p for p in sorted(dataset_dir.rglob("*"))
            if p.is_file() and p.suffix.lower() in {".csv", ".xlsx", ".xls", ".json"}
        ][:args.max_files_per_dataset]
        count_before = len(rows)
        for file_path in files:
            rows.extend(examples_for_file(dataset_dir, file_path, args.max_examples_per_file))
        summary[dataset_dir.name] = len(rows) - count_before

    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary_path = output.with_suffix(".summary.json")
    summary_path.write_text(json.dumps({"total_examples": len(rows), "by_dataset": summary}, indent=2), encoding="utf-8")
    print(f"Wrote {len(rows)} examples to {output}")
    print(f"Wrote summary to {summary_path}")


if __name__ == "__main__":
    main()
