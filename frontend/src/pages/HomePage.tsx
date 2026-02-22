import { useEffect, useMemo, useState } from "react";
import { cancelSync, getHealth, getSyncStatus, startSync, type SyncStatus } from "../api";

export function HomePage() {
  const [status, setStatus] = useState<string>("loading");
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getHealth()
      .then((r) => setStatus(r.status))
      .catch(() => setStatus("error"));
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
        if (!active) return;
        timer = window.setTimeout(poll, 1200);
      }
    };
    poll();
    return () => {
      active = false;
      if (timer) window.clearTimeout(timer);
    };
  }, []);

  const canStart = useMemo(() => !starting && !sync?.running, [starting, sync?.running]);

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
    <section className="panel">
      <h2>Home Dashboard</h2>
      <div className="sync-metrics">
        <p>
          API status: <strong>{status}</strong>
        </p>
        <p>
          Last order date: <strong>{sync?.last_order_date ?? "n/a"}</strong>
        </p>
        <p>
          Last transaction date: <strong>{sync?.last_transaction_date ?? "n/a"}</strong>
        </p>
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
          <progress value={Math.max(0, Math.min(100, sync.progress ?? 0))} max={100} />
          <p>
            Stage: <strong>{sync.stage}</strong> | Progress: <strong>{sync.progress ?? 0}%</strong>
          </p>
          {sync.cancel_requested ? <p className="muted">Cancellation requested...</p> : null}
          <p className="muted">{sync.notes ?? ""}</p>
          {!sync.running && (sync.new_transactions_added ?? 0) > 0 ? (
            <p>
              Added <strong>{sync.new_transactions_added}</strong> new transaction(s).
            </p>
          ) : null}
          {!sync.running && (sync.new_transactions_added ?? 0) === 0 && sync.status === "ok" ? (
            <p>No new transactions were found since the last import.</p>
          ) : null}
          {!sync.running && sync.status === "cancelled" ? <p>Import terminated by user.</p> : null}
          {sync.error ? <p className="error">{sync.error}</p> : null}
        </div>
      ) : null}

      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
