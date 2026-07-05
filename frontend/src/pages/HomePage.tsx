import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  formatMoney,
  getHealth,
  getRetailerStatus,
  getSpendByCategory,
  getSpendByMonth,
  getSpendByRetailer,
} from "../api";
import type { RetailerStatus, SpendByCategoryReport, SpendByMonthReport, SpendByRetailerReport } from "../types";
import { Panel } from "../components/Panel";
import { StatCard } from "../components/StatCard";
import { SpendTrendChart } from "../components/charts/SpendTrendChart";
import { BreakdownChart } from "../components/charts/BreakdownChart";
import { isoDate, monthStart, shiftMonth } from "../lib/dates";
import { colorForRetailer } from "../lib/chartTheme";

export function HomePage() {
  const [apiStatus, setApiStatus] = useState("loading");
  const [retailers, setRetailers] = useState<RetailerStatus[]>([]);
  const [monthly, setMonthly] = useState<SpendByMonthReport | null>(null);
  const [byRetailer, setByRetailer] = useState<SpendByRetailerReport | null>(null);
  const [byCategory, setByCategory] = useState<SpendByCategoryReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    getHealth()
      .then((r) => setApiStatus(r.status))
      .catch(() => setApiStatus("error"));
  }, []);

  useEffect(() => {
    const start = isoDate(monthStart(shiftMonth(new Date(), -11)));
    const end = isoDate(new Date());

    setLoading(true);
    setError("");
    Promise.all([
      getRetailerStatus(),
      getSpendByMonth({ start_date: start, end_date: end }),
      getSpendByRetailer({ start_date: start, end_date: end }),
      getSpendByCategory({ start_date: start, end_date: end }),
    ])
      .then(([r, m, byR, byC]) => {
        setRetailers(r.retailers);
        setMonthly(m);
        setByRetailer(byR);
        setByCategory(byC);
      })
      .catch(() => setError("Failed to load dashboard data"))
      .finally(() => setLoading(false));
  }, []);

  const totalNetCents = monthly?.months.reduce((sum, m) => sum + m.net_amount_cents, 0) ?? 0;
  const totalOrders = monthly?.months.reduce((sum, m) => sum + m.order_count, 0) ?? 0;
  const latestRetailer = retailers[0];

  return (
    <section className="dashboard-grid">
      <Panel>
        <div className="status-strip">
          <div className={`status-pill ${apiStatus === "ok" ? "good" : "warn"}`}>API {apiStatus}</div>
          <div className="status-pill neutral">
            Last sync: {latestRetailer?.last_import_finished_at ?? "never"}
          </div>
          <Link to="/status" className="status-strip-link">
            View sync &amp; import status →
          </Link>
        </div>
      </Panel>

      <div className="dashboard-stats">
        <StatCard label="Net Spend (12mo)" value={formatMoney(totalNetCents)} caption="Trailing 12 months" />
        <StatCard label="Orders (12mo)" value={totalOrders} caption="Trailing 12 months" />
        <StatCard
          label="Latest Order"
          value={latestRetailer?.latest_order_date ?? "n/a"}
          caption={latestRetailer?.retailer ?? ""}
        />
      </div>

      {loading ? <p>Loading dashboard...</p> : null}
      {error ? <p className="error">{error}</p> : null}

      <Panel className="chart-panel">
        <h3>Spend Trend</h3>
        {monthly ? <SpendTrendChart months={monthly.months} retailers={monthly.retailers} /> : null}
      </Panel>

      <div className="dashboard-charts-grid">
        <Panel className="chart-panel">
          <h3>By Retailer</h3>
          {byRetailer ? (
            <BreakdownChart
              items={byRetailer.retailers.map((r) => ({ name: r.retailer, valueCents: r.net_amount_cents }))}
              colorFor={colorForRetailer}
            />
          ) : null}
        </Panel>

        <Panel className="chart-panel">
          <h3>By Category</h3>
          {byCategory ? (
            <BreakdownChart
              items={byCategory.rows.map((r) => ({ name: r.name, valueCents: r.net_amount_cents }))}
            />
          ) : null}
        </Panel>
      </div>
    </section>
  );
}
