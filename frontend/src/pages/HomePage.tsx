import { useEffect, useMemo, useState } from "react";
import { cancelSync, getActualStatus, getHealth, getSyncStatus, startSync, type SyncStatus } from "../api";
import type { ActualStatus } from "../types";

export function HomePage() {
  const [status, setStatus] = useState<string>("loading");
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [actualStatus, setActualStatus] = useState<ActualStatus | null>(null);

  useEffect(() => {
    getHealth()
      .then((r) => setStatus(r.status))
      .catch(() => setStatus("error"));
    getActualStatus()
      .then(setActualStatus)
      .catch(() => {});
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

  return (
    <section className="dashboard-grid">
      <article className="panel hero-panel">
        <div className="hero-copy">
          <p className="eyebrow">Command Center</p>
          <h2>Control imports without leaving the dashboard.</h2>
          <p className="muted">
            The new shell emphasizes status visibility, room for new modules, and a steadier visual rhythm for
            everyday use.
          </p>
        </div>

        <div className="hero-status">
          <div className={`status-pill ${status === "ok" ? "good" : "warn"}`}>API {status}</div>
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
      </article>

      <div className="dashboard-stats">
        <article className="panel stat-card">
          <p className="eyebrow">API</p>
          <p className="stat-value">{status}</p>
          <p className="muted">Backend health check</p>
        </article>

        <article className="panel stat-card">
          <p className="eyebrow">Latest Orders</p>
          <p className="stat-value">{sync?.last_order_date ?? "n/a"}</p>
          <p className="muted">Most recent order date</p>
        </article>

        <article className="panel stat-card">
          <p className="eyebrow">Latest Transactions</p>
          <p className="stat-value">{sync?.last_transaction_date ?? "n/a"}</p>
          <p className="muted">Most recent transaction date</p>
        </article>

        <article className="panel stat-card">
          <p className="eyebrow">Actual Budget</p>
          <p className="stat-value">
            {actualStatus
              ? actualStatus.configured
                ? `${actualStatus.pending} pending`
                : "Not configured"
              : "n/a"}
          </p>
          <p className="muted">
            {actualStatus?.configured
              ? `Syncing to ${actualStatus.file}`
              : "Configure in Actual Budget page"}
          </p>
        </article>
      </div>
    </section>
  );
}
