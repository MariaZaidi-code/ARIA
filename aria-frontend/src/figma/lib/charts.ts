// Shared categorical palette: muted professional tones (Tableau-style),
// never neon or purple. First color is the brand steel blue.
export const CATEGORY_COLORS = [
  "#2F6FAD", // steel blue
  "#2E9B6B", // green
  "#C98A1B", // bronze
  "#B85C4D", // terracotta
  "#5B7C99", // slate
  "#7A9E43", // olive
  "#A87C4F", // tan
  "#C65D3A", // rust
  "#4C9A9A", // teal gray
  "#8A8A8A", // gray
  "#3E5C76", // navy
  "#D9A441", // gold
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
