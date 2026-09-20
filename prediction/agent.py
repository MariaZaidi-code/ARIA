"""PredictionAgent - ARIA predictive analysis.

Turns a Goal-Agent `processed_data.json` payload into a structured forecast.

Forecastability contract (dynamic, never hardcoded per dataset):

- ``50`` is a *confidence threshold*, not a hard block. With ``n_obs >= 50``
  the full pipeline runs (model selection + train-earlier/validate-later
  time-series validation). With fewer observations but a mathematically
  meaningful series (valid date column, temporal variation, numeric target,
  non-constant) ARIA still produces a PRELIMINARY forecast marked
  ``reliability: limited`` with an explicit message, ``n_obs``, confidence
  interval and a recommendation to connect more history.
- Genuinely unforecastable data (no date field, no temporal variation, no
  numeric target, constant series) returns ``ok: False`` with a reason, the
  missing field and a suggestion — never a fabricated forecast.
- Pre-forecast validation + preparation (time column, target, frequency from
  the median timestamp delta, missing dates/values, duplicate timestamps
  aggregated by sum, constant/near-constant check, outlier flags for info
  only, irregular intervals, aggregation level) is exposed as the
  ``preparation`` object — every value derived from the data.
- Model selection compares naive / seasonal-naive / moving-average /
  exponential smoothing / Holt-Winters / ARIMA-SARIMA families (statsmodels
  when installed, skipped gracefully otherwise; ML only with enough data)
  via trailing-holdout + walk-forward scoring and picks the best by
  MAPE with MAE/RMSE tiebreak. ``model_selected`` + ``candidates[]`` carry
  the scores.
- Metrics (MAE, RMSE, MAPE, sMAPE, WAPE, bias) when history allows;
  ``reliability: high|moderate|limited`` + concise ``accuracy`` summary up
  front, full detail behind the expandable ``details`` object.
- Horizon is auto-suggested from frequency and ``n_obs``
  (``min(cap, max(floor, n_obs // 4))`` style logic), user-overridable via
  the ``horizon`` request parameter.
- Drivers are derived from the dataset (trend slope, seasonality strength,
  top categorical contributor, volatility) — each with ``name``,
  ``evidence`` and ``metric_value``.

Legacy response keys are preserved; new keys are additive only. Every error
path returns structured graceful JSON (``core/errors.py::sanitize_error``),
never a stack trace.
"""

import logging
import math

import numpy as np
import pandas as pd

from .evaluate import (
    accuracy_from_mape,
    bias as _bias,
    mae as _mae,
    mape as _mape,
    reliability_label as _legacy_reliability_label,
    rmse as _rmse,
    smape as _smape,
    wape as _wape,
)
from . import models as M
from . import selection as _selection

try:  # graceful when used outside the full ARIA stack
    from core.errors import sanitize_error as _sanitize_error
except Exception:  # pragma: no cover
    def _sanitize_error(exc, max_len=300):
        try:
            return str(exc)[:max_len]
        except Exception:
            return "An error occurred."

log = logging.getLogger("aria.prediction")

# 50 is a confidence threshold, NOT a hard block: below it forecasts are
# still produced when mathematically meaningful, but marked preliminary.
CONFIDENCE_THRESHOLD_N = 50
PRELIMINARY_MESSAGE = (
    "ARIA can generate a preliminary forecast from the available data, "
    "but fewer than 50 observations are available. "
    "Forecast confidence is limited."
)
PRELIMINARY_RECOMMENDATION = (
    "Connect more historical data to improve forecast reliability."
)
ANALYZE_SUGGESTION = "Ask ARIA to analyze this dataset instead."


def _numeric_cols(df):
    """Numeric columns, including numeric-looking string columns (e.g. a Postgres
    NUMERIC value serialised as text by JSON)."""
    cols = []
    for c in df.columns:
        if pd.api.types.is_numeric_dtype(df[c]):
            cols.append(c)
            continue
        sample = df[c].dropna()
        if not len(sample):
            continue
        coerced = pd.to_numeric(sample, errors="coerce")
        if coerced.notna().sum() / len(sample) >= 0.8:
            cols.append(c)
    return cols


def _datetime_cols(df):
    cols = []
    for c in df.columns:
        if pd.api.types.is_numeric_dtype(df[c]):
            continue
        try:
            parsed = pd.to_datetime(df[c], errors="coerce")
            if parsed.notna().sum() >= max(2, int(len(df) * 0.8)):
                cols.append(c)
        except Exception:
            continue
    return cols


def _infer_period(dates):
    """Choose the aggregation period from the median gap between dates."""
    series = pd.Series(pd.to_datetime(pd.unique(pd.to_datetime(dates, errors="coerce")))).sort_values().dropna()
    gaps = series.diff().dropna().dt.days
    if len(gaps) == 0:
        return "D"
    med = float(gaps.median())
    if med <= 2:
        return "D"
    if med <= 10:
        return "W"
    return "MS"


_PERIOD_NAMES = {"D": "daily", "W": "weekly", "MS": "monthly"}

# Column names that indicate a natural period/ordinal axis for forecasting even
# without a datetime column (e.g. "sales by year", "churn per month").
_PERIOD_KEYWORDS = {
    "period", "periods", "year", "years", "yr", "month", "months",
    "day", "days", "week", "weeks", "quarter", "quarters", "qtr",
    "seq", "sequence", "index", "idx", "order", "rank", "time",
    "date", "dates", "timestamp", "datetime",
}


