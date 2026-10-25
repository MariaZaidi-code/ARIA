import { Brush } from "recharts";
import type { BrushProps } from "recharts";

/** A shared, clearly-grabbable range control for every Recharts chart. */
export function ChartBrush(props: BrushProps) {
  // Plain screen-reader label: Recharts' default reads "Min value:
  // undefined, Max value: undefined" when data points have no `name`.
  const { className = "", height = 30, travellerWidth = 18,
    ariaLabel = "Chart range: drag the handles to zoom in", ...rest } = props;
  return (
    <Brush
      {...rest}
      ariaLabel={ariaLabel}
      className={`aria-chart-brush ${className}`.trim()}
      height={height}
      travellerWidth={travellerWidth}
      fill="transparent"
      stroke="var(--border)"
      traveller={({ x, y, width, height: handleHeight }) => {
        const bodyHeight = Math.min(22, Math.max(18, handleHeight - 8));
        const bodyY = y + (handleHeight - bodyHeight) / 2;
        const center = x + width / 2;
        const gripY = y + handleHeight / 2;
        return (
          <g>
            <rect
              x={x}
              y={bodyY}
              width={width}
              height={bodyHeight}
              rx={bodyHeight / 2}
              fill="var(--background)"
              stroke="var(--primary)"
              strokeWidth={1.5}
            />
            <path
              d={`M ${center - 3} ${gripY - 3} v 6 M ${center} ${gripY - 3} v 6 M ${center + 3} ${gripY - 3} v 6`}
              fill="none"
              stroke="var(--primary)"
              strokeWidth={1.25}
              strokeLinecap="round"
              opacity={0.85}
            />
          </g>
        );
      }}
    />
  );
}
