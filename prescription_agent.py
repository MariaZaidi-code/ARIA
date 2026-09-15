"""ARIA Prescription Agent
--------------------------
Role: Recommended Actions

Turns the Insight Agent's findings (KPIs, trends, anomalies, hypotheses) plus
the Prediction Agent's forecast into 3-5 concrete, prioritized next actions a
manager should take. Uses the configured LLM (local Mistral or cloud Groq) and
falls back to a template derived from the actual numbers if the LLM fails.

When DB context is provided (engine, dialect, intel, table, metric), delegates
to ``prescription_engine.analyze`` for evidence-backed deterministic prescriptions.

Output: {"actions": [str, ...], "source": "llm" | "template" | "engine"}
"""

import json
import logging
import re

from llm_provider import create_provider

logging.basicConfig(level=logging.INFO)


class PrescriptionAgent:
    def __init__(self, provider=None):
        self.llm = provider or create_provider()

    def prescribe(self, processed_data, kpis, trends, anomalies, hypotheses,
                  predictions=None, max_actions=5, *,
                  engine=None, dialect=None, intel=None, table=None, metric=None):
        """Return a dict with 'actions' (list of strings) and 'source'.

        When ``engine``, ``dialect``, ``intel``, ``table``, and ``metric`` are
        provided, the canonical ``prescription_engine.analyze`` path is used
        for evidence-backed deterministic prescriptions.  The legacy LLM and
        template paths are preserved for callers without DB context.
        """
        processed_data = processed_data or {}
        kpis = kpis or []
        trends = trends or []
        anomalies = anomalies or []
        hypotheses = hypotheses or []

        # ---- Deterministic engine path (§4 pipeline) ----
        if all(v is not None for v in (engine, dialect, intel, table, metric)):
            try:
                from prescription_engine.engine import analyze as _engine_analyze
                result = _engine_analyze(engine, dialect, intel, table, metric)
                if result.get("ok") and result.get("prescriptions"):
                    actions = []
                    for rx in result["prescriptions"][:max_actions]:
                        title = rx.get("title") or rx.get("summary", "")
                        if title:
                            actions.append(title)
                    if actions:
                        return {
                            "actions": actions,
                            "source": "engine",
                            "engine_status": result.get("status"),
                            "engine_driver": result.get("driver"),
                            "engine_story": result.get("story"),
                            "engine_summary": result.get("summary_plain"),
                            "impact_note": "Impact estimates derived from deterministic statistical analysis.",
                        }
                # Engine returned no_prescription or ok=False — fall through to LLM/template.
                logging.getLogger("aria.prescription").info(
                    "Engine returned no prescription (%s); falling back to LLM/template",
                    result.get("status", result.get("detail")),
                )
            except Exception as exc:
                logging.getLogger("aria.prescription").warning(
                    "Engine delegation failed (%s); falling back to LLM/template", exc)

        # ---- LLM path ----
        context = {
            "user_goal": processed_data.get("user_goal", "Unknown goal"),
            "row_count": processed_data.get("row_count", 0),
            "kpis": kpis[:6],
            "trends": trends[:3],
            "anomalies": anomalies[:5],
            "hypotheses": hypotheses[:4],
            "prediction": self._prediction_summary(predictions),
        }

        prompt = f"""
You are ARIA's Insight Agent. Recommend exactly {max_actions} concrete,
prioritized next actions for a non-technical manager. Tie each action to the
actual numbers in the context (KPIs, trends, anomalies, hypotheses, and the
forecast if one is present).

Context:
{json.dumps(context, indent=2, default=str)}

Rules:
- Output ONLY a numbered list, one action per line, no extra text.
- Each action must be specific enough to execute this week.
- If the forecast shows a strong projected change, include an action that
  prepares for it.
"""
        try:
            text = self.llm.chat(
                "story",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                num_predict=500,
            )
            if not (text or "").strip():
                logging.getLogger("aria.prescription").warning(
                    "Prescription LLM returned empty; using template actions")
                return {
                    "actions": self._template_actions(kpis, trends, anomalies, hypotheses,
                                                      predictions, max_actions),
                    "source": "template",
                    "status": "LLM_EMPTY",
                    "impact_note": "Impact could not be reliably estimated from the available data.",
                }
            actions = self._parse_actions(text, max_actions)
            if actions:
                return {
                    "actions": actions,
                    "source": "llm",
                    "status": "SUCCESS",
                    # Honesty guard (t.txt section 43): never invent financial impact.
                    "impact_note": "Impact could not be reliably estimated from the available data.",
                }
            logging.getLogger("aria.prescription").warning(
                "Prescription LLM returned unparseable prose; using template actions")
            return {
                "actions": self._template_actions(kpis, trends, anomalies, hypotheses,
                                                  predictions, max_actions),
                "source": "template",
                "status": "INVALID_LLM_RESPONSE",
                "impact_note": "Impact could not be reliably estimated from the available data.",
            }
        except Exception as exc:
            logging.getLogger("aria.prescription").exception("Prescription LLM failed; using template actions")

        return {
            "actions": self._template_actions(kpis, trends, anomalies, hypotheses,
                                              predictions, max_actions),
            "source": "template",
            "status": "LLM_UNAVAILABLE",
            # Honesty guard (t.txt section 43): never invent financial impact.
            "impact_note": "Impact could not be reliably estimated from the available data.",
        }

    def recommendation_for_validated_decision(self, decision: dict):
        """PHASE 10: validated Decision -> existing prescription engine.

        Delegates to prescription_engine.recommendation_for_decision (the
        single engine). Never returns title-as-recommendation, never an
        LLM-only action. Returns the supported text or None.
        """
        try:
            from prescription_engine.engine import recommendation_for_decision as _rfd
            return _rfd(decision if isinstance(decision, dict) else {})
        except Exception as exc:
            logging.getLogger("aria.prescription").debug(
                "recommendation_for_decision failed closed: %s", exc)
            return None

    @staticmethod
    def _prediction_summary(predictions):
        # Only an accuracy-validated forecast may influence prescriptions.
        if not predictions or not predictions.get("valid") or not predictions.get("points"):
            return None
        return {
            "column": predictions["column"],
            "period": predictions["period"],
            "horizon": predictions["horizon"],
            "method": predictions["method"],
            "accuracy_pct": predictions["accuracy_pct"],
            "projected_pct_change": predictions["projected_pct_change"],
            "last_actual": predictions["last_actual"],
            "points": predictions["points"][:4],
        }

    @staticmethod
    def _parse_actions(text, max_actions):
        actions = []
        for line in str(text).splitlines():
            line = line.strip().replace("*", "").strip()
            if not line:
                continue
            m = re.match(r"^\s*(?:\d+[\.\)]\s*[\.\)\:]?|[-*]\s*|\u2022\s*)\s*(.*)$", line)
            if m and m.group(1).strip():
                actions.append(m.group(1).strip())
            if len(actions) >= max_actions:
                break
        if actions:
            return actions[:max_actions]

        # The model ignored the list format and returned prose. Descriptive
        # sentences are not prescriptions — signal unparseable output so the
        # caller falls back to template actions instead of promoting prose.
        return []

    @staticmethod
    def _template_actions(kpis, trends, anomalies, hypotheses, predictions, max_actions):
        actions = []
        if hypotheses:
            actions.append(f"Validate the leading hypothesis: {hypotheses[0].get('hypothesis', 'N/A')}")
        if trends:
            t = trends[0]
            actions.append(
                f"Review the {t.get('direction', 'unknown')} trend in "
                f"{', '.join(t.get('columns', []))} "
                f"(change {t.get('pct_change', 'N/A')}%)."
            )
        if anomalies:
            a = anomalies[0]
            actions.append(
                f"Investigate the unusual {a.get('column', 'reading')} "
                f"(observed {a.get('value', 'N/A')}, well outside its usual range)."
            )
        if predictions and predictions.get("valid") and predictions.get("points"):
            period_word = predictions.get("period") or "periods"
            if period_word in ("sequence", "daily", "weekly", "monthly"):
                period_word = "periods"
            actions.append(
                f"Plan for the projected {predictions['projected_pct_change']}% change in "
                f"{predictions['column']} over the next {predictions['horizon']} {period_word} "
                f"(backtest accuracy {predictions['accuracy_pct']}% if shown)."
            )
        if kpis and not actions:
            valid = [k for k in kpis if isinstance(k, dict) and k.get("mean") is not None]
            if valid:
                top = max(valid, key=lambda k: k.get("mean", 0))
                actions.append(f"Keep monitoring {top.get('column', 'key metric')} (mean {top.get('mean')}).")
        if not actions:
            actions.append("Continue monitoring the key metrics; no urgent action is indicated.")
        return actions[:max_actions]