import type { ReactNode } from "react";

export type SummaryItem = {
  label: string;
  value: ReactNode;
  title?: string;
};

export function DetailSummaryList({ items }: { items: SummaryItem[] }) {
  return (
    <>
      {items.map((item) => (
        <p key={item.label} title={item.title}>
          <strong>{item.label}:</strong> {item.value}
        </p>
      ))}
    </>
  );
}
