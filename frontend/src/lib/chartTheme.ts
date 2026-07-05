// Chart color tokens. Recharts needs literal hex values (it can't read CSS
// custom properties), so the handful of colors used here are duplicated from
// styles.css's :root rather than sharing a single source of truth.
//
// The 8-hue categorical set is the dataviz skill's validated dark-mode
// palette, re-validated with scripts/validate_palette.js against this app's
// actual panel surface (#111214): PASS on lightness band, chroma floor, and
// contrast; CVD separation sits in the 8-12 "floor" band at all 8 slots in
// use, which is why charts with 4+ series always carry direct labels here,
// not color alone. Hues are assigned in this fixed order — never cycled or
// reassigned when a filter changes which series are visible.
export const CATEGORICAL_COLORS = [
  "#3987e5", // blue
  "#199e70", // aqua
  "#c98500", // yellow
  "#008300", // green
  "#9085e9", // violet
  "#e66767", // red
  "#d55181", // magenta
  "#d95926", // orange
];

// Single-hue sequential ramp (blue), for magnitude-only contexts (e.g. a lone
// series trend line, or bars where color encodes rank rather than identity).
export const SEQUENTIAL_BLUE = "#4f8cff";

export const CHART_CHROME = {
  ink: "#e8e9eb", // matches --text
  inkSoft: "#9b9da4", // matches --text-secondary
  inkMuted: "#67696f", // matches --text-tertiary
  grid: "#232428", // matches --border
  gridStrong: "#34363b", // matches --border-strong
  danger: "#f0576c", // matches --danger
  surface: "#1a1b1e", // matches --bg-elevated, used for tooltip backgrounds
};

const retailerColorCache = new Map<string, string>();

// Assigns a stable categorical color per retailer name, first-seen order, so
// "amazon" (or any retailer) keeps the same color across every chart on the
// dashboard rather than being recolored whenever the visible set changes.
export function colorForRetailer(retailer: string): string {
  if (!retailerColorCache.has(retailer)) {
    const color = CATEGORICAL_COLORS[retailerColorCache.size % CATEGORICAL_COLORS.length];
    retailerColorCache.set(retailer, color);
  }
  return retailerColorCache.get(retailer)!;
}
