import React from "react";
import { CalendarDays } from "lucide-react";

export interface TimeRangeOption {
  key: string;
  label: string;
}

interface TimeRangeSelectorProps {
  options: TimeRangeOption[];
  value: string;
  onChange: (key: string) => void;
  className?: string;
}

export function TimeRangeSelector({ options, value, onChange, className = "" }: TimeRangeSelectorProps) {
  return (
    <div
      className={`inline-flex items-center gap-0.5 p-0.5 rounded-lg bg-muted/50 border border-border/60 ${className}`}
      role="radiogroup"
      aria-label="Time range"
    >
      <CalendarDays size={12} className="text-muted-foreground ml-1 mr-0.5 flex-shrink-0 pointer-events-none" />
      {options.map((opt) => {
        const active = opt.key === value;
        return (
          <button
            key={opt.key}
            role="radio"
            aria-checked={active}
            onClick={() => onChange(opt.key)}
            className={`relative px-2.5 py-1 text-[11px] font-medium rounded-md border transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 ${active
              ? "bg-card text-foreground border-border/70 shadow-sm"
              : "text-muted-foreground hover:text-foreground hover:bg-card/60 border-transparent"
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
