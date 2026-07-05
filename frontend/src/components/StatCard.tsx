import type { ReactNode } from "react";

export function StatCard({
  label,
  value,
  caption,
}: {
  label: string;
  value: ReactNode;
  caption?: ReactNode;
}) {
  return (
    <article className="panel stat-card">
      <p className="eyebrow">{label}</p>
      <p className="stat-value">{value}</p>
      {caption ? <p className="muted">{caption}</p> : null}
    </article>
  );
}
