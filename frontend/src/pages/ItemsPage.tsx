import { useEffect, useMemo, useState } from "react";
import { ColumnDef } from "@tanstack/react-table";
import { useNavigate } from "react-router-dom";
import { formatMoney, listItems } from "../api";
import type { OrderItem } from "../types";
import { DataTable } from "../components/DataTable";

export function ItemsPage() {
  const [rows, setRows] = useState<OrderItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [startDate, setStartDate] = useState("2000-01-01");
  const [endDate, setEndDate] = useState("2100-01-01");
  const [globalFilter, setGlobalFilter] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    setLoading(true);
    setError("");
    listItems({ search, start_date: startDate, end_date: endDate, limit: 1000 })
      .then((res) => setRows(res.rows))
      .catch(() => setError("Failed to load items"))
      .finally(() => setLoading(false));
  }, [search, startDate, endDate]);

  const columns = useMemo<ColumnDef<OrderItem>[]>(
    () => [
      { accessorKey: "item_id", header: "Item ID" },
      { accessorKey: "order_id", header: "Order ID" },
      { accessorKey: "title", header: "Title" },
      { accessorKey: "quantity", header: "Qty" },
      { accessorKey: "item_subtotal_cents", header: "Subtotal", cell: (c) => formatMoney(c.getValue<number>()) },
      { accessorKey: "item_tax_cents", header: "Tax", cell: (c) => formatMoney(c.getValue<number | null>()) },
      { accessorKey: "amazon_transaction_id", header: "Primary Txn" }
    ],
    []
  );

  return (
    <>
      <section className="filters">
        <input placeholder="Search id/title/order" value={search} onChange={(e) => setSearch(e.target.value)} />
        <input value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        <input value={endDate} onChange={(e) => setEndDate(e.target.value)} />
      </section>
      {loading ? <p>Loading...</p> : null}
      {error ? <p className="error">{error}</p> : null}
      <DataTable
        title="Order Items"
        data={rows}
        columns={columns}
        globalFilter={globalFilter}
        onGlobalFilterChange={setGlobalFilter}
        onRowClick={(r) => navigate(`/items/${r.item_id}`)}
      />
    </>
  );
}
