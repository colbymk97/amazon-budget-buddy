import { useMemo } from "react";
import { Area, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatMoney } from "../../api";
import { CATEGORICAL_COLORS, CHART_CHROME, colorForRetailer } from "../../lib/chartTheme";
import type { MonthlySpend } from "../../types";

type Metric = "net_amount_cents" | "gross_order_cents";

export function SpendTrendChart({
  months,
  retailers,
  metric = "net_amount_cents",
  height = 280,
}: {
  months: MonthlySpend[];
  retailers: string[];
  metric?: Metric;
  height?: number;
}) {
  const data = useMemo(
    () =>
      months.map((m) => {
        const row: Record<string, number | string> = { month: m.month };
        for (const retailer of retailers) {
          const value = m.by_retailer[retailer]?.[metric] ?? 0;
          row[retailer] = Math.abs(value) / 100;
        }
        return row;
      }),
    [months, retailers, metric]
  );

  const singleSeries = retailers.length <= 1;
  const tooltipStyle = {
    background: CHART_CHROME.surface,
    border: `1px solid ${CHART_CHROME.grid}`,
    borderRadius: 8,
    color: CHART_CHROME.ink,
  };

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 16, left: 8, bottom: 0 }}>
        <CartesianGrid stroke={CHART_CHROME.grid} vertical={false} />
        <XAxis
          dataKey="month"
          tick={{ fill: CHART_CHROME.inkMuted, fontSize: 12 }}
          axisLine={{ stroke: CHART_CHROME.grid }}
          tickLine={false}
        />
        <YAxis
          tick={{ fill: CHART_CHROME.inkMuted, fontSize: 12 }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v: number) => `$${v.toLocaleString()}`}
          width={64}
        />
        <Tooltip
          contentStyle={tooltipStyle}
          labelStyle={{ color: CHART_CHROME.inkSoft }}
          formatter={(value: unknown) => formatMoney(Number(value) * 100)}
        />
        {!singleSeries ? <Legend wrapperStyle={{ color: CHART_CHROME.inkSoft, fontSize: 12 }} /> : null}
        {retailers.map((retailer) => {
          const color = singleSeries ? CATEGORICAL_COLORS[0] : colorForRetailer(retailer);
          return singleSeries ? (
            <Area
              key={retailer}
              type="monotone"
              dataKey={retailer}
              name={retailer}
              stroke={color}
              strokeWidth={2}
              fill={color}
              fillOpacity={0.1}
              dot={{ r: 4, fill: color, stroke: CHART_CHROME.surface, strokeWidth: 2 }}
              activeDot={{ r: 5 }}
            />
          ) : (
            <Line
              key={retailer}
              type="monotone"
              dataKey={retailer}
              name={retailer}
              stroke={color}
              strokeWidth={2}
              dot={{ r: 4, fill: color, stroke: CHART_CHROME.surface, strokeWidth: 2 }}
              activeDot={{ r: 5 }}
            />
          );
        })}
      </ComposedChart>
    </ResponsiveContainer>
  );
}
