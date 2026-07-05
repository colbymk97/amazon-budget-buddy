import { useMemo } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatMoney } from "../../api";
import { CHART_CHROME, SEQUENTIAL_BLUE } from "../../lib/chartTheme";

export type BreakdownItem = {
  name: string;
  valueCents: number;
};

export function BreakdownChart({
  items,
  colorFor,
  height,
}: {
  items: BreakdownItem[];
  colorFor?: (name: string) => string;
  height?: number;
}) {
  const data = useMemo(
    () =>
      [...items]
        .sort((a, b) => Math.abs(b.valueCents) - Math.abs(a.valueCents))
        .map((item) => ({ name: item.name, value: Math.abs(item.valueCents) / 100 })),
    [items]
  );

  const chartHeight = height ?? Math.max(140, data.length * 36 + 24);

  return (
    <ResponsiveContainer width="100%" height={chartHeight}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 48, left: 0, bottom: 4 }}>
        <CartesianGrid stroke={CHART_CHROME.grid} horizontal={false} />
        <XAxis
          type="number"
          tick={{ fill: CHART_CHROME.inkMuted, fontSize: 12 }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v: number) => `$${v.toLocaleString()}`}
        />
        <YAxis
          type="category"
          dataKey="name"
          tick={{ fill: CHART_CHROME.inkSoft, fontSize: 12 }}
          axisLine={false}
          tickLine={false}
          width={140}
        />
        <Tooltip
          contentStyle={{
            background: CHART_CHROME.surface,
            border: `1px solid ${CHART_CHROME.grid}`,
            borderRadius: 8,
            color: CHART_CHROME.ink,
          }}
          labelStyle={{ color: CHART_CHROME.inkSoft }}
          formatter={(value: unknown) => formatMoney(Number(value) * 100)}
        />
        <Bar dataKey="value" radius={[0, 4, 4, 0]} maxBarSize={24}>
          {data.map((entry) => (
            <Cell key={entry.name} fill={colorFor ? colorFor(entry.name) : SEQUENTIAL_BLUE} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
