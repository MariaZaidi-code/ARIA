// Shared categorical palette: charts are colorful by category, never all-blue.
export const CATEGORY_COLORS = [
  "#4F46E5", // indigo
  "#059669", // emerald
  "#F59E0B", // amber
  "#EC4899", // pink
  "#06B6D4", // cyan
  "#8B5CF6", // violet
  "#EF4444", // red
  "#14B8A6", // teal
  "#F97316", // orange
  "#84CC16", // lime
  "#6366F1", // periwinkle
  "#D946EF", // fuchsia
];

export const colorFor = (index: number): string =>
  CATEGORY_COLORS[((index % CATEGORY_COLORS.length) + CATEGORY_COLORS.length) % CATEGORY_COLORS.length];

/** Stable color per category name so legends stay consistent across renders. */
export const colorForName = (name: string): string => {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  }
  return colorFor(hash);
};
