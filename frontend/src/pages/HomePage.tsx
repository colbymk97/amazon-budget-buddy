import { useEffect, useState } from "react";
import { getDbStatus, getHealth, type DbRetailerStatus } from "../api";

export function HomePage() {
  const [status, setStatus] = useState<string>("loading");
  const [dbStats, setDbStats] = useState<DbRetailerStatus[] | null>(null);

  useEffect(() => {
    getHealth()
      .then((r) => setStatus(r.status))
      .catch(() => setStatus("error"));
    getDbStatus()
      .then((r) => setDbStats(r.retailers))
      .catch(() => setDbStats([]));
  }, []);

  const totalOrders = (dbStats ?? []).reduce((sum, r) => sum + r.orders, 0);
  const totalTransactions = (dbStats ?? []).reduce((sum, r) => sum + r.transactions, 0);
  const latestOrderDate = (dbStats ?? [])
    .map((r) => r.latest_order_date)
    .filter((d): d is string => !!d)
    .sort()
    .pop();
  const latestImport = (dbStats ?? [])
    .map((r) => r.last_import_finished_at)
    .filter((d): d is string => !!d)
    .sort()
    .pop();

  return (
    <section className="dashboard-grid">
      <article className="panel hero-panel">
        <div className="hero-copy">
          <p className="eyebrow">Dashboard</p>
          <h2>A read-only window into your local SQLite database.</h2>
          <p className="muted">
            Imports happen from the CLI (<code>amazon-spending import</code>). This site renders
            whatever is already in the database — orders, items, transactions, and budget categorization.
          </p>
        </div>

        <div className="hero-status">
          <div className={`status-pill ${status === "ok" ? "good" : "warn"}`}>API {status}</div>
          <div className="status-pill neutral">Read-only viewer</div>
        </div>
      </article>

      {dbStats && dbStats.length > 0 && (
        <article className="panel">
          <p className="eyebrow">Database</p>
          <h3>Retailer Status</h3>
          <table className="data-table" style={{ marginTop: "0.75rem" }}>
            <thead>
              <tr>
                <th>Retailer</th>
                <th>Orders</th>
                <th>Transactions</th>
                <th>Date Range</th>
                <th>Last Import</th>
              </tr>
            </thead>
            <tbody>
              {dbStats.map((r) => (
                <tr key={r.retailer}>
                  <td>{r.retailer}</td>
                  <td>{r.orders.toLocaleString()}</td>
                  <td>{r.transactions.toLocaleString()}</td>
                  <td>
                    {r.first_order_date ?? "—"} → {r.latest_order_date ?? "—"}
                  </td>
                  <td>
                    {r.last_import_finished_at
                      ? new Date(r.last_import_finished_at).toLocaleDateString()
                      : "—"}{" "}
                    {r.last_import_status ? (
                      <span className={`status-pill ${r.last_import_status === "ok" ? "good" : "neutral"}`}>
                        {r.last_import_status}
                      </span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </article>
      )}

      <div className="dashboard-stats">
        <article className="panel stat-card">
          <p className="eyebrow">Orders</p>
          <p className="stat-value">{totalOrders.toLocaleString()}</p>
          <p className="muted">Total across retailers</p>
        </article>

        <article className="panel stat-card">
          <p className="eyebrow">Transactions</p>
          <p className="stat-value">{totalTransactions.toLocaleString()}</p>
          <p className="muted">Retailer payment events</p>
        </article>

        <article className="panel stat-card">
          <p className="eyebrow">Latest Order</p>
          <p className="stat-value">{latestOrderDate ?? "n/a"}</p>
          <p className="muted">Most recent order date</p>
        </article>

        <article className="panel stat-card">
          <p className="eyebrow">Last Import</p>
          <p className="stat-value">
            {latestImport ? new Date(latestImport).toLocaleDateString() : "n/a"}
          </p>
          <p className="muted">Most recent CLI run</p>
        </article>
      </div>
    </section>
  );
}
