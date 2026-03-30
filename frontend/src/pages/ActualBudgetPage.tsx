import { useEffect, useState } from "react";
import {
  autoCategorize,
  formatMoney,
  getActualCategories,
  getActualStatus,
  saveActualConfig,
  syncToActual,
  testActualConnection,
} from "../api";
import type { ActualCategory, ActualConfigPayload, ActualStatus } from "../types";

export function ActualBudgetPage() {
  // --- config form state ---
  const [baseUrl, setBaseUrl] = useState("");
  const [password, setPassword] = useState("");
  const [file, setFile] = useState("");
  const [accountName, setAccountName] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [configMsg, setConfigMsg] = useState("");
  const [configError, setConfigError] = useState("");

  // --- actual status ---
  const [status, setStatus] = useState<ActualStatus | null>(null);

  // --- categories ---
  const [categories, setCategories] = useState<ActualCategory[]>([]);
  const [loadingCats, setLoadingCats] = useState(false);

  // --- sync ---
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<string>("");

  // --- AI categorize ---
  const [categorizing, setCategorizing] = useState(false);
  const [catResult, setCatResult] = useState("");

  // --- load current status on mount ---
  useEffect(() => {
    getActualStatus()
      .then((s) => {
        setStatus(s);
        if (s.configured) {
          setBaseUrl(s.base_url ?? "");
          setFile(s.file ?? "");
          setAccountName(s.account_name ?? "");
        }
      })
      .catch(() => {});
  }, []);

  const configPayload = (): ActualConfigPayload => ({
    base_url: baseUrl,
    password,
    file,
    account_name: accountName || undefined,
  });

  const onTestConnection = async () => {
    setConfigMsg("");
    setConfigError("");
    setTesting(true);
    try {
      const r = await testActualConnection(configPayload());
      setConfigMsg(r.message);
    } catch (e: unknown) {
      setConfigError(e instanceof Error ? e.message : "Connection test failed.");
    } finally {
      setTesting(false);
    }
  };

  const onSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setConfigMsg("");
    setConfigError("");
    setSaving(true);
    try {
      await saveActualConfig(configPayload());
      setConfigMsg("Configuration saved.");
      const s = await getActualStatus();
      setStatus(s);
    } catch (e: unknown) {
      setConfigError(e instanceof Error ? e.message : "Failed to save configuration.");
    } finally {
      setSaving(false);
    }
  };

  const onFetchCategories = async () => {
    setLoadingCats(true);
    try {
      const res = await getActualCategories();
      setCategories(res.rows);
    } catch {
      setConfigError("Failed to fetch categories from Actual Budget.");
    } finally {
      setLoadingCats(false);
    }
  };

  const onSync = async (dryRun: boolean) => {
    setSyncing(true);
    setSyncResult("");
    try {
      const r = await syncToActual(dryRun);
      const prefix = dryRun ? "[Dry Run] " : "";
      setSyncResult(
        `${prefix}Synced: ${r.synced}, No match: ${r.no_match}` +
        (r.errors.length ? `, Errors: ${r.errors.length}` : "")
      );
      const s = await getActualStatus();
      setStatus(s);
    } catch (e: unknown) {
      setSyncResult(e instanceof Error ? e.message : "Sync failed.");
    } finally {
      setSyncing(false);
    }
  };

  const onAutoCategorize = async () => {
    setCategorizing(true);
    setCatResult("");
    try {
      const r = await autoCategorize();
      setCatResult(
        r.message ?? `Categorized ${r.categorized} of ${r.total} transaction(s).`
      );
    } catch (e: unknown) {
      setCatResult(e instanceof Error ? e.message : "Auto-categorization failed.");
    } finally {
      setCategorizing(false);
    }
  };

  return (
    <section className="report-layout">
      <article className="panel">
        <h2>Actual Budget</h2>
        <p className="muted">
          Configure your Actual Budget server connection, sync transactions, and auto-categorize using AI.
          Actual Budget is the source of truth for all budget data.
        </p>
      </article>

      {/* --- Connection Configuration --- */}
      <article className="panel">
        <h3>Server Configuration</h3>
        <form className="admin-form" onSubmit={onSave}>
          <input
            placeholder="Base URL (e.g. http://localhost:5006)"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            required
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <input
            placeholder="Budget file name (e.g. My Budget)"
            value={file}
            onChange={(e) => setFile(e.target.value)}
            required
          />
          <input
            placeholder="Account name filter (optional)"
            value={accountName}
            onChange={(e) => setAccountName(e.target.value)}
          />
          <div className="sync-actions">
            <button type="button" onClick={onTestConnection} disabled={testing || !baseUrl || !password || !file}>
              {testing ? "Testing..." : "Test Connection"}
            </button>
            <button type="submit" disabled={saving || !baseUrl || !password || !file}>
              {saving ? "Saving..." : "Save Configuration"}
            </button>
          </div>
        </form>
        {configMsg ? <p className="muted">{configMsg}</p> : null}
        {configError ? <p className="error">{configError}</p> : null}
        {status ? (
          <div className="hero-status" style={{ marginTop: 8 }}>
            <div className={`status-pill ${status.configured ? "good" : "warn"}`}>
              {status.configured ? "Connected" : "Not configured"}
            </div>
            {status.configured ? (
              <div className="status-pill info">{status.pending} pending sync</div>
            ) : null}
          </div>
        ) : null}
      </article>

      {/* --- Sync Controls --- */}
      <article className="panel">
        <h3>Sync to Actual Budget</h3>
        <p className="muted">
          Push unsynced retailer transactions to Actual Budget. Each matched transaction gets its notes updated
          with the Amazon order ID and line items. Pending: <strong>{status?.pending ?? 0}</strong> transaction(s).
        </p>
        <div className="sync-actions">
          <button onClick={() => onSync(true)} disabled={syncing || !status?.configured}>
            {syncing ? "Running..." : "Dry Run (Preview)"}
          </button>
          <button onClick={() => onSync(false)} disabled={syncing || !status?.configured}>
            {syncing ? "Syncing..." : "Sync to Actual"}
          </button>
        </div>
        {syncResult ? <p className="muted">{syncResult}</p> : null}
      </article>

      {/* --- AI Auto-Categorize --- */}
      <article className="panel">
        <h3>AI Auto-Categorization</h3>
        <p className="muted">
          Automatically categorize uncategorized transactions using AI before syncing.
          Uses categories from your connected Actual Budget server in a single optimized call.
        </p>
        <div className="sync-actions">
          <button onClick={onFetchCategories} disabled={loadingCats || !status?.configured}>
            {loadingCats ? "Loading..." : "Fetch Categories"}
          </button>
          <button onClick={onAutoCategorize} disabled={categorizing || !status?.configured}>
            {categorizing ? "Categorizing..." : "Auto-Categorize Transactions"}
          </button>
        </div>
        {catResult ? <p className="muted">{catResult}</p> : null}
      </article>

      {/* --- Actual Categories (read-only) --- */}
      {categories.length > 0 ? (
        <article className="panel">
          <h3>Actual Budget Categories</h3>
          <p className="muted">
            {categories.length} categories loaded from Actual Budget. These are used for AI auto-categorization
            and displayed read-only on transaction tables.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Group</th>
                  <th>Category</th>
                  <th>ID</th>
                </tr>
              </thead>
              <tbody>
                {categories.map((c) => (
                  <tr key={c.id}>
                    <td>{c.group}</td>
                    <td>{c.name}</td>
                    <td className="muted">{c.id.slice(0, 8)}...</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      ) : null}
    </section>
  );
}
