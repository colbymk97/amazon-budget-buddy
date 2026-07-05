import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  formatMoney,
  getSpendByCategory,
  getSpendByMonth,
  getSpendByRetailer,
  listItems,
  listOrders,
  listTransactions,
} from "../api";
import type {
  RetailerTransaction,
  Order,
  OrderItem,
  SpendByCategoryReport,
  SpendByMonthReport,
  SpendByRetailerReport,
} from "../types";
import { isoDate, monthEnd, monthLabel, monthStart, shiftMonth } from "../lib/dates";
import { Panel } from "../components/Panel";
import { SpendTrendChart } from "../components/charts/SpendTrendChart";
import { BreakdownChart } from "../components/charts/BreakdownChart";
import { colorForRetailer } from "../lib/chartTheme";

export function ReportsPage() {
  const navigate = useNavigate();
  const [selectedMonth, setSelectedMonth] = useState<Date>(() => monthStart(new Date()));
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [orders, setOrders] = useState<Order[]>([]);
  const [txns, setTxns] = useState<RetailerTransaction[]>([]);
  const [items, setItems] = useState<OrderItem[]>([]);

  const [trend, setTrend] = useState<SpendByMonthReport | null>(null);
  const [byRetailer, setByRetailer] = useState<SpendByRetailerReport | null>(null);
  const [byCategory, setByCategory] = useState<SpendByCategoryReport | null>(null);

  const startDate = useMemo(() => isoDate(monthStart(selectedMonth)), [selectedMonth]);
  const endDate = useMemo(() => isoDate(monthEnd(selectedMonth)), [selectedMonth]);

  useEffect(() => {
    setLoading(true);
    setError("");
    Promise.all([
      listOrders({ start_date: startDate, end_date: endDate, search, limit: 5000 }),
      listTransactions({ start_date: startDate, end_date: endDate, search, limit: 5000 }),
      listItems({ start_date: startDate, end_date: endDate, search, limit: 5000 }),
      getSpendByRetailer({ start_date: startDate, end_date: endDate }),
      getSpendByCategory({ start_date: startDate, end_date: endDate }),
    ])
      .then(([o, t, i, byR, byC]) => {
        setOrders(o.rows);
        setTxns(t.rows);
        setItems(i.rows);
        setByRetailer(byR);
        setByCategory(byC);
      })
      .catch(() => setError("Failed to load report data"))
      .finally(() => setLoading(false));
  }, [startDate, endDate, search]);

  useEffect(() => {
    const trendStart = isoDate(monthStart(shiftMonth(new Date(), -11)));
    const trendEnd = isoDate(new Date());
    getSpendByMonth({ start_date: trendStart, end_date: trendEnd })
      .then(setTrend)
      .catch(() => setTrend(null));
  }, []);

  const monthlyNetCents = useMemo(
    () => txns.reduce((sum, t) => sum + (t.amount_cents ?? 0), 0),
    [txns]
  );
  const monthlyGrossOrderCents = useMemo(
    () => orders.reduce((sum, o) => sum + (o.order_total_cents ?? 0), 0),
    [orders]
  );

  const monthOptions = useMemo(
    () => Array.from({ length: 12 }, (_, i) => shiftMonth(monthStart(new Date()), -i)),
    []
  );

  return (
    <section className="report-layout">
      <article className="panel report-controls">
        <div className="report-controls-top">
          <h2>Monthly Reporting</h2>
          <input
            placeholder="Search orders, labels, item titles..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <div className="month-nav">
          <button onClick={() => setSelectedMonth((d) => shiftMonth(d, -1))}>← Previous</button>
          <div className="month-current">{monthLabel(selectedMonth)}</div>
          <button onClick={() => setSelectedMonth((d) => shiftMonth(d, 1))}>Next →</button>
        </div>

        <div className="month-strip">
          {monthOptions.map((d) => {
            const value = isoDate(d);
            const selected = value === isoDate(selectedMonth);
            return (
              <button
                key={value}
                className={`month-chip${selected ? " active" : ""}`}
                onClick={() => setSelectedMonth(d)}
              >
                {d.toLocaleDateString("en-US", { month: "short", year: "2-digit" })}
              </button>
            );
          })}
        </div>
      </article>

      <div className="report-summary-grid">
        <article className="panel">
          <h3>Net Spend (Transactions)</h3>
          <p className="report-number">{formatMoney(monthlyNetCents)}</p>
          <p className="muted">Range: {startDate} to {endDate}</p>
        </article>
        <article className="panel">
          <h3>Gross Order Total</h3>
          <p className="report-number">{formatMoney(monthlyGrossOrderCents)}</p>
          <p className="muted">Sum of order totals in month</p>
        </article>
        <article className="panel">
          <h3>Counts</h3>
          <p>Orders: <strong>{orders.length}</strong></p>
          <p>Transactions: <strong>{txns.length}</strong></p>
          <p>Items: <strong>{items.length}</strong></p>
        </article>
      </div>

      <Panel className="chart-panel">
        <h3>Spend Trend (Trailing 12 Months)</h3>
        {trend ? <SpendTrendChart months={trend.months} retailers={trend.retailers} /> : null}
      </Panel>

      <div className="dashboard-charts-grid">
        <Panel className="chart-panel">
          <h3>By Retailer — {monthLabel(selectedMonth)}</h3>
          {byRetailer ? (
            <BreakdownChart
              items={byRetailer.retailers.map((r) => ({ name: r.retailer, valueCents: r.net_amount_cents }))}
              colorFor={colorForRetailer}
            />
          ) : null}
        </Panel>

        <Panel className="chart-panel">
          <h3>By Category — {monthLabel(selectedMonth)}</h3>
          {byCategory ? (
            <BreakdownChart
              items={byCategory.rows.map((r) => ({ name: r.name, valueCents: r.net_amount_cents }))}
            />
          ) : null}
        </Panel>
      </div>

      <article className="panel">
        <h3>Top Orders This Month</h3>
        {loading ? <p>Loading...</p> : null}
        {error ? <p className="error">{error}</p> : null}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Order ID</th>
                <th>Date</th>
                <th>Total</th>
                <th>Items</th>
                <th>Transactions</th>
              </tr>
            </thead>
            <tbody>
              {[...orders]
                .sort((a, b) => (b.order_total_cents ?? 0) - (a.order_total_cents ?? 0))
                .slice(0, 30)
                .map((o) => (
                  <tr key={o.order_id} className="clickable" onClick={() => navigate(`/orders/${o.order_id}`)}>
                    <td>{o.order_id}</td>
                    <td>{o.order_date}</td>
                    <td>{formatMoney(o.order_total_cents)}</td>
                    <td>{o.item_count ?? 0}</td>
                    <td>{o.txn_count ?? 0}</td>
                  </tr>
                ))}
              {!loading && orders.length === 0 ? (
                <tr>
                  <td colSpan={5} className="muted">
                    No orders in this month.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </article>
    </section>
  );
}
