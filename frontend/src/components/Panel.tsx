import type { ReactNode } from "react";

export function Panel({ children, className }: { children: ReactNode; className?: string }) {
  return <article className={className ? `panel ${className}` : "panel"}>{children}</article>;
}
