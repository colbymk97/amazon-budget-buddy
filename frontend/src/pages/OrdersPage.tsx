import { useEffect, useMemo, useState } from "react";
import { ColumnDef } from "@tanstack/react-table";
import { useNavigate } from "react-router-dom";
import { formatMoney, listOrders } from "../api";
import type { Order } from "../types";
import { DataTable } from "../components/DataTable";

export function OrdersPage() {
  const [rows, setRows] = useState<Order[]>([]);
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
    listOrders({ search, start_date: startDate, end_date: endDate, limit: 1000 })
      .then((res) => setRows(res.rows))
      .catch(() => setError("Failed to load orders"))
      .finally(() => setLoading(false));
  }, [search, startDate, endDate]);

  const columns = useMemo<ColumnDef<Order>[]>(
    () => [
      { accessorKey: "order_id", header: "Order ID" },
      { accessorKey: "order_date", header: "Date" },
      { accessorKey: "item_count", header: "Items" },
      { accessorKey: "txn_count", header: "Transactions" },
      { accessorKey: "order_total_cents", header: "Total", cell: (c) => formatMoney(c.getValue<number>()) },
      { accessorKey: "tax_cents", header: "Tax", cell: (c) => formatMoney(c.getValue<number | null>()) },
      { accessorKey: "payment_last4", header: "Last4" },
      { accessorKey: "order_url", header: "Order URL" }
    ],
    []
  );

  return (
    <>
      <section className="filters">
        <input placeholder="Search orders/title" value={search} onChange={(e) => setSearch(e.target.value)} />
        <input value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        <input value={endDate} onChange={(e) => setEndDate(e.target.value)} />
      </section>
      {loading ? <p>Loading...</p> : null}
      {error ? <p className="error">{error}</p> : null}
      <DataTable
        title="Orders"
        data={rows}
        columns={columns}
        globalFilter={globalFilter}
        onGlobalFilterChange={setGlobalFilter}
        onRowClick={(r) => navigate(`/orders/${r.order_id}`)}
      />
    </>
  );
}
