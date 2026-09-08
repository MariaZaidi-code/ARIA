"""Insights detection engine — fully dynamic, database-agnostic.

Generates real insights from ANY connected database using schema metadata
(data_type, primary_key, declared_relationships) — zero hardcoded assumptions.

Provides GET /api/insights, POST /api/insights/save, DELETE /api/insights/save/{id},
GET /api/insights/saved, POST /api/insights/{id}/ask.
"""

import math
import statistics
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from core.deps import require_writable
from core.config import get_session, save_session
from api.schema_intel import SchemaIntelligence, _safe_name, _run_sql, AMOUNT_HINTS

router = APIRouter(tags=["insights"])


# ── Helpers (local to insights engine) ──────────────────────────────────

def _safe_float(v):
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _fmt_currency(v):
    if v is None:
        return "N/A"
    if abs(v) >= 1_000_000:
        return f"${v/1_000_000:,.1f}M"
    if abs(v) >= 1_000:
        return f"${v/1_000:,.0f}K"
    return f"${v:,.0f}"


def _fmt_pct(v):
    if v is None:
        return "N/A"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.1f}%"


# ── Insight Detection Engine ─────────────────────────────────────────────

class InsightsEngine:
    """Detect real insights from any connected database. Fully dynamic.

    Uses shared SchemaIntelligence from api.schema_intel — no duplication.
    Accepts either a raw DB-API connection (psycopg2/pymysql) or a
    SQLAlchemy engine for cross-table queries.
    """

    def __init__(self, conn, mapping: dict, llm=None):
        self.conn = conn
        self.mapping = mapping
        self.llm = llm
        self.intel = SchemaIntelligence(mapping)

    def generate_all_insights(self, max_insights: int = 20):
        """Run all detectors, return ranked insights."""
        insights = []

        for tname in self.intel.tables:
            # Skip empty tables
            tinfo = self.intel.tables[tname]
            if tinfo.get("empty"):
                continue

            # Skip tables with no meaningful numeric measures (dimension-only tables)
            measure = self.intel.find_best_measure(tname)
            if not measure:
                continue

            try:
                insights.extend(self._detect_growth_decline(tname))
            except Exception:
                pass
            try:
                insights.extend(self._detect_trends(tname))
            except Exception:
                pass
            try:
                insights.extend(self._detect_anomalies(tname))
            except Exception:
                pass
            try:
                insights.extend(self._detect_opportunities(tname))
            except Exception:
                pass
            try:
                insights.extend(self._detect_risks(tname))
            except Exception:
                pass

        # Cross-table correlation
        try:
            insights.extend(self._detect_correlations())
        except Exception:
            pass

        insights = self._deduplicate(insights)
        insights = self._rank(insights)
        return insights[:max_insights]

    # ── Growth / Decline ──────────────────────────────────────────────────

    def _detect_growth_decline(self, table: str):
        insights = []
        date_col = self.intel.find_best_datetime(table)
        if not date_col:
            return []

        measure = self.intel.find_best_measure(table)
        if not measure:
            return []

        # Get current vs previous period
        sql = f"""
            WITH monthly AS (
                SELECT date_trunc('month', {_safe_name(date_col)}) AS period,
                       SUM({_safe_name(measure)}) AS val
                FROM {_safe_name(table)}
                WHERE {_safe_name(date_col)} IS NOT NULL
                GROUP BY period
                ORDER BY period DESC
                LIMIT 12
            )
            SELECT period, val FROM monthly ORDER BY period
        """
        _, rows = _run_sql(self.conn, sql, limit=12)
        if len(rows) < 2:
            return []

        values = [(r["period"], _safe_float(r["val"])) for r in rows if _safe_float(r["val"]) is not None]
        if len(values) < 2:
            return []

        current_val = values[-1][1]
        previous_val = values[-2][1]
        if previous_val == 0 or previous_val is None:
            return []

        change_pct = ((current_val - previous_val) / abs(previous_val)) * 100
        period_label = self._period_label(values[-1][0], values[-2][0])

        # Determine table description for titles
        tdesc = self.intel.tables[table].get("description", table)
        metric_label = f"{measure} ({tdesc})" if tdesc and tdesc != table else measure

        confidence = self._compute_confidence(change_pct, len(values), abs(current_val), abs(previous_val))
        viz_data = [{"period": str(v[0])[:7], "value": v[1]} for v in values]

        observations = [
            f"{measure} was {_fmt_currency(previous_val)} in the previous period.",
            f"{measure} is {_fmt_currency(current_val)} in the current period.",
            f"This represents a {_fmt_pct(change_pct)} change.",
        ]
        if len(values) >= 4:
            avg = statistics.mean([v[1] for v in values])
            observations.append(f"Average over the last {len(values)} periods: {_fmt_currency(avg)}.")

        if change_pct > 5:
            insight_type = "Growth"
            severity = self._compute_severity(change_pct, confidence, current_val)
            title = f"{tdesc or table}: {measure} grew {_fmt_pct(change_pct)} to {_fmt_currency(current_val)}"
        elif change_pct < -5:
            insight_type = "Decline"
            severity = self._compute_severity(abs(change_pct), confidence, current_val)
            title = f"{tdesc or table}: {measure} declined {_fmt_pct(change_pct)} to {_fmt_currency(current_val)}"
        else:
            return []

        impact_value = current_val - previous_val
        dims = self.intel.get_text_cols(table)[:3]

        insights.append(self._build_insight(
            insight_id=f"gd_{table}_{measure}",
            insight_type=insight_type,
            severity=severity,
            title=title,
            description=f"{measure} in {tdesc or table} changed from {_fmt_currency(previous_val)} to {_fmt_currency(current_val)} ({_fmt_pct(change_pct)}) from {period_label}.",
            metric=metric_label,
            metric_value=current_val,
            previous_value=previous_val,
            magnitude=_fmt_pct(change_pct),
            confidence=confidence,
            affected_period=period_label,
            tags=[table, measure, insight_type.lower()],
            observations=observations,
            support_metrics=[f"Period-over-period change: {_fmt_pct(change_pct)}"],
            sample_size=len(values),
            baseline=previous_val,
            current_value=current_val,
            change_pct=change_pct,
            impact_value=impact_value,
            impact_direction="positive" if impact_value > 0 else "negative",
            impact_explanation=f"The {_fmt_pct(change_pct)} change in {measure} represents a {'gain' if impact_value > 0 else 'loss'} of {_fmt_currency(abs(impact_value))}.",
            next_question=f"What caused the {_fmt_pct(change_pct)} {'increase' if change_pct > 0 else 'decrease'} in {measure} in {tdesc or table}?",
            next_dims=dims,
            viz_type="area",
            viz_data=viz_data,
            source_tables=[table],
            source_columns=[date_col, measure],
        ))

        return insights

    # ── Trends ────────────────────────────────────────────────────────────

    def _detect_trends(self, table: str):
        insights = []
        date_col = self.intel.find_best_datetime(table)
        if not date_col:
            return []

        measure = self.intel.find_best_measure(table)
        if not measure:
            return []

        sql = f"""
            SELECT date_trunc('month', {_safe_name(date_col)}) AS period,
                   SUM({_safe_name(measure)}) AS val
            FROM {_safe_name(table)}
            WHERE {_safe_name(date_col)} IS NOT NULL
            GROUP BY period
            ORDER BY period
            LIMIT 24
        """
        _, rows = _run_sql(self.conn, sql, limit=24)
        if len(rows) < 6:
            return []

        values = [(r["period"], _safe_float(r["val"])) for r in rows if _safe_float(r["val"]) is not None]
        if len(values) < 6:
            return []

        nums = [v[1] for v in values]
        n = len(nums)
        x_mean = (n - 1) / 2
        y_mean = statistics.mean(nums)
        numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(nums))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        if denominator == 0:
            return []

        slope = numerator / denominator
        if y_mean == 0:
            return []
        slope_pct = (slope / abs(y_mean)) * 100

        consecutive = sum(1 for i in range(1, n) if (nums[i] > nums[i-1]) == (slope > 0))
        consistency = consecutive / (n - 1)

        if abs(slope_pct) < 1 or consistency < 0.6:
            return []

        ss_res = sum((y - (y_mean + slope * (i - x_mean))) ** 2 for i, y in enumerate(nums))
        ss_tot = sum((y - y_mean) ** 2 for y in nums)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

        confidence = min(95, max(30, int(r_squared * 100 * consistency)))
        direction = "increasing" if slope > 0 else "decreasing"
        period_months = self._period_label(values[-1][0], values[0][0])
        tdesc = self.intel.tables[table].get("description", table)
        severity = self._compute_severity(abs(slope_pct) * len(nums), confidence, nums[-1])
        viz_data = [{"period": str(v[0])[:7], "value": v[1]} for v in values]
        dims = self.intel.get_text_cols(table)[:3]

        insights.append(self._build_insight(
            insight_id=f"tr_{table}_{measure}",
            insight_type="Trend",
            severity=severity,
            title=f"{tdesc or table}: {measure} shows {direction} trend ({_fmt_pct(slope_pct)}/period)",
            description=f"{measure} in {tdesc or table} has been {direction} consistently over {len(values)} periods ({period_months}). The average rate of change is {_fmt_pct(slope_pct)} per period with {consistency*100:.0f}% consistency.",
            metric=f"{measure} ({tdesc or table})",
            metric_value=nums[-1],
            previous_value=nums[0],
            magnitude=_fmt_pct(slope_pct * len(nums)),
            confidence=confidence,
            affected_period=period_months,
            tags=[table, measure, "trend", direction],
            observations=[
                f"{measure} started at {_fmt_currency(nums[0])} and ended at {_fmt_currency(nums[-1])} over {len(values)} periods.",
                f"Linear trend slope: {_fmt_pct(slope_pct)} per period. R-squared: {r_squared:.3f}. Consistency: {consistency*100:.0f}%.",
            ],
            support_metrics=[f"Trend slope: {_fmt_pct(slope_pct)}/period", f"R²: {r_squared:.3f}"],
            sample_size=len(values),
            baseline=nums[0],
            current_value=nums[-1],
            change_pct=((nums[-1] - nums[0]) / abs(nums[0])) * 100 if nums[0] != 0 else 0,
            impact_value=nums[-1] - nums[0],
            impact_direction="positive" if slope > 0 else "negative",
            impact_explanation=f"Sustained {direction} trend in {measure} over {len(values)} periods suggests a {'positive' if slope > 0 else 'negative'} trajectory.",
            next_question=f"What factors are driving the {direction} trend in {measure}?",
            next_dims=dims,
            viz_type="area",
            viz_data=viz_data,
            source_tables=[table],
            source_columns=[date_col, measure],
        ))

        return insights

    # ── Anomalies ─────────────────────────────────────────────────────────

    def _detect_anomalies(self, table: str):
        insights = []
        date_col = self.intel.find_best_datetime(table)
        if not date_col:
            return []

        measure = self.intel.find_best_measure(table)
        if not measure:
            return []

        sql = f"""
            SELECT date_trunc('month', {_safe_name(date_col)}) AS period,
                   SUM({_safe_name(measure)}) AS val
            FROM {_safe_name(table)}
            WHERE {_safe_name(date_col)} IS NOT NULL
            GROUP BY period
            ORDER BY period
            LIMIT 24
        """
        _, rows = _run_sql(self.conn, sql, limit=24)
        if len(rows) < 6:
            return []

        values = [(r["period"], _safe_float(r["val"])) for r in rows if _safe_float(r["val"]) is not None]
        if len(values) < 6:
            return []

        nums = [v[1] for v in values]
        sorted_nums = sorted(nums)
        n = len(sorted_nums)
        q1 = sorted_nums[n // 4]
        q3 = sorted_nums[3 * n // 4]
        iqr = q3 - q1
        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr
        mean_val = statistics.mean(nums)
        std_val = statistics.stdev(nums) if len(nums) > 1 else 0
        tdesc = self.intel.tables[table].get("description", table)

        for period, val in values:
            if val is None:
                continue
            if val < lower_bound or val > upper_bound:
                z_score = (val - mean_val) / std_val if std_val > 0 else 0
                direction = "above" if val > upper_bound else "below"
                confidence = min(95, max(40, int(min(abs(z_score) * 25, 95))))
                severity = "high" if abs(z_score) > 2.5 else ("medium" if abs(z_score) > 1.5 else "low")
                period_str = period.strftime('%b %Y') if hasattr(period, 'strftime') else str(period)
                viz_data = [{"period": str(v[0])[:7], "value": v[1], "anomaly": v[0] == period} for v in values]
                dims = self.intel.get_text_cols(table)[:3]

                insights.append(self._build_insight(
                    insight_id=f"an_{table}_{measure}_{period_str.replace(' ', '_')}",
                    insight_type="Anomaly",
                    severity=severity,
                    title=f"{tdesc or table}: {measure} anomaly at {_fmt_currency(val)} in {period_str} ({direction} normal range)",
                    description=f"{measure} reached {_fmt_currency(val)} in {period_str}, which is {direction} the expected range of {_fmt_currency(lower_bound)} to {_fmt_currency(upper_bound)}. Z-score: {z_score:.2f}.",
                    metric=f"{measure} ({tdesc or table})",
                    metric_value=val,
                    previous_value=mean_val,
                    magnitude=f"{_fmt_currency(val)} (z={z_score:.1f})",
                    confidence=confidence,
                    affected_period=period_str,
                    tags=[table, measure, "anomaly", direction],
                    observations=[
                        f"Observed value: {_fmt_currency(val)} in {period_str}.",
                        f"Expected range: {_fmt_currency(lower_bound)} to {_fmt_currency(upper_bound)} (IQR method).",
                        f"Mean: {_fmt_currency(mean_val)}, Std Dev: {_fmt_currency(std_val)}. Z-score: {z_score:.2f}.",
                    ],
                    support_metrics=[f"Z-score: {z_score:.2f}", f"IQR bounds: [{_fmt_currency(lower_bound)}, {_fmt_currency(upper_bound)}]"],
                    sample_size=len(values),
                    baseline=mean_val,
                    current_value=val,
                    change_pct=((val - mean_val) / abs(mean_val) * 100) if mean_val != 0 else 0,
                    impact_value=val - mean_val,
                    impact_direction="positive" if val > mean_val else "negative",
                    impact_explanation=f"The {direction} normal {measure} of {_fmt_currency(val)} in {period_str} may indicate {'an exceptional opportunity' if val > mean_val else 'a potential issue requiring investigation'}.",
                    next_question=f"What caused {measure} to be {direction} normal in {period_str}?",
                    next_dims=dims,
                    viz_type="area",
                    viz_data=viz_data,
                    source_tables=[table],
                    source_columns=[date_col, measure],
                ))

        return insights

    # ── Opportunities ─────────────────────────────────────────────────────

    def _detect_opportunities(self, table: str):
        insights = []
        dim = self.intel.find_best_dimension(table)
        if not dim:
            return []

        measure = self.intel.find_best_measure(table)
        if not measure:
            return []

        tdesc = self.intel.tables[table].get("description", table)

        sql = f"""
            SELECT {_safe_name(dim)} AS dim_val, SUM({_safe_name(measure)}) AS val
            FROM {_safe_name(table)}
            WHERE {_safe_name(dim)} IS NOT NULL
            GROUP BY {_safe_name(dim)}
            ORDER BY val DESC
            LIMIT 20
        """
        _, rows = _run_sql(self.conn, sql, limit=20)
        if len(rows) < 3:
            return []

        values = [(r["dim_val"], _safe_float(r["val"])) for r in rows if _safe_float(r["val"]) is not None]
        if len(values) < 3:
            return []

        total = sum(v[1] for v in values)
        if total == 0:
            return []

        top = values[0]
        top_share = (top[1] / total) * 100
        mid = len(values) // 2
        top_half = values[:mid] if mid > 0 else values[:1]
        bottom_half = values[mid:] if mid < len(values) else values[-1:]

        if top_half and bottom_half:
            top_avg = statistics.mean([v[1] for v in top_half])
            bottom_avg = statistics.mean([v[1] for v in bottom_half])
            if top_avg > 0:
                gap_ratio = (top_avg - bottom_avg) / top_avg * 100
                if gap_ratio > 30:
                    confidence = min(90, max(40, int(gap_ratio * 0.8)))
                    severity = "medium" if gap_ratio > 50 else "low"
                    viz_data = [{"name": str(v[0]), "value": v[1]} for v in values[:10]]

                    insights.append(self._build_insight(
                        insight_id=f"op_{table}_{dim}",
                        insight_type="Opportunity",
                        severity=severity,
                        title=f"{tdesc or table}: Underpenetrated segments in {dim}",
                        description=f"The top {dim} ({top[0]}) generates {_fmt_currency(top[1])} ({top_share:.1f}%). Bottom segments average {_fmt_currency(bottom_avg)} vs top half {_fmt_currency(top_avg)}, a {gap_ratio:.0f}% gap.",
                        metric=f"{measure} ({tdesc or table})",
                        metric_value=total,
                        magnitude=f"{gap_ratio:.0f}% gap",
                        confidence=confidence,
                        affected_period="Current period",
                        tags=[table, dim, "opportunity", "underpenetrated"],
                        observations=[
                            f"Top {dim}: {top[0]} at {_fmt_currency(top[1])} ({top_share:.1f}% share).",
                            f"Top half average: {_fmt_currency(top_avg)}. Bottom half: {_fmt_currency(bottom_avg)}. Gap: {gap_ratio:.0f}%.",
                        ],
                        support_metrics=[f"Concentration: {top_share:.1f}%", f"Gap: {gap_ratio:.0f}%"],
                        sample_size=len(values),
                        impact_value=top_avg - bottom_avg,
                        impact_direction="positive",
                        impact_explanation=f"Closing the gap could unlock up to {_fmt_currency(top_avg - bottom_avg)} in additional {measure}.",
                        next_question=f"What is driving the performance gap in {dim}?",
                        next_dims=[dim],
                        viz_type="bar",
                        viz_data=viz_data,
                        source_tables=[table],
                        source_columns=[dim, measure],
                    ))

        # High-growth dimension
        date_col = self.intel.find_best_datetime(table)
        if date_col and len(values) >= 3:
            for dv in values[:3]:
                sql2 = f"""
                    SELECT date_trunc('month', {_safe_name(date_col)}) AS period,
                           SUM({_safe_name(measure)}) AS val
                    FROM {_safe_name(table)}
                    WHERE {_safe_name(dim)} = %s AND {_safe_name(date_col)} IS NOT NULL
                    GROUP BY period ORDER BY period LIMIT 12
                """
                try:
                    cur = self.conn.cursor()
                    cur.execute(sql2, (str(dv[0]),))
                    cols = [d[0] for d in cur.description]
                    period_rows = cur.fetchmany(12)
                    cur.close()
                    if len(period_rows) < 3:
                        continue
                    pvals = [(r[0], _safe_float(r[1])) for r in period_rows if _safe_float(r[1]) is not None]
                    if len(pvals) < 3:
                        continue
                    fv, lv = pvals[0][1], pvals[-1][1]
                    if fv and lv and fv > 0:
                        growth_pct = ((lv - fv) / abs(fv)) * 100
                        if growth_pct > 20:
                            confidence = min(85, max(35, int(growth_pct * 0.5)))
                            viz_data_g = [{"period": "start", "value": fv}, {"period": "end", "value": lv}]
                            insights.append(self._build_insight(
                                insight_id=f"og_{table}_{dim}_{dv[0]}",
                                insight_type="Opportunity",
                                severity="medium",
                                title=f"{tdesc or table}: High-growth {dim} '{dv[0]}' ({_fmt_pct(growth_pct)})",
                                description=f"{dim} '{dv[0]}' in {tdesc or table} grew from {_fmt_currency(fv)} to {_fmt_currency(lv)} ({_fmt_pct(growth_pct)}).",
                                metric=f"{measure} ({tdesc or table})",
                                metric_value=lv,
                                previous_value=fv,
                                magnitude=_fmt_pct(growth_pct),
                                confidence=confidence,
                                affected_period="Period-over-period",
                                tags=[table, dim, "opportunity", "high-growth", str(dv[0])],
                                observations=[f"{dim} '{dv[0]}' grew from {_fmt_currency(fv)} to {_fmt_currency(lv)} ({_fmt_pct(growth_pct)})."],
                                support_metrics=[f"Growth: {_fmt_pct(growth_pct)}"],
                                baseline=fv,
                                current_value=lv,
                                change_pct=growth_pct,
                                impact_value=lv - fv,
                                impact_direction="positive",
                                impact_explanation=f"Continued growth in '{dv[0]}' represents an expansion opportunity.",
                                next_question=f"What is driving growth in {dim} '{dv[0]}'?",
                                next_dims=[dim],
                                viz_type="bar",
                                viz_data=viz_data_g,
                                source_tables=[table],
                                source_columns=[dim, date_col, measure],
                            ))
                except Exception:
                    continue

        return insights

    # ── Risks ─────────────────────────────────────────────────────────────

    def _detect_risks(self, table: str):
        insights = []
        date_col = self.intel.find_best_datetime(table)
        if not date_col:
            return []

        measure = self.intel.find_best_measure(table)
        if not measure:
            return []

        sql = f"""
            SELECT date_trunc('month', {_safe_name(date_col)}) AS period,
                   SUM({_safe_name(measure)}) AS val
            FROM {_safe_name(table)}
            WHERE {_safe_name(date_col)} IS NOT NULL
            GROUP BY period
            ORDER BY period
            LIMIT 12
        """
        _, rows = _run_sql(self.conn, sql, limit=12)
        if len(rows) < 4:
            return []

        values = [(r["period"], _safe_float(r["val"])) for r in rows if _safe_float(r["val"]) is not None]
        if len(values) < 4:
            return []

        nums = [v[1] for v in values]
        tdesc = self.intel.tables[table].get("description", table)

        # Consecutive declines
        declining_streak = 0
        for i in range(len(nums) - 1, 0, -1):
            if nums[i] < nums[i - 1]:
                declining_streak += 1
            else:
                break

        if declining_streak >= 3:
            total_decline = ((nums[-1] - nums[0]) / abs(nums[0])) * 100 if nums[0] != 0 else 0
            confidence = min(90, max(40, declining_streak * 20))
            severity = "high" if declining_streak >= 4 else "medium"
            period_label = self._period_label(values[-1][0], values[0][0])
            viz_data = [{"period": str(v[0])[:7], "value": v[1]} for v in values]
            dims = self.intel.get_text_cols(table)[:3]

            insights.append(self._build_insight(
                insight_id=f"rk_{table}_{measure}",
                insight_type="Risk",
                severity=severity,
                title=f"{tdesc or table}: Sustained decline — {measure} down {declining_streak} consecutive periods",
                description=f"{measure} in {tdesc or table} declined for {declining_streak} consecutive periods, from {_fmt_currency(nums[0])} to {_fmt_currency(nums[-1])} ({_fmt_pct(total_decline)}).",
                metric=f"{measure} ({tdesc or table})",
                metric_value=nums[-1],
                previous_value=nums[0],
                magnitude=_fmt_pct(total_decline),
                confidence=confidence,
                affected_period=period_label,
                tags=[table, measure, "risk", "decline"],
                observations=[
                    f"{measure} declined for {declining_streak} consecutive periods.",
                    f"Total decline: from {_fmt_currency(nums[0])} to {_fmt_currency(nums[-1])} ({_fmt_pct(total_decline)}).",
                ],
                support_metrics=[f"Declining streak: {declining_streak}", f"Total decline: {_fmt_pct(total_decline)}"],
                sample_size=len(values),
                baseline=nums[0],
                current_value=nums[-1],
                change_pct=total_decline,
                impact_value=nums[-1] - nums[0],
                impact_direction="negative",
                impact_explanation=f"Continued decline could result in further losses of {_fmt_currency(abs(nums[-1] - nums[0]))} per period.",
                next_question=f"What is causing the sustained decline in {measure}?",
                next_dims=dims,
                viz_type="area",
                viz_data=viz_data,
                source_tables=[table],
                source_columns=[date_col, measure],
            ))

        # Stagnation
        if len(nums) >= 6:
            mean_val = statistics.mean(nums)
            cv = (statistics.stdev(nums) / mean_val * 100) if mean_val != 0 else 0
            if cv < 5:
                recent_trend = nums[-1] - nums[-3] if len(nums) >= 3 else 0
                if abs(recent_trend) < mean_val * 0.02:
                    confidence = min(75, max(30, int(80 - cv * 10)))
                    period_label = self._period_label(values[-1][0], values[0][0])
                    viz_data = [{"period": str(v[0])[:7], "value": v[1]} for v in values]
                    dims = self.intel.get_text_cols(table)[:3]

                    insights.append(self._build_insight(
                        insight_id=f"rks_{table}_{measure}",
                        insight_type="Risk",
                        severity="low",
                        title=f"{tdesc or table}: Stagnation — {measure} flat for {len(values)} periods",
                        description=f"{measure} in {tdesc or table} has been flat at ~{_fmt_currency(mean_val)} with {cv:.1f}% coefficient of variation over {len(values)} periods.",
                        metric=f"{measure} ({tdesc or table})",
                        metric_value=nums[-1],
                        magnitude=f"CV: {cv:.1f}%",
                        confidence=confidence,
                        affected_period=period_label,
                        tags=[table, measure, "risk", "stagnation"],
                        observations=[
                            f"{measure} average: {_fmt_currency(mean_val)} over {len(values)} periods.",
                            f"Coefficient of variation: {cv:.1f}% (very stable).",
                        ],
                        support_metrics=[f"CV: {cv:.1f}%", f"Mean: {_fmt_currency(mean_val)}"],
                        sample_size=len(values),
                        impact_value=0,
                        impact_direction="neutral",
                        impact_explanation=f"Flat {measure} may indicate market saturation or lack of growth initiatives.",
                        next_question=f"What factors could break the stagnation in {measure}?",
                        next_dims=dims,
                        viz_type="line",
                        viz_data=viz_data,
                        source_tables=[table],
                        source_columns=[date_col, measure],
                    ))

        return insights

    # ── Correlations ──────────────────────────────────────────────────────

    def _detect_correlations(self):
        """Detect correlations between numeric measures across tables."""
        insights = []
        fact_tables = [t for t in self.intel.tables if self.intel.is_fact_table(t)]

        for i, t1 in enumerate(fact_tables):
            for t2 in fact_tables[i+1:]:
                m1 = self.intel.find_best_measure(t1)
                m2 = self.intel.find_best_measure(t2)
                dt1 = self.intel.find_best_datetime(t1)
                dt2 = self.intel.find_best_datetime(t2)
                if not m1 or not m2 or not dt1 or not dt2:
                    continue

                # Find join path
                join_path = self.intel.find_join_path(t1, t2)
                if not join_path:
                    continue

                join_clause = self.intel.build_join_clause(join_path)
                join_on = join_path[-1]  # last join step
                sql = f"""
                    SELECT date_trunc('month', {_safe_name(t1)}.{_safe_name(dt1)}) AS period,
                           SUM({_safe_name(t1)}.{_safe_name(m1)}) AS v1,
                           SUM({_safe_name(t2)}.{_safe_name(m2)}) AS v2
                    FROM {_safe_name(t1)}
                    {join_clause}
                    WHERE {_safe_name(t1)}.{_safe_name(dt1)} IS NOT NULL
                    GROUP BY period
                    ORDER BY period
                    LIMIT 24
                """
                _, rows = _run_sql(self.conn, sql, limit=24)
                if len(rows) < 6:
                    continue

                v1 = [_safe_float(r["v1"]) for r in rows if _safe_float(r["v1"]) is not None and _safe_float(r["v2"]) is not None]
                v2 = [_safe_float(r["v2"]) for r in rows if _safe_float(r["v1"]) is not None and _safe_float(r["v2"]) is not None]
                periods = [str(r["period"])[:7] for r in rows if _safe_float(r["v1"]) is not None and _safe_float(r["v2"]) is not None]

                if len(v1) < 6:
                    continue

                n = len(v1)
                mean1 = statistics.mean(v1)
                mean2 = statistics.mean(v2)
                std1 = statistics.stdev(v1)
                std2 = statistics.stdev(v2)
                if std1 == 0 or std2 == 0:
                    continue

                corr = sum((a - mean1) * (b - mean2) for a, b in zip(v1, v2)) / ((n - 1) * std1 * std2)
                if abs(corr) > 0.6:
                    confidence = min(90, max(35, int(abs(corr) * 100)))
                    direction = "positive" if corr > 0 else "negative"
                    strength = "strong" if abs(corr) > 0.8 else "moderate"
                    tdesc1 = self.intel.tables[t1].get("description", t1)
                    tdesc2 = self.intel.tables[t2].get("description", t2)
                    viz_data = [{"period": periods[i], "table1": v1[i], "table2": v2[i]} for i in range(len(v1))]

                    insights.append(self._build_insight(
                        insight_id=f"corr_{t1}_{t2}",
                        insight_type="Correlation",
                        severity="medium",
                        title=f"{strength.title()} {direction} correlation between {tdesc1} and {tdesc2} (r={corr:.2f})",
                        description=f"There is a {strength} {direction} correlation (r={corr:.2f}) between {tdesc1} and {tdesc2} over {n} common periods.",
                        metric=f"{tdesc1} vs {tdesc2}",
                        magnitude=f"r={corr:.2f}",
                        confidence=confidence,
                        affected_period=f"{periods[0]} to {periods[-1]}",
                        tags=[t1, t2, "correlation", direction],
                        observations=[
                            f"Pearson r={corr:.2f} ({strength} {direction}). Based on {n} paired observations.",
                            f"Note: Correlation does not imply causation.",
                        ],
                        support_metrics=[f"r={corr:.2f}", f"n={n}"],
                        sample_size=n,
                        impact_value=0,
                        impact_direction="neutral",
                        impact_explanation=f"The {strength} correlation may indicate shared underlying drivers. This does not imply causation.",
                        next_question=f"What common factors drive the relationship between {tdesc1} and {tdesc2}?",
                        next_dims=[t1, t2],
                        viz_type="scatter",
                        viz_data=viz_data,
                        source_tables=[t1, t2],
                        source_columns=[dt1, dt2],
                    ))

        return insights

    # ── Helpers ───────────────────────────────────────────────────────────

    def _period_label(self, later, earlier):
        l = later.strftime('%b %Y') if hasattr(later, 'strftime') else str(later)[:7]
        e = earlier.strftime('%b %Y') if hasattr(earlier, 'strftime') else str(earlier)[:7]
        return f"{e} to {l}"

    def _compute_confidence(self, change_pct, sample_size, current, previous):
        mag_score = min(40, abs(change_pct) * 2)
        sample_score = min(30, sample_size * 3)
        consistency_score = 20 if abs(change_pct) > 10 else 10
        baseline_score = 10 if previous != 0 else 0
        return min(95, max(25, int(mag_score + sample_score + consistency_score + baseline_score)))

    def _compute_severity(self, magnitude, confidence, value):
        score = (magnitude / 10) * 0.4 + (confidence / 100) * 0.6
        if score > 6:
            return "high"
        if score > 3:
            return "medium"
        return "low"

    def _build_insight(self, **kw):
        """Build a standardized insight dict."""
        now = datetime.now().isoformat()
        return {
            "id": kw.get("insight_id", f"ins_{now}"),
            "type": kw.get("insight_type", "Trend"),
            "severity": kw.get("severity", "low"),
            "title": kw.get("title", ""),
            "description": kw.get("description", ""),
            "metric": kw.get("metric", ""),
            "metricValue": kw.get("metric_value"),
            "previousValue": kw.get("previous_value"),
            "magnitude": kw.get("magnitude", ""),
            "confidence": kw.get("confidence", 50),
            "detectedAt": now,
            "affectedPeriod": kw.get("affected_period", ""),
            "tags": kw.get("tags", []),
            "evidence": {
                "observations": kw.get("observations", []),
                "supportingMetrics": kw.get("support_metrics", []),
                "sampleSize": kw.get("sample_size"),
                "baseline": kw.get("baseline"),
                "currentValue": kw.get("current_value"),
                "changePercent": round(kw.get("change_pct", 0), 1) if kw.get("change_pct") else None,
            },
            "businessImpact": {
                "value": kw.get("impact_value"),
                "direction": kw.get("impact_direction", "neutral"),
                "explanation": kw.get("impact_explanation", ""),
            },
            "recommendedNextAnalysis": {
                "question": kw.get("next_question", ""),
                "metric": kw.get("metric", ""),
                "dimensions": kw.get("next_dims", []),
            },
            "visualization": {
                "type": kw.get("viz_type", "bar"),
                "data": kw.get("viz_data", []),
            },
            "source": {
                "tables": kw.get("source_tables", []),
                "columns": kw.get("source_columns", []),
            },
        }

    def _deduplicate(self, insights):
        seen = set()
        unique = []
        for ins in insights:
            key = (ins["type"], ins.get("metric", ""), ins.get("affectedPeriod", ""))
            if key not in seen:
                seen.add(key)
                unique.append(ins)
        return unique

    def _rank(self, insights):
        def score(ins):
            sev_map = {"high": 3, "medium": 2, "low": 1}
            sev = sev_map.get(ins.get("severity", "low"), 1)
            conf = ins.get("confidence", 50) / 100
            mag = abs(ins.get("metricValue") or 0)
            return sev * conf * (1 + math.log1p(mag))
        return sorted(insights, key=score, reverse=True)


# ── API Endpoints ─────────────────────────────────────────────────────────

class SaveInsightRequest(BaseModel):
    insight_id: str
    title: str
    insight_type: str
    severity: str
    metric: str = ""
    insight_payload: dict = {}


class AskInsightRequest(BaseModel):
    question: str = ""
    insight_id: str = ""


@router.get("/api/insights")
def get_insights(request: Request, user: dict = Depends(require_writable)):
    """Generate real insights from the connected database."""
    import json as _json
    session = get_session(user["user_id"])
    schema_path = session.get("schema_path")
    if not schema_path or not schema_path.exists():
        raise HTTPException(status_code=400, detail="No database connected. Please connect first.")
    mapping = _json.loads(schema_path.read_text(encoding="utf-8"))
    tables = mapping.get("tables", {})
    if not tables:
        raise HTTPException(status_code=400, detail="No tables found. Please extract schema first.")

    from core.secret_box import decrypt as _decrypt_secret
    db_config = dict(session.get("db") or {})
    db_type = session.get("db_type", "postgresql")
    if not db_config or session.get("source_type") != "relational":
        raise HTTPException(status_code=400, detail="Insights require a connected relational database.")
    if db_config.get("password"):
        try:
            db_config["password"] = _decrypt_secret(db_config["password"])
        except Exception:
            pass

    if db_type == "mysql":
        try:
            import pymysql
            conn = pymysql.connect(
                host=db_config.get("host", "localhost"),
                port=int(db_config.get("port", 3306)),
                user=db_config.get("user"),
                password=db_config.get("password"),
                database=db_config.get("db"),
                charset="utf8mb4",
                connect_timeout=10,
            )
        except Exception:
            raise HTTPException(status_code=500, detail="Could not connect to database.")
    else:
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=db_config.get("host", "localhost"),
                port=int(db_config.get("port", 5432)),
                dbname=db_config.get("db"),
                user=db_config.get("user"),
                password=db_config.get("password"),
                options=f"-c search_path={db_config.get('db_schema', 'public')}",
                connect_timeout=10,
            )
        except Exception:
            raise HTTPException(status_code=500, detail="Could not connect to database.")

    try:
        engine = InsightsEngine(conn, mapping)
        insights = engine.generate_all_insights(max_insights=20)
        return {"ok": True, "insights": insights, "count": len(insights)}
    except Exception as e:
        return {"ok": True, "insights": [], "count": 0, "note": str(e)}
    finally:
        try:
            conn.close()
        except Exception:
            pass


@router.get("/api/insights/saved")
def get_saved_insights(request: Request, user: dict = Depends(require_writable)):
    """Return saved/bookmarked insights for this user."""
    session = get_session(user["user_id"])
    saved = session.get("saved_insights", [])
    return {"ok": True, "saved": saved}


@router.post("/api/insights/save")
def save_insight(req: SaveInsightRequest, request: Request, user: dict = Depends(require_writable)):
    """Bookmark/save an insight."""
    session = get_session(user["user_id"])
    saved = session.get("saved_insights", [])
    if any(s.get("insight_id") == req.insight_id for s in saved):
        return {"ok": True, "saved": saved}
    saved.append({
        "insight_id": req.insight_id,
        "title": req.title,
        "type": req.insight_type,
        "severity": req.severity,
        "metric": req.metric,
        "created_at": datetime.now().isoformat(),
        "insight_payload": req.insight_payload,
    })
    session["saved_insights"] = saved
    save_session(user["user_id"], session)
    return {"ok": True, "saved": saved}


@router.delete("/api/insights/save/{insight_id}")
def unsave_insight(insight_id: str, request: Request, user: dict = Depends(require_writable)):
    """Remove bookmark from an insight."""
    session = get_session(user["user_id"])
    saved = session.get("saved_insights", [])
    saved = [s for s in saved if s.get("insight_id") != insight_id]
    session["saved_insights"] = saved
    save_session(user["user_id"], session)
    return {"ok": True, "saved": saved}


@router.post("/api/insights/{insight_id}/ask")
def ask_about_insight(insight_id: str, req: AskInsightRequest, request: Request, user: dict = Depends(require_writable)):
    """Analyze a specific insight further using the GoalAgent."""
    import json as _json
    from pathlib import Path
    from core.config import get_session
    from core.secret_box import decrypt as _decrypt_secret

    session = get_session(user["user_id"])
    schema_path = session.get("schema_path")
    if not schema_path or not Path(str(schema_path)).exists():
        raise HTTPException(status_code=400, detail="No database connected.")

    mapping = _json.loads(Path(str(schema_path)).read_text(encoding="utf-8"))
    db_config = dict(session.get("db") or {})
    if not db_config:
        raise HTTPException(status_code=400, detail="No database configuration found.")
    if db_config.get("password"):
        try:
            db_config["password"] = _decrypt_secret(db_config["password"])
        except Exception:
            pass

    db_type = session.get("db_type", "postgresql")
    dialect = "postgresql" if "postgres" in db_type else "mysql" if "mysql" in db_type else "sqlite"
    db_uri = session.get("db_uri", "")
    provider = session.get("provider")

    # Generate insights to find the specific one
    from sqlalchemy import create_engine, text
    try:
        engine = create_engine(db_uri)
        with engine.connect() as conn:
            ins_engine = InsightsEngine(conn, mapping, llm=None)
            all_insights = ins_engine.generate_all_insights(max_insights=20)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate insights: {str(e)}")

    # Find the target insight
    target = None
    for ins in all_insights:
        if ins.get("id") == insight_id:
            target = ins
            break

    if not target:
        raise HTTPException(status_code=404, detail="Insight not found.")

    # Build a contextual question from the insight
    question = req.question or ""
    if not question:
        title = target.get("title", "")
        metric = target.get("metric", "")
        insight_type = target.get("type", "")
        description = target.get("description", "")
        question = f"Provide a detailed analysis of: {title}. {description}"

    # Run through GoalAgent
    try:
        from goal_agent.agent import GoalAgent
        import time

        output_dir = Path("artifacts/processed_data") / f"user_{user['user_id']}"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"insight_analysis_{int(time.time())}.json"

        agent = GoalAgent(
            schema_json_path=str(schema_path),
            db_uri=db_uri,
            provider=provider,
            dialect=dialect,
        )
        result = agent.process_goal(question, output_path=str(output_path))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

    return {
        "ok": True,
        "insight_id": insight_id,
        "question": question,
        "result": result,
    }
