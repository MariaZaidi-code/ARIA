import { useMemo } from "react";
import { InsightChart, normalizeInsightViz } from "../charts";

export interface DocumentVisualization {
  type: string;
  title: string;
  x_key: string;
  x_label?: string;
  y_label?: string;
  series: { key: string; label: string; source_id?: string }[];
  data: Record<string, string | number>[];
  cross_document?: boolean;
  source_ids?: string[];
}

/**
 * Chart for an answer, built server-side only from cited table evidence
 * (`visualization` on the chat response). Rendered with the shared
 * InsightChart so tooltips, legend toggles and theming match other pages.
 */
export function DocumentAnswerChart({
  visualization,
  onViewSource,
}: {
  visualization: DocumentVisualization;
  onViewSource?: (sourceId: string) => void;
}) {
  const spec = useMemo(() => {
    const series = (visualization.series || []).map((item) => item.key).filter(Boolean);
    if (!series.length) return null;
    return normalizeInsightViz({
      type: visualization.type || "bar",
      x: visualization.x_key || "label",
      y: series[0],
      series: series.slice(1),
      title: visualization.title,
      data: visualization.data,
      interactive: true,
    });
  }, [visualization]);

  if (!spec || spec.data.length < 2) return null;
  const sources = visualization.source_ids?.filter(Boolean) || [];
  return (
    <figure className="doc-answer-chart" aria-label={`Chart: ${visualization.title}`}>
      <figcaption>
        <strong>{visualization.title}</strong>
        <span>{visualization.cross_document ? "Compared across cited documents" : "From cited table data"}</span>
      </figcaption>
      <InsightChart spec={spec} height={220} />
      {sources.length > 0 && onViewSource && (
        <div className="doc-answer-chart-sources">
          {sources.map((sourceId) => (
            <button key={sourceId} type="button" className="doc-link-button" onClick={() => onViewSource(sourceId)}>
              View cited data [{sourceId}]
            </button>
          ))}
        </div>
      )}
    </figure>
  );
}
