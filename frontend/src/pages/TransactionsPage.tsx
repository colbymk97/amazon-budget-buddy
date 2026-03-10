import { useEffect, useMemo, useState } from "react";
import { ColumnDef } from "@tanstack/react-table";
import { useNavigate } from "react-router-dom";
import { formatMoney, listTransactions } from "../api";
import type { RetailerTransaction } from "../types";
import { DataTable } from "../components/DataTable";

export function TransactionsPage() {
  const [rows, setRows] = useState<RetailerTransaction[]>([]);
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
    listTransactions({ search, start_date: startDate, end_date: endDate, limit: 1000 })
      .then((res) => setRows(res.rows))
      .catch(() => setError("Failed to load transactions"))
      .finally(() => setLoading(false));
  }, [search, startDate, endDate]);

  const columns = useMemo<ColumnDef<RetailerTransaction>[]>(
    () => [
      { accessorKey: "retailer_txn_id", header: "Transaction ID" },
      { accessorKey: "retailer", header: "Retailer" },
      { accessorKey: "txn_date", header: "Txn Date" },
      { accessorKey: "order_id", header: "Order ID" },
      { accessorKey: "amount_cents", header: "Amount", cell: (c) => formatMoney(c.getValue<number>()) },
      { accessorKey: "raw_label", header: "Label" },
      { accessorKey: "payment_last4", header: "Last4" },
      { accessorKey: "order_url", header: "Order URL" }
    ],
    []
  );

  return (
    <>
      <section className="filters">
        <input placeholder="Search id/label/order" value={search} onChange={(e) => setSearch(e.target.value)} />
        <input value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        <input value={endDate} onChange={(e) => setEndDate(e.target.value)} />
      </section>
      {loading ? <p>Loading...</p> : null}
      {error ? <p className="error">{error}</p> : null}
      <DataTable
        title="Transactions"
        data={rows}
        columns={columns}
        globalFilter={globalFilter}
        onGlobalFilterChange={setGlobalFilter}
        onRowClick={(r) => navigate(`/transactions/${r.retailer_txn_id}`)}
      />
    </>
  );
}