def _suggest_horizon(frequency_label, n_obs):
    """Dynamic horizon default from frequency + history length.

    ``min(cap, max(floor, n_obs // 4))`` logic — caps/floors are method
    bounds, the actual value is computed per dataset. A caller-supplied
    ``horizon`` always overrides this.
    """
    n = max(int(n_obs or 0), 0)
    if frequency_label == "daily":
        return min(30, max(7, n // 4))
    if frequency_label == "weekly":
        return min(12, max(4, n // 4))
    if frequency_label == "monthly":
        return min(12, max(3, n // 4))
    return min(12, max(3, n // 4))


def _reliability_level(accuracy, preliminary=False):
    """high|moderate|limited from backtested accuracy.

    Preliminary (sub-threshold history) forecasts are always ``limited`` —
    the ``forecast_stage`` + message say they are preliminary.
    """
    if preliminary:
        return "limited"
    if accuracy is None:
        return "limited"
    if accuracy >= 85:
        return "high"
    if accuracy >= 70:
        return "moderate"
    return "limited"


def _lag_autocorr(values, lag):
    v = np.asarray(values, dtype=float)
    n = len(v)
    if n <= lag or lag < 1:
        return 0.0
    a, b = v[:-lag], v[lag:]
    if float(np.std(a)) < 1e-12 or float(np.std(b)) < 1e-12:
        return 0.0
    try:
        return float(np.corrcoef(a, b)[0, 1])
    except Exception:
        return 0.0


def _forecast_labels(last_label, steps, period_code):
    if period_code is None:
        return [f"t+{k}" for k in range(1, steps + 1)]
    last_ts = pd.to_datetime(last_label)
    step = {
        "D": pd.Timedelta(days=1),
        "W": pd.Timedelta(weeks=1),
        "MS": pd.DateOffset(months=1),
    }[period_code]
    return [(last_ts + k * step).strftime("%Y-%m-%d") for k in range(1, steps + 1)]


def _series_varies(vals) -> bool:
    """True when consecutive points actually move (not a flat level line).

    Relative bar: range must exceed 1e-6 of the series scale, so genuine
    micro-variation counts but float dust does not.
    """
    try:
        v = np.asarray(vals, dtype=float)
        v = v[np.isfinite(v)]
        if len(v) < 2:
            return False
        scale = max(1.0, abs(float(np.mean(np.abs(v)))))
        return bool(float(np.max(v) - np.min(v)) > 1e-6 * scale)
    except Exception:
        return False


def _forecast_varies(vals) -> bool:
    """Alias kept at the forecast call-site: same varying-series rule."""
    return _series_varies(vals)


def _history_varies(vals) -> bool:
    return _series_varies(vals)


def _substitute_flat_winner(values, season_period, model_spec, sel_meta,
                            sel_metrics, steps):
    """Swap a flat-projecting winner for a varying scored alternate.

    When the winner's own refit projects a constant level on genuinely
    varying history, prefer the best-ranked validated candidate whose refit
    actually varies (still a backtested model; the swap is disclosed in the
    returned selection statement) — never invented wiggle. No varying
    scored alternate -> inputs returned unchanged with note None.

    Returns (model_spec, sel_meta, sel_metrics, sub_note).
    """
    from .evaluate import _make as _mk
    try:
        _probe = max(1, min(int(steps or 1), len(values)))
        if season_period:
            _probe = max(_probe, min(int(season_period), len(values)))
        _winner = getattr(model_spec, "name", "?") \
            if isinstance(model_spec, type) else "ensemble"
        try:
            _wpts = np.asarray(
                _mk(model_spec, season_period).fit(values).predict(
                    _probe), dtype=float) \
                if isinstance(model_spec, type) else \
                np.asarray(model_spec.predict(_probe), dtype=float)
        except Exception:
            log.debug("flat-line guard: winner probe refit failed",
                      exc_info=True)
            return model_spec, sel_meta, sel_metrics, None
        if _wpts is None or _forecast_varies(_wpts) \
                or not _history_varies(values):
            return model_spec, sel_meta, sel_metrics, None
        for _row in (sel_meta.get("ranking") or [])[1:]:
            _alt_name = _row.get("model")
            if not _alt_name or _alt_name == _winner:
                continue
            if (_row.get("mae") is None and _row.get("mape") is None):
                continue  # unscored candidates cannot substitute
            _alt = next(
                (c for c in M.CANDIDATES if c.name == _alt_name),
                None)
            if _alt is None or _alt is model_spec:
                continue
            if len(values) < getattr(_alt, "min_points", 0):
                continue
            if (getattr(_alt, "needs_real_period", False)
                    and not season_period):
                continue
            try:
                _alt_pts = np.asarray(
                    _mk(_alt, season_period).fit(values).predict(
                        _probe), dtype=float)
            except Exception:
                continue
            if _forecast_varies(_alt_pts):
                _new_metrics = {
                    "mae": _row.get("mae"),
                    "rmse": _row.get("rmse"),
                    "mape": _row.get("mape"),
                }
                _new_meta = dict(sel_meta)
                _new_meta["winner"] = _alt_name
                _note = (
                    f"{_winner} validated best but projected a "
                    f"flat level line on varying history; using "
                    f"{_alt_name} (holdout MAPE {_row.get('mape')}%) "
                    f"so the projection carries the observed dynamics."
                )
                _new_meta["statement"] = (
                    str(_new_meta.get("statement") or "")
                    + " " + _note).strip()
                return _alt, _new_meta, _new_metrics, _note
        log.debug("flat-line guard: winner %s flat on varying history but "
                  "no varying scored alternate found", _winner)
        return model_spec, sel_meta, sel_metrics, None
    except Exception:
        log.debug("flat-line guard failed", exc_info=True)
        return model_spec, sel_meta, sel_metrics, None


class PredictionAgent:
    def __init__(self, horizon=6, min_points=5, valid_threshold=70.0,
                 confidence_threshold=50, auto_horizon=True):
        self.horizon = int(horizon)
        self.min_points = int(min_points)
        # Minimum out-of-sample accuracy (%) for a forecast to be presented as
        # valid. Below this the prediction is kept in the payload for transparency
        # but flagged invalid so the story, prescriptions and UI do not use it.
        self.valid_threshold = float(valid_threshold)
        # Confidence threshold (NOT a hard block): below it forecasts are
        # marked preliminary/limited but still produced when meaningful.
        self.confidence_threshold = int(confidence_threshold)
        # When True (default) a forecast() call without an explicit horizon
        # uses the dynamically suggested horizon; otherwise self.horizon.
        self.auto_horizon = bool(auto_horizon)

    def forecast(self, processed_data, numeric_col=None, datetime_col=None, horizon=None):
        try:
            return self._forecast_inner(processed_data, numeric_col, datetime_col, horizon)
        except Exception as exc:
            log.warning("Forecast failed gracefully: %s", exc)
            out = self._empty(_sanitize_error(exc), "insufficient_data")
            out.update({"ok": False, "missing_field": "internal",
                        "suggestion": ANALYZE_SUGGESTION})
            return out

    def _forecast_inner(self, processed_data, numeric_col=None, datetime_col=None, horizon=None):
        rows = (processed_data or {}).get("data") or []
        if not rows:
            out = self._empty("empty dataset", "no_data")
            out.update({"ok": False, "missing_field": "data",
                        "suggestion": ANALYZE_SUGGESTION})
            return out

        df = pd.DataFrame(rows)
        numeric_cols = _numeric_cols(df)
        if not numeric_cols:
            out = self._empty("no numeric columns found", "no_data")
            out.update({"ok": False, "missing_field": "numeric_target",
                        "suggestion": ANALYZE_SUGGESTION})
            return out
        # Coerce numeric-looking string columns to real numbers so downstream
        # aggregation and models compute correctly.
        for c in numeric_cols:
            if c in df.columns and not pd.api.types.is_numeric_dtype(df[c]):
                try:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
                except Exception:
                    pass

        if numeric_col is None:
            goal = str(processed_data.get("user_goal") or "").lower()
            # Identifier-like columns (ids/keys/codes) are never forecast targets:
            # they are synthetic keys, not measures.
            def _is_id_like(name):
                try:
                    from core.identifiers import is_id_like as _canon
                    return bool(_canon(name))
                except Exception:
                    low = str(name or "").lower().strip()
                    return low.endswith("_id") or low.endswith("_key") or low in ("id", "key", "code", "codeid")

            measure_cols = [c for c in numeric_cols if not _is_id_like(c)]
            if not measure_cols:
                # Only identifier-like numeric columns exist (e.g. an aggregate
                # that only selected keys). Forecasting a synthetic key is
                # meaningless, so degrade gracefully instead of guessing.
                out = self._empty(
                    "no measure column to forecast (only id/key/code columns are numeric)",
                    "not_applicable",
                )
                out.update({"ok": False, "missing_field": "numeric_target",
                            "suggestion": ANALYZE_SUGGESTION})
                return out
            numeric_col = next(
                (c for c in measure_cols if c.lower() in goal or goal in c.lower()),
                measure_cols[-1],  # measures usually come after id columns in SELECT order
            )
        if numeric_col not in df.columns:
            out = self._empty(f"numeric column '{numeric_col}' not found", "no_data")
            out.update({"ok": False, "missing_field": "numeric_target",
                        "suggestion": ANALYZE_SUGGESTION})
            return out

        if datetime_col is None:
            dcols = _datetime_cols(df)
            datetime_col = dcols[0] if dcols else None

        if datetime_col is not None:
            built = self._build_series(df, numeric_col, datetime_col)
            if built is not None:
                values, labels, period_code, diagnostics = built
                if len(values) >= 2:
                    season_period = self._season_period(period_code, len(values))
                    return self._build(
                        values, labels, numeric_col,
                        _PERIOD_NAMES[period_code], period_code, horizon,
                        season_period, diagnostics,
                        n_extra_features=self._extra_feature_count(
                            df, numeric_col, exclude=[datetime_col]),
                        raw_df=df, time_col=datetime_col,
                    )

        # No usable time column: a forecast is only meaningful when the rows carry
        # a natural period/ordinal axis (year, month, period, ...). Plain category
        # aggregates (e.g. "count by city") have no time dimension to forecast over
        # and are handled gracefully instead of being forced through a fake axis.
        seq_col = self._sequence_col(df)
        if seq_col is None:
            out = self._empty(
                "no time dimension - a forecast is not applicable to this aggregate "
                f"question (forecast target '{numeric_col}').",
                "not_applicable",
            )
            out.update({"ok": False, "missing_field": "date",
                        "suggestion": ANALYZE_SUGGESTION,
                        "target": numeric_col, "column": numeric_col})
            return out

        seq = df[seq_col]
        raw_vals = pd.to_numeric(df[numeric_col], errors="coerce").astype(float)
        n_missing_vals = int(raw_vals.isna().sum())
        values = raw_vals.values
        mask = pd.notna(values)
        values = values[mask]
        seq = np.asarray(seq)[mask]
        if len(values) < 2:
            out = self._empty(f"not enough numeric values in '{numeric_col}'", "insufficient_data")
            out.update({"ok": False, "missing_field": "history",
                        "suggestion": ANALYZE_SUGGESTION,
                        "target": numeric_col, "column": numeric_col})
            return out
        labels = [str(v) for v in seq.tolist()]
        seq_dups = int(pd.Series(labels).duplicated().sum())
        diagnostics = {
            "time_grain": "sequence",
            "duplicate_timestamps_merged": seq_dups,
            "missing_periods": 0,
            "missing_periods_interpolated": 0,
            "missing_periods_filled": 0,
            "median_delta_days": None,
            "frequency": "sequence",
            "n_obs_raw": int(len(df)),
            "n_obs": int(len(values)),
            "missing_values": n_missing_vals,
            "aggregation_level": "ordinal_sequence_no_date_aggregation",
            "aggregation_method": "none",
            "irregular_intervals": False,
        }
        return self._build(values, labels, numeric_col, "sequence", None, horizon, None,
                           diagnostics=diagnostics,
                           n_extra_features=self._extra_feature_count(
                               df, numeric_col, exclude=[seq_col]),
                           raw_df=df, time_col=seq_col)

    def _sequence_col(self, df):
        """Find a column that provides a natural period/ordinal axis."""
        for c in df.columns:
            low = str(c).lower().strip()
            if low in _PERIOD_KEYWORDS or low.startswith(("year", "month", "week", "qtr", "quarter", "period")):
                if df[c].notna().sum() >= 2 and df[c].nunique() >= 2:
                    return c
        return None

    def _season_period(self, period_code, n):
        """Season length for seasonal models, when enough history exists."""
        if period_code == "D" and n >= 21:
            return 7
        if period_code == "MS" and n >= 24:
            return 12
        if period_code == "W" and n >= 12:
            return 4
        return None

    def _extra_feature_count(self, df, target_col, exclude=None):
        """Other usable columns alongside the target (feature-richness hint).

        The time axis itself is not a predictive feature and is excluded."""
        skip = {target_col} | set(exclude or [])
        return sum(1 for c in df.columns if c not in skip and df[c].notna().sum() >= 2)

    def _build_series(self, df, numeric_col, datetime_col):
        """Data-first series construction.

        detect datetime column -> target/measure -> aggregate to time grain
        -> clean missing/duplicates -> history check.

        Returns (values, labels, period_code, diagnostics) or None when the
        datetime column cannot serve as a time axis. Labels are backend
        timestamps ("%Y-%m-%d"); the frontend must plot these verbatim and
        never invent dates.
        """
        ts = pd.to_datetime(df[datetime_col], errors="coerce")
        try:
            if getattr(ts.dt, "tz", None) is not None:
                ts = ts.dt.tz_convert("UTC").dt.tz_localize(None)
        except Exception:
            try:
                ts = ts.dt.tz_localize(None)
            except Exception:
                pass
        n_bad_time = int(ts.isna().sum())
        mask = ts.notna()
        if mask.sum() < 3:
            return None
        temp = df[mask].copy()
        temp["_ts"] = ts[mask]
        # Chronological order is enforced here; everything downstream
        # (grain inference, aggregation, labels) sees sorted time.
        temp = temp.sort_values("_ts").reset_index(drop=True)
        # Target/measure: coerce once; non-numeric rows cannot be aggregated.
        temp["_val"] = pd.to_numeric(temp[numeric_col], errors="coerce")
        n_bad_value = int(temp["_val"].isna().sum())
        temp = temp[temp["_val"].notna()]
        if len(temp) < 2:
            return None
        # Raw gap profile (before aggregation) drives the irregular-interval
        # flag and the frequency evidence — all derived from observed data.
        uniq_ts = pd.Series(pd.unique(temp["_ts"])).sort_values()
        raw_gaps = uniq_ts.diff().dropna().dt.total_seconds() / 86400.0
        median_delta = float(raw_gaps.median()) if len(raw_gaps) else 0.0
        if len(raw_gaps) >= 3:
            gap_mean = float(raw_gaps.mean())
            gap_std = float(raw_gaps.std())
            gap_cv = (gap_std / gap_mean) if gap_mean > 1e-12 else 0.0
            irregular = bool(gap_cv > 0.75 or float(raw_gaps.max()) > 3 * median_delta)
        else:
            irregular = False
        # Time grain from the observed (unique) timestamps.
        period_code = _infer_period(temp["_ts"])
        # Aggregate to the grain; duplicate timestamps are merged by sum and
        # counted so the cleaning is auditable, never silent.
        n_rows = len(temp)
        n_unique = int(temp["_ts"].nunique())
        grouped = temp.groupby(pd.Grouper(key="_ts", freq=period_code))["_val"].sum()
        duplicates_merged = max(0, n_rows - n_unique)
        # Clean missing periods: compare the observed grain periods against
        # the full min..max range. (pandas >= 2/3 zero-fills unobserved
        # groupby bins, so gaps are detected from the timestamps, not NaNs.)
        # Interior gaps of <= 2 consecutive periods are linearly interpolated;
        # edges / long outages keep the aggregation zero and every gap is
        # reported in diagnostics — never silently invented.
        _PER_FREQ = {"MS": "M", "D": "D", "W": "W"}
        try:
            observed = set(temp["_ts"].dt.to_period(_PER_FREQ[period_code]))
            full = pd.period_range(temp["_ts"].min(), temp["_ts"].max(),
                                   freq=_PER_FREQ[period_code])
            missing = [p for p in full if p not in observed]
        except Exception:
            missing = []
        missing_periods = len(missing)
        grouped = grouped.reindex(
            pd.date_range(grouped.index.min(), grouped.index.max(), freq=period_code))
        grouped = grouped.fillna(0.0).astype(float)
        n_interpolated = 0
        if missing_periods:
            asfreq_idx = pd.period_range(grouped.index.min(), grouped.index.max(),
                                         freq=_PER_FREQ[period_code])
            vals = grouped.copy()
            n = min(len(asfreq_idx), len(vals))
            if n < len(asfreq_idx) or n < len(vals):
                log.warning("Period index length mismatch: asfreq=%d, vals=%d; using %d",
                            len(asfreq_idx), len(vals), n)
            vals.index = asfreq_idx[:n]
            # runs of consecutive missing periods
            run, prev = [], None
            runs = []
            for p in missing:
                if prev is not None and p.ordinal == prev.ordinal + 1:
                    run.append(p)
                else:
                    if run:
                        runs.append(run)
                    run = [p]
                prev = p
            if run:
                runs.append(run)
            for run in runs:
                if len(run) > 2:
                    continue
                lo_pos = max(0, full.get_loc(run[0]) - 1)
                hi_pos = min(len(full) - 1, full.get_loc(run[-1]) + 1)
                if full[lo_pos] in observed and full[hi_pos] in observed:
                    lo_v = float(vals.loc[full[lo_pos]])
                    hi_v = float(vals.loc[full[hi_pos]])
                    span = hi_pos - lo_pos
                    for k, p in enumerate(run, start=1):
                        vals.loc[p] = lo_v + (hi_v - lo_v) * (k / span)
                        n_interpolated += 1
            vals.index = grouped.index
            grouped = vals.astype(float)
        values = np.asarray(grouped.values, dtype=float)
        labels = [pd.Timestamp(t).strftime("%Y-%m-%d") for t in grouped.index]
        # Post-aggregation quality flags — info for validation, never silent.
        std = float(np.std(values)) if len(values) else 0.0
        mean = float(np.mean(values)) if len(values) else 0.0
        constant = bool(len(values) >= 2 and (std < 1e-9 or pd.Series(values).nunique() <= 1))
        cv = (std / abs(mean)) if abs(mean) > 1e-12 else (float("inf") if std > 0 else 0.0)
        near_constant = bool(not constant and len(values) >= 3 and math.isfinite(cv) and cv < 1e-3)
        outliers = self._outlier_count(values)
        if n_rows > len(values):
            agg_level = f"transaction_rows_aggregated_to_{period_code}_by_sum"
        elif duplicates_merged:
            agg_level = f"duplicate_timestamps_aggregated_to_{period_code}_by_sum"
        else:
            agg_level = f"already_at_{period_code}_grain"
        diagnostics = {
            "time_grain": period_code,
            "duplicate_timestamps_merged": duplicates_merged,
            "missing_periods": missing_periods,
            "missing_periods_interpolated": n_interpolated,
            "missing_periods_filled": missing_periods,
            "median_delta_days": round(median_delta, 2),
            "frequency": _PERIOD_NAMES[period_code],
            "n_obs_raw": int(n_rows),
            "n_obs": int(len(values)),
            "missing_values": int(n_bad_time + n_bad_value),
            "outlier_count": outliers,
            "outlier_method": "IQR+zscore union, info only - values kept",
            "irregular_intervals": bool(irregular),
            "aggregation_level": agg_level,
            "aggregation_method": "sum",
            "constant": constant,
            "near_constant": near_constant,
            "temporal_variation": bool(not constant and len(values) >= 2),
        }
        return values, labels, period_code, diagnostics

    @staticmethod
    def _outlier_count(values):
        """IQR + z-score union count. Info only — values are never removed."""
        v = np.asarray(values, dtype=float)
        if len(v) < 4:
            return 0
        try:
            q1, q3 = float(np.percentile(v, 25)), float(np.percentile(v, 75))
            iqr = q3 - q1
            lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            iqr_mask = (v < lo) | (v > hi)
        except Exception:
            iqr_mask = np.zeros(len(v), dtype=bool)
        try:
            std = float(np.std(v))
            mean = float(np.mean(v))
            z_mask = np.abs(v - mean) > 3 * std if std > 1e-12 else np.zeros(len(v), dtype=bool)
        except Exception:
            z_mask = np.zeros(len(v), dtype=bool)
        return int(np.sum(iqr_mask | z_mask))

    def _holdout_extended(self, values, model_cls, season_period):
        """Extended metrics on a train-earlier/validate-later trailing holdout.

        Fits on values[:-h], scores against values[-h:] — never a random
        split. Returns {mae, rmse, mape, smape, wape, bias, holdout_points}
        with None where unmeasurable.
        """
        from .evaluate import holdout_backtest as _hb
        n = len(values)
        h = min(3, max(1, n // 4)) if n > 1 else 0
        if h < 1 or (n - h) < 3:
            return {"mae": None, "rmse": None, "mape": None, "smape": None,
                    "wape": None, "bias": None, "holdout_points": 0}
        base = _hb(model_cls, values, season_period, h)
        try:
            from .evaluate import _make as _mk
            pred = np.asarray(_mk(model_cls, season_period).fit(values[:-h]).predict(h),
                              dtype=float)
            actual = np.asarray(values[-h:], dtype=float)
            return {
                "mae": base.get("mae"),
                "rmse": base.get("rmse"),
                "mape": base.get("mape"),
                "smape": _smape(actual, pred),
                "wape": _wape(actual, pred),
                "bias": round(_bias(actual, pred), 4) if _bias(actual, pred) is not None else None,
                "holdout_points": int(h),
            }
        except Exception:
            return {"mae": base.get("mae"), "rmse": base.get("rmse"),
                    "mape": base.get("mape"), "smape": None, "wape": None,
                    "bias": None, "holdout_points": int(h)}

    def _compute_drivers(self, values, season_period, target_col, period_name,
                         raw_df=None, time_col=None):
        """Dataset-derived drivers: trend, seasonality, volatility, top
        categorical contributor. Every string embeds measured numbers —
        nothing generic or hardcoded."""
        v = np.asarray(values, dtype=float)
        n = len(v)
        drivers = []
        mean = float(np.mean(v)) if n else 0.0
        std = float(np.std(v)) if n else 0.0
        # 1. trend slope (least squares, per-period).
        try:
            slope = float(np.polyfit(np.arange(n, dtype=float), v, 1)[0]) if n >= 2 else 0.0
        except Exception:
            slope = 0.0
        direction = "upward" if slope > 0 else ("downward" if slope < 0 else "flat")
        drivers.append({
            "name": f"trend in {target_col}",
            "evidence": (
                f"least-squares slope {slope:+.4f} per {period_name} period "
                f"over {n} periods (direction: {direction})"
            ),
            "metric_value": round(slope, 4),
        })
        # 2. seasonality strength at the seasonal lag (or best scanned lag).
        if season_period and season_period >= 2:
            ac = _lag_autocorr(v, season_period)
            drivers.append({
                "name": f"seasonality (lag {season_period})",
                "evidence": (
                    f"autocorrelation {ac:.3f} at seasonal lag {season_period} "
                    f"for this {period_name} series of {n} periods"
                ),
                "metric_value": round(ac, 3),
            })
        else:
            best_lag, best_ac = 0, 0.0
            for lag in range(2, min(12, n // 2) + 1):
                ac = _lag_autocorr(v, lag)
                if abs(ac) > abs(best_ac):
                    best_lag, best_ac = lag, ac
            drivers.append({
                "name": f"seasonality (lag {best_lag})" if best_lag else "seasonality (no lag scannable)",
                "evidence": (
                    f"strongest autocorrelation {best_ac:.3f} at lag {best_lag} "
                    f"scanning lags 2..{min(12, n // 2)} over {n} periods"
                    if best_lag else
                    f"only {n} periods — too short to scan seasonal lags"
                ),
                "metric_value": round(best_ac, 3),
            })
        # 3. volatility (coefficient of variation).
        cv = (std / abs(mean)) if abs(mean) > 1e-12 else (float("inf") if std > 0 else 0.0)
        drivers.append({
            "name": f"volatility of {target_col}",
            "evidence": (
                f"coefficient of variation "
                f"{cv:.3f}" if math.isfinite(cv) else "coefficient of variation undefined (zero mean)"
            ) + f" (std {std:.2f} vs mean {mean:.2f}) over {n} periods",
            "metric_value": round(cv, 3) if math.isfinite(cv) else None,
        })
        # 4. top categorical contributor (contribution analysis on raw rows).
        contrib = self._top_contributor(raw_df, target_col, exclude=time_col)
        if contrib:
            col, val, share, top_sum, total, ngroups = contrib
            drivers.append({
                "name": f"top contributor: {col}",
                "evidence": (
                    f"{col}='{val}' contributes {share:.1f}% of total {target_col} "
                    f"({top_sum:,.2f} of {total:,.2f} across {ngroups} groups)"
                ),
                "metric_value": round(share, 2),
            })
        return drivers

    @staticmethod
    def _top_contributor(raw_df, target_col, exclude=None):
        """Highest-share category by summed target across usable cat columns."""
        if raw_df is None or target_col not in raw_df.columns:
            return None
        try:
            totals = pd.to_numeric(raw_df[target_col], errors="coerce")
            grand = float(totals.sum())
            if not math.isfinite(grand) or abs(grand) < 1e-12:
                return None
            best = None
            for c in raw_df.columns:
                if c == target_col or (exclude is not None and c == exclude):
                    continue
                s = raw_df[c]
                if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_object_dtype(s):
                    continue
                try:
                    nunique = int(s.nunique(dropna=True))
                except Exception:
                    continue
                if nunique < 2 or nunique > 30:
                    continue
                try:
                    grouped = totals.groupby(s.fillna("∅")).sum()
                    if grouped.empty:
                        continue
                    top_val = grouped.abs().idxmax()
                    top_sum = float(grouped.loc[top_val])
                    share = abs(top_sum) / abs(grand) * 100.0
                    if best is None or share > best[2]:
                        best = (str(c), str(top_val), share, top_sum, grand, nunique)
                except Exception:
                    continue
            return best
        except Exception:
            return None

    def _build(self, values, labels, col, period_name, period_code, horizon,
               season_period=None, diagnostics=None, n_extra_features=0,
               raw_df=None, time_col=None):
        conf_thresh = int(getattr(self, "confidence_threshold", None)
                          or CONFIDENCE_THRESHOLD_N)
        values = np.asarray(values, dtype=float)
        frequency_label = _PERIOD_NAMES.get(period_code, "sequence") \
            if period_code else "sequence"
        n_obs = int(len(values))
        horizon_suggested = _suggest_horizon(frequency_label, n_obs)
        auto_h = bool(getattr(self, "auto_horizon", True))
        if horizon is not None:
            horizon_eff = horizon
        elif auto_h:
            horizon_eff = horizon_suggested
        else:
            horizon_eff = getattr(self, "horizon", horizon_suggested)
        try:
            horizon_eff = int(horizon_eff)
        except Exception:
            horizon_eff = horizon_suggested
        horizon_eff = max(1, horizon_eff)
        # Validation (Phases 10/14): sufficient unique history + meaningful
        # variance. Either failure returns an explanation with NO forecast
        # points — never a fake-looking projection from inadequate data.
        if len(values) < self.min_points:
            return self._insufficient(
                col, period_name, period_code, horizon_eff,
                f"only {len(values)} history period(s) found — "
                f"at least {self.min_points} are needed for a reliable forecast. "
                "Try a different number with more history, or connect a "
                "longer series and try again.",
                diagnostics=diagnostics,
                missing_field="history",
            )
        if float(np.std(values)) < 1e-9 or pd.Series(values).nunique() <= 1:
            out = self._insufficient(
                col, period_name, period_code, horizon_eff,
                f"'{col}' shows no meaningful variation over "
                f"{len(values)} periods (constant history) — there is no "
                "trend to project. Try a different number with changing "
                "values instead.",
                diagnostics=diagnostics,
                missing_field="temporal_variation",
            )
            out.update({"ok": False, "suggestion": ANALYZE_SUGGESTION})
            return out
        preliminary = bool(n_obs < conf_thresh)
        # Intelligent model selection: diagnose the series, shortlist by rule
        # (little history -> naive/seasonal-naive; seasonality -> seasonal;
        # trend+seasonality -> ETS/SARIMA; feature-rich -> ML note;
        # irregular -> unreliable), backtest the shortlist on a trailing
        # holdout and pick the winner on holdout error.
        model_spec, sel_metrics, sel_meta = _selection.select_intelligent(
            values, season_period,
            n_extra_features=n_extra_features,
            min_points=self.min_points,
        )
        validated = model_spec is not None
        if not validated:
            # Defensive: select_intelligent only declines when n < min_points
            # (handled above), so reaching here means no candidate could be
            # scored — explain instead of emitting an unvalidated projection.
            return self._insufficient(
                col, period_name, period_code, horizon_eff,
                "no candidate model could be validated on this history "
                "(too little data for holdout/walk-forward scoring), "
                "so no forecast was generated.",
                diagnostics=diagnostics,
                missing_field="history",
            )
        # Flat-line guard (pre-refit probe): a validated winner that
        # projects a constant level on genuinely varying history draws a
        # flat line users read as "no forecast". A post-refit safety net
        # below re-checks the FINAL points (probe and final fit can differ).
        _probe_steps = max(1, min(int(horizon_eff or 1), len(values)))
        if season_period:
            _probe_steps = max(_probe_steps,
                               min(int(season_period), len(values)))
        model_spec, sel_meta, sel_metrics, _sub_note = \
            _substitute_flat_winner(values, season_period, model_spec,
                                    sel_meta, sel_metrics, _probe_steps)
        from .evaluate import one_step_ahead_mae as _oos_mae
        from .evaluate import one_step_ahead_mape as _oos_mape
        oos_mape = _oos_mape(model_spec, values, season_period) \
            if isinstance(model_spec, type) else sel_meta.get("walk_forward_mape")
        oos_mae = _oos_mae(model_spec, values, season_period) \
            if isinstance(model_spec, type) else sel_meta.get("walk_forward_mae")

        # An EnsembleModel arrives already fitted, but its .fit(values) is also a
        # no-op that records the series for fitted()/residuals(); classes are
        # fitted here on the full series — via the same constructor the
        # backtests used, so a seasonal winner keeps its real period
        # (seasonal_naive refit with a default period 7 on monthly data, or
        # auto_ets refit without its period, silently mis-forecast).
        if isinstance(model_spec, type):
            from .evaluate import _make as _mk_final
            model = _mk_final(model_spec, season_period).fit(values)
        else:
            model = model_spec.fit(values)
        # Horizon is capped at history length (extrapolating further is not
        # supported). The cap is now disclosed via horizon_capped/details
        # instead of silent min() — numeric behavior unchanged.
        try:
            _req_steps = max(1, int(horizon_eff))
        except (TypeError, ValueError):
            _req_steps = 1
        steps = max(1, min(_req_steps, len(values)))
        horizon_capped = _req_steps > len(values)
        horizon_note = (
            f"Requested horizon {_req_steps} exceeds history length {len(values)}; "
            f"capped to {steps}."
            if horizon_capped else None
        )
        points = np.asarray(model.predict(steps), dtype=float)

        try:
            resid = model.residuals(values)
        except Exception:
            try:
                resid = np.asarray(values, dtype=float) - np.asarray(model.fitted(), dtype=float)
            except Exception:
                resid = np.zeros_like(values, dtype=float)
        std = float(np.std(resid)) if len(resid) > 1 else 0.0
        # Prefer the honest out-of-sample error for the confidence band width;
        # fall back to in-sample std only when no walk-forward could be run.
        if oos_mae:
            # MAE ~= 0.8 * sigma for a Gaussian; rescale to an approximate sigma.
            sigma = oos_mae / 0.8
        else:
            sigma = std
        # Post-refit safety net: the pre-refit probe can disagree with the
        # final fit (refit nondeterminism, ensemble path). If the FINAL
        # points are flat on varying history, substitute and rebuild
        # points/bands from the alternate — a flat line is never shipped
        # silently.
        if (not _forecast_varies(points) and _history_varies(values)):
            _post_spec, _post_meta, _post_met, _post_note = \
                _substitute_flat_winner(values, season_period, model_spec,
                                        sel_meta, sel_metrics, steps)
            if _post_note is not None and _post_spec is not model_spec:
                try:
                    from .evaluate import _make as _mk_post
                    model_spec, sel_meta, sel_metrics = \
                        _post_spec, _post_meta, _post_met
                    model = _mk_post(model_spec, season_period).fit(values) \
                        if isinstance(model_spec, type) \
                        else model_spec.fit(values)
                    points = np.asarray(model.predict(steps), dtype=float)
                    try:
                        resid = model.residuals(values)
                    except Exception:
                        try:
                            resid = np.asarray(values, dtype=float) - np.asarray(
                                model.fitted(), dtype=float)
                        except Exception:
                            resid = np.zeros_like(values, dtype=float)
                    std = float(np.std(resid)) if len(resid) > 1 else 0.0
                    if isinstance(model_spec, type):
                        oos_mape = _oos_mape(model_spec, values, season_period)
                        oos_mae = _oos_mae(model_spec, values, season_period)
                    else:
                        oos_mape = sel_meta.get("walk_forward_mape")
                        oos_mae = sel_meta.get("walk_forward_mae")
                    sigma = oos_mae / 0.8 if oos_mae else std
                    _sub_note = ((_sub_note + " ") if _sub_note else "") + _post_note
                    log.info("flat-line guard (post-refit): %s", _post_note)
                except Exception:
                    log.debug("flat-line guard post-refit rebuild failed",
                              exc_info=True)
        last_actual = float(values[-1])
        accuracy = accuracy_from_mape(oos_mape)
        projected_pct = (
            round(float(points[-1] / last_actual * 100.0 - 100.0), 2) if last_actual else 0.0
        )

        # Validation gate: only forecasts whose backtested accuracy clears the
        # threshold are "valid". Poor/unknown accuracy -> not usable downstream.
        # Zero-actual periods are excluded from MAPE (undefined at 0), so a
        # sparse series must also show enough evaluated origins — otherwise a
        # 95% accuracy on 2 of 10 periods would mislead.
        from prediction.evaluate import walk_forward_coverage as _coverage
        cov = _coverage(values, season_period)
        zero_frac = (cov["zero_skipped"] / cov["origins"]) if cov["origins"] else 0.0
        enough_coverage = cov["evaluated"] >= 3 and zero_frac < 0.5
        valid = accuracy is not None and accuracy >= self.valid_threshold and enough_coverage
        if not validated:
            reason = "insufficient history for walk-forward validation"
        elif accuracy is None:
            reason = "accuracy could not be measured (no walk-forward errors)"
        elif not enough_coverage:
            reason = (
                f"accuracy {accuracy}% covers only {cov['evaluated']}/{cov['origins']} "
                f"periods ({cov['zero_skipped']} zero-demand periods excluded from MAPE)"
            )
        else:
            reason = (
                f"backtest accuracy {accuracy}% {'meets' if valid else 'below'} "
                f"the {self.valid_threshold}% threshold"
            )
        forecast_stage = "preliminary" if preliminary else "full"
        reliability = _reliability_level(accuracy, preliminary=preliminary)
        validation = {
            "method": "expanding-window walk-forward (one-step-ahead, out-of-sample)",
            "metric": "MAPE",
            "accuracy_pct": accuracy,
            "threshold_pct": self.valid_threshold,
            "passed": valid,
            "reason": reason,
            "walk_forward_origins": cov["origins"],
            "walk_forward_evaluated": cov["evaluated"],
            "zero_actuals_skipped": cov["zero_skipped"],
            "n_obs": n_obs,
            "confidence_threshold": conf_thresh,
            "forecast_stage": forecast_stage,
        }

        # Data contract (Phase 12 / §16): backend timestamps only. `historical`
        # carries date->value pairs, `forecast` carries future timestamps with
        # a confidence interval. `confidence_interval` mirrors the 80/95% bands
        # per forecast date and `timestamps` lists every backend date in plot
        # order (history then forecast). The frontend plots these verbatim and
        # never invents dates; legacy `history`/`points` stay for compatibility.
        model_name = getattr(model, "name", "none")
        frequency = period_code or "sequence"
        fwd_labels = _forecast_labels(labels[-1], steps, period_code)
        forecast_points = [
            {
                "label": fwd_labels[i],
                "value": round(float(points[i]), 2),
                "forecast": round(float(points[i]), 2),
                "lower80": round(float(points[i] - 1.28 * sigma), 2),
                "upper80": round(float(points[i] + 1.28 * sigma), 2),
                "lower95": round(float(points[i] - 1.96 * sigma), 2),
                "upper95": round(float(points[i] + 1.96 * sigma), 2),
            }
            for i in range(steps)
        ]
        # Trailing actuals so the UI can draw one continuous
        # history + projection chart (last 24 periods max).
        history = [
            {"label": lab, "actual": round(float(v), 2)}
            for lab, v in zip(labels[-24:], values[-24:])
        ]
        historical = [
            {"date": lab, "value": round(float(v), 2)}
            for lab, v in zip(labels[-24:], values[-24:])
        ]
        forecast_series = [
            {
                "date": fwd_labels[i],
                "value": round(float(points[i]), 2),
                "lower": round(float(points[i] - 1.96 * sigma), 2),
                "upper": round(float(points[i] + 1.96 * sigma), 2),
            }
            for i in range(steps)
        ]
        # Metrics: holdout winner scores first, honest walk-forward as the
        # fallback so mae/rmse/mape are always populated when measurable.
        rep_mape = sel_metrics.get("mape")
        if rep_mape is None and oos_mape is not None:
            rep_mape = round(oos_mape, 2)
        rep_mae = sel_metrics.get("mae")
        if rep_mae is None and oos_mae is not None:
            rep_mae = round(oos_mae, 2)
        rep_rmse = sel_metrics.get("rmse")
        if rep_rmse is None:
            try:
                rep_rmse = round(_rmse(values, np.asarray(model.fitted(), dtype=float)), 2)
            except Exception:
                rep_rmse = None
        # Extended holdout metrics (train-earlier/validate-later split).
        extended = self._holdout_extended(values, model_spec if isinstance(model_spec, type)
                                          else model_spec.__class__, season_period)
        metrics = {"mae": rep_mae, "rmse": rep_rmse, "mape": rep_mape}
        selection_statement = sel_meta.get("statement") or (
            f"Selected {model_name} { _selection.HOLDOUT_STATEMENT}."
            if validated else "insufficient history for holdout validation")
        model_notes = dict(sel_meta)
        model_notes.setdefault("sigma", round(float(sigma), 2))
        if diagnostics:
            model_notes.setdefault("series_diagnostics", diagnostics)

        # Perfect-fit honesty: a zero-width interval is observed error, not
        # certainty. The bands stay as computed; the note tells every
        # consumer (story, prescriptions, UI) to treat it as uncertain.
        try:
            perfect_fit = bool(valid) and float(sigma) <= 1e-12
        except (TypeError, ValueError):
            perfect_fit = False
        uncertainty_note = (
            "Very low observed error — treat as uncertain, not guaranteed"
            if perfect_fit else None
        )
        # Documented flat line: no validated candidate varies on this
        # history, so the level projection stands — the note (surfaced in
        # the UI) says why instead of leaving a flat line unexplained.
        try:
            if (uncertainty_note is None and _sub_note is None
                    and not _forecast_varies(points)
                    and _history_varies(values)):
                uncertainty_note = (
                    "Validated models project a steady level on this history — "
                    "the flat line is the backtested signal, not missing data."
                )
        except Exception:
            pass

        # Candidates with scores (best first) + the winner — all derived
        # from the same trailing-holdout backtest, never invented.
        ranking = sel_meta.get("ranking") or []
        candidates = [
            {"model": r.get("model"), "mae": r.get("mae"), "rmse": r.get("rmse"),
             "mape": r.get("mape"), "holdout_points": r.get("holdout_points")}
            for r in ranking
        ]
        model_selected = sel_meta.get("winner") or model_name
        drivers = self._compute_drivers(values, season_period, col, period_name,
                                        raw_df=raw_df, time_col=time_col)
        preparation = {
            "time_column": time_col,
            "target_column": col,
            "frequency": frequency_label,
            "frequency_detection": {
                "method": "median timestamp delta",
                "median_delta_days": (diagnostics or {}).get("median_delta_days"),
                "time_grain": (diagnostics or {}).get("time_grain"),
            },
            "n_obs_raw": (diagnostics or {}).get("n_obs_raw", n_obs),
            "n_obs": n_obs,
            "missing_periods": (diagnostics or {}).get("missing_periods", 0),
            "missing_periods_filled": (diagnostics or {}).get("missing_periods_filled", 0),
            "missing_values": (diagnostics or {}).get("missing_values", 0),
            "duplicate_timestamps_merged": (diagnostics or {}).get(
                "duplicate_timestamps_merged", 0),
            "duplicate_aggregation": (diagnostics or {}).get("aggregation_method", "sum"),
            "constant": (diagnostics or {}).get("constant", False),
            "near_constant": (diagnostics or {}).get("near_constant", False),
            "temporal_variation": (diagnostics or {}).get("temporal_variation", True),
            "outlier_count": (diagnostics or {}).get("outlier_count", 0),
            "outlier_method": (diagnostics or {}).get(
                "outlier_method", "IQR+zscore union, info only - values kept"),
            "irregular_intervals": (diagnostics or {}).get("irregular_intervals", False),
            "aggregation_level": (diagnostics or {}).get("aggregation_level"),
        }
        if accuracy is not None:
            accuracy_summary = (
                f"Backtested accuracy {accuracy}% (walk-forward MAPE "
                f"{round(oos_mape, 2) if oos_mape is not None else 'n/a'}%) over "
                f"{cov['evaluated']}/{cov['origins']} origins — {reliability} reliability."
                + (" Preliminary: fewer than "
                   f"{conf_thresh} observations (n={n_obs})." if preliminary else "")
            )
        else:
            accuracy_summary = (
                "Accuracy could not be measured on this history — "
                "treat the projection as directional."
            )
        details = {
            "metrics_extended": {
                "mae": rep_mae, "rmse": rep_rmse, "mape": rep_mape,
                "smape": extended.get("smape"), "wape": extended.get("wape"),
                "bias": extended.get("bias"),
                "holdout_points": extended.get("holdout_points"),
            },
            "coverage": cov,
            "selection": {k: v for k, v in sel_meta.items()},
            "diagnostics": dict(diagnostics or {}),
            "horizon": {"requested": horizon, "suggested": horizon_suggested,
                        "used": steps, "frequency": frequency_label,
                        "capped": horizon_capped, "note": horizon_note},
            "confidence_threshold": conf_thresh,
            "sigma": round(float(sigma), 2),
            "legacy_reliability_label": _legacy_reliability_label(accuracy),
        }

        return {
            "ok": True,
            "column": col,
            "period": period_name,
            "horizon": steps,
            "horizon_suggested": horizon_suggested,
            "horizon_capped": horizon_capped,
            "horizon_note": horizon_note,
            "forecast_stage": forecast_stage,
            "method": model_name,
            "model_selected": model_selected,
            "candidates": candidates,
            "accuracy_pct": accuracy,
            "accuracy": {"pct": accuracy, "summary": accuracy_summary},
            "mape_pct": round(oos_mape, 2) if oos_mape is not None else None,
            "reliability": reliability,
            "valid": valid,
            "reason": None if valid else reason,
            "message": PRELIMINARY_MESSAGE if preliminary else None,
            "recommendation": PRELIMINARY_RECOMMENDATION if preliminary else None,
            "n_obs": n_obs,
            "uncertainty_note": uncertainty_note,
            "interval_method": "pointwise",
            "validation": validation,
            "preparation": preparation,
            "model_notes": model_notes,
            "last_actual": {"label": labels[-1], "value": round(last_actual, 2)},
            "projected_pct_change": projected_pct,
            "points": forecast_points,
            "history": history,
            "drivers": drivers,
            "details": details,
            # ---- data contract (Phase 12 / §16) ----
            "historical": historical,
            "forecast": forecast_series,
            "confidence_interval": [
                {
                    "date": fwd_labels[i],
                    "lower80": round(float(points[i] - 1.28 * sigma), 2),
                    "upper80": round(float(points[i] + 1.28 * sigma), 2),
                    "lower95": round(float(points[i] - 1.96 * sigma), 2),
                    "upper95": round(float(points[i] + 1.96 * sigma), 2),
                }
                for i in range(steps)
            ],
            "timestamps": [h["date"] for h in historical]
            + [f["date"] for f in forecast_series],
            "frequency": frequency,
            "target": col,
            "model": model_name,
            "metrics": metrics,
            "selection_statement": selection_statement,
        }

    def _insufficient(self, col, period_name, period_code, horizon, reason,
                      diagnostics=None, missing_field="history"):
        """Contract-safe insufficient-history response: explanation, no
        forecast points — never a fake-looking projection."""
        out = self._empty(reason, "insufficient_data")
        out.update({
            "column": col,
            "period": period_name,
            "horizon": int(horizon or 0),
            "frequency": period_code or "sequence",
            "target": col,
            "selection_statement": None,
            "ok": False,
            "missing_field": missing_field,
            "suggestion": ANALYZE_SUGGESTION,
        })
        if diagnostics:
            out["model_notes"] = {"series_diagnostics": diagnostics}
            out["preparation"] = {
                "time_column": None,
                "target_column": col,
                "frequency": _PERIOD_NAMES.get(period_code, "sequence")
                if period_code else "sequence",
                "n_obs": diagnostics.get("n_obs", 0),
                "n_obs_raw": diagnostics.get("n_obs_raw", 0),
                "missing_periods": diagnostics.get("missing_periods", 0),
                "missing_values": diagnostics.get("missing_values", 0),
                "duplicate_timestamps_merged": diagnostics.get(
                    "duplicate_timestamps_merged", 0),
                "constant": diagnostics.get("constant", False),
                "near_constant": diagnostics.get("near_constant", False),
                "temporal_variation": diagnostics.get("temporal_variation", False),
                "irregular_intervals": diagnostics.get("irregular_intervals", False),
                "aggregation_level": diagnostics.get("aggregation_level"),
            }
        return out

    def _empty(self, reason, reliability):
        return {
            "ok": False,
            "column": None, "period": None, "horizon": 0,
            "horizon_suggested": None,
            "forecast_stage": "none",
            "method": "none", "model_selected": None, "candidates": [],
            "accuracy_pct": None, "accuracy": {"pct": None, "summary": str(reason)},
            "mape_pct": None,
            "reliability": reliability, "reason": reason,
            "message": None, "recommendation": None,
            "missing_field": None, "suggestion": ANALYZE_SUGGESTION,
            "n_obs": 0,
            "points": [], "history": [],
            "drivers": [], "details": {},
            "valid": False,
            "uncertainty_note": None,
            "interval_method": None,
            "validation": {
                "method": None, "metric": "MAPE",
                "accuracy_pct": None, "threshold_pct": self.valid_threshold,
                "passed": False, "reason": reason,
            },
            "preparation": {
                "time_column": None, "target_column": None, "frequency": None,
                "n_obs": 0, "n_obs_raw": 0,
            },
            "last_actual": None, "projected_pct_change": None,
            "historical": [], "forecast": [], "confidence_interval": [],
            "timestamps": [], "frequency": None,
            "target": None, "model": "none",
            "metrics": {"mae": None, "rmse": None, "mape": None},
            "selection_statement": None,
            "model_notes": {},
        }

    def decision_scenario_support(self, decision: dict) -> dict:
        """PHASE 11 hook: honest forecast-backed scenario capability.

        What-If itself runs in the prescription engine (OLS lever model);
        the forecast agent only reports whether a time-series outlook can
        contextualize the decision. Never fabricates a prediction: returns
        {supported, reason} from the decision's own forecast payload.
        """
        d = decision if isinstance(decision, dict) else {}
        fc = d.get("forecast")
        if not isinstance(fc, dict) or not fc:
            return {"supported": False,
                    "reason": "No validated forecast attached to this decision."}
        pts = fc.get("points") or fc.get("forecast") or []
        if isinstance(pts, list) and len(pts) >= 2:
            return {"supported": True, "reason": None,
                    "horizon": len(pts)}
        return {"supported": False,
                "reason": "Attached forecast has no usable projection."}
