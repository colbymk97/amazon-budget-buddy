import type { ReactNode } from "react";

export type SimpleColumn<T> = {
  header: string;
  cell: (row: T) => ReactNode;
  className?: string;
  title?: (row: T) => string;
};

export function SimpleTable<T>({
  columns,
  rows,
  rowKey,
  emptyMessage,
}: {
  columns: SimpleColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  emptyMessage: string;
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col.header}>{col.header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)}>
              {columns.map((col) => (
                <td key={col.header} className={col.className} title={col.title?.(row)}>
                  {col.cell(row)}
                </td>
              ))}
            </tr>
          ))}
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="muted">
                {emptyMessage}
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}
