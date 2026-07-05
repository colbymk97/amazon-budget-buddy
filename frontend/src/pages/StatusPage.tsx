import { useEffect, useMemo, useState } from "react";
import {
  cancelSync,
  getActualStatus,
  getHealth,
  getRetailerStatus,
  getSyncStatus,
  startSync,
  syncActualCategories,
  syncToActual,
  type SyncStatus,
} from "../api";
import type { ActualStatus, RetailerStatus } from "../types";
import { Panel } from "../components/Panel";
import { StatCard } from "../components/StatCard";
import { SimpleTable } from "../components/SimpleTable";

export function StatusPage() {
  const [apiStatus, setApiStatus] = useState<string>("loading");
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");

  const [retailers, setRetailers] = useState<RetailerStatus[]>([]);
  const [actual, setActual] = useState<ActualStatus | null>(null);
  const [actualLoading, setActualLoading] = useState(true);
  const [actualError, setActualError] = useState("");

  const [runningActualSync, setRunningActualSync] = useState(false);
  const [actualSyncMessage, setActualSyncMessage] = useState("");
  const [syncingCategories, setSyncingCategories] = useState(false);
  const [categorySyncMessage, setCategorySyncMessage] = useState("");

  useEffect(() => {
    getHealth()
      .then((r) => setApiStatus(r.status))
      .catch(() => setApiStatus("error"));
  }, []);

  useEffect(() => {
    let active = true;
    let timer: number | null = null;

    const poll = async () => {
      try {
        const s = await getSyncStatus();
        if (!active) return;
        setSync(s);
      } catch {
        if (!active) return;
        setError("Failed to fetch sync status.");
      } finally {
        if (active) {
          timer = window.setTimeout(poll, 1200);
        }
      }
    };
    poll();
    return () => {
      active = false;
      if (timer) window.clearTimeout(timer);
    };
  }, []);

  const loadStatus = async () => {
    setActualLoading(true);
    setActualError("");
    try {
      const [r, a] = await Promise.all([getRetailerStatus(), getActualStatus()]);
      setRetailers(r.retailers);
      setActual(a);
    } catch {
      setActualError("Failed to load retailer/Actual status.");
    } finally {
      setActualLoading(false);
    }
  };

  useEffect(() => {
    loadStatus();
  }, []);

  const canStart = useMemo(() => !starting && !sync?.running, [starting, sync?.running]);
  const progress = Math.max(0, Math.min(100, sync?.progress ?? 0));

  const onStartSync = async () => {
    setError("");
    setStarting(true);
    try {
      await startSync();
      const s = await getSyncStatus();
      setSync(s);
    } catch {
      setError("Failed to start import.");
    } finally {
      setStarting(false);
    }
  };

  const onCancelSync = async () => {
    setError("");
    try {
      await cancelSync();
      const s = await getSyncStatus();
      setSync(s);
    } catch {
      setError("Failed to request cancellation.");
    }
  };

  const onRunActualSync = async (dryRun: boolean) => {
    setRunningActualSync(true);
    setActualSyncMessage("");
    setActualError("");
    try {
      const result = await syncToActual(dryRun);
      setActualSyncMessage(
        `${dryRun ? "Dry run: " : ""}synced ${result.synced}, refreshed ${result.refreshed}, ` +
          `skipped ${result.skipped}, no match ${result.no_match}.`
      );
      await loadStatus();
    } catch {
      setActualError("Actual sync failed. Check that Actual Budget is configured and reachable.");
    } finally {
      setRunningActualSync(false);
    }
  };

  const onSyncCategories = async () => {
    setSyncingCategories(true);
    setCategorySyncMessage("");
    setActualError("");
    try {
      const result = await syncActualCategories();
      setCategorySyncMessage(`Synced ${result.categories_synced} categories from Actual.`);
    } catch {
      setActualError("Could not refresh categories from Actual.");
    } finally {
      setSyncingCategories(false);
    }
  };

  return (
    <section className="dashboard-grid">
      <Panel className="hero-panel">
        <h2>Sync &amp; Import</h2>

        <div className="hero-status">
          <div className={`status-pill ${apiStatus === "ok" ? "good" : "warn"}`}>API {apiStatus}</div>
          <div className={`status-pill ${sync?.running ? "info" : "neutral"}`}>
            {sync?.running ? "Import active" : "Importer idle"}
          </div>
          <div className="status-pill neutral">Stage {sync?.stage ?? "waiting"}</div>
        </div>

        <div className="sync-actions">
          <button disabled={!canStart} onClick={onStartSync}>
            {starting ? "Starting..." : sync?.running ? "Import Running..." : "Import New Data"}
          </button>
          <button disabled={!sync?.running} onClick={onCancelSync}>
            Terminate Import
          </button>
          {sync?.running ? <span className="muted">Importing in background...</span> : null}
        </div>

        {sync ? (
          <div className="sync-progress">
            <div className="progress-labels">
              <span>{sync.stage}</span>
              <strong>{progress}%</strong>
            </div>
            <progress value={progress} max={100} />
            {sync.cancel_requested ? <p className="muted">Cancellation requested...</p> : null}
            <p className="muted">{sync.notes ?? ""}</p>
            {!sync.running && (sync.new_transactions_added ?? 0) > 0 ? (
              <p>
                Added <strong>{sync.new_transactions_added}</strong> new transaction(s).
              </p>
            ) : null}
            {!sync.running && (sync.new_orders_added ?? 0) > 0 ? (
              <p>
                Found <strong>{sync.new_orders_added}</strong> order(s)
                {sync.sync_since_date ? (
                  <>
                    {" "}
                    since <strong>{sync.sync_since_date}</strong>
                  </>
                ) : null}
                .
              </p>
            ) : null}
            {!sync.running && (sync.new_transactions_added ?? 0) === 0 && sync.status === "ok" ? (
              <p>
                No new orders were found
                {sync.sync_since_date ? (
                  <>
                    {" "}
                    since <strong>{sync.sync_since_date}</strong>
                  </>
                ) : (
                  " since the last import"
                )}
                .
              </p>
            ) : null}
            {!sync.running && sync.status === "cancelled" ? <p>Import terminated by user.</p> : null}
            {sync.error ? <p className="error">{sync.error}</p> : null}
          </div>
        ) : null}

        {error ? <p className="error">{error}</p> : null}
      </Panel>

      <Panel>
        <h3>Retailers</h3>
        {actualLoading ? <p>Loading...</p> : null}
        <SimpleTable
          columns={[
            { header: "Retailer", cell: (r: RetailerStatus) => r.retailer },
            { header: "Orders", cell: (r) => r.orders },
            { header: "Transactions", cell: (r) => r.transactions },
            { header: "First Order", cell: (r) => r.first_order_date ?? "n/a" },
            { header: "Latest Order", cell: (r) => r.latest_order_date ?? "n/a" },
            { header: "Last Import", cell: (r) => r.last_import_finished_at ?? "n/a" },
            { header: "Status", cell: (r) => r.last_import_status ?? "n/a" },
            { header: "Account", cell: (r) => r.bound_account ?? "n/a" },
          ]}
          rows={retailers}
          rowKey={(r) => r.retailer}
          emptyMessage="No retailer activity yet."
        />
      </Panel>

      <div className="dashboard-stats">
        <StatCard label="Actual Budget" value={actual?.configured ? "Configured" : "Not configured"} caption={actual?.file ?? "Run actual-configure via the CLI"} />
        <StatCard label="Synced" value={actual?.synced ?? 0} caption={`of ${actual?.total_transactions ?? 0} transactions`} />
        <StatCard label="Pending" value={actual?.pending ?? 0} caption="Not yet synced" />
        <StatCard label="Skipped" value={actual?.skipped ?? 0} caption="Gift cards, points, etc." />
      </div>

      <Panel>
        <h3>Actual Budget Reconciliation</h3>
        <p className="muted">Last synced: {actual?.last_synced_at ?? "never"}</p>
        <div className="sync-actions">
          <button disabled={runningActualSync || !actual?.configured} onClick={() => onRunActualSync(true)}>
            {runningActualSync ? "Running..." : "Dry Run"}
          </button>
          <button disabled={runningActualSync || !actual?.configured} onClick={() => onRunActualSync(false)}>
            {runningActualSync ? "Running..." : "Sync to Actual"}
          </button>
          <button disabled={syncingCategories || !actual?.configured} onClick={onSyncCategories}>
            {syncingCategories ? "Refreshing..." : "Refresh Categories from Actual"}
          </button>
        </div>
        {actualSyncMessage ? <p className="muted">{actualSyncMessage}</p> : null}
        {categorySyncMessage ? <p className="muted">{categorySyncMessage}</p> : null}
        {actualError ? <p className="error">{actualError}</p> : null}

        {actual && actual.skip_reasons.length > 0 ? (
          <SimpleTable
            columns={[
              { header: "Skip Reason", cell: (s: { reason: string | null; count: number }) => s.reason ?? "n/a" },
              { header: "Count", cell: (s) => s.count },
            ]}
            rows={actual.skip_reasons}
            rowKey={(s) => s.reason ?? "n/a"}
            emptyMessage="No skipped transactions."
          />
        ) : null}
      </Panel>
    </section>
  );
}
