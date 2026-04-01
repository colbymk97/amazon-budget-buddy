import { useEffect, useRef, useState } from "react";
import {
  deleteActualConfig,
  deleteCredentials,
  getActualStatus,
  getCredentials,
  importTransactionsCsv,
  runActualSync,
  saveActualConfig,
  saveCredentials,
  getExportUrl,
  type ActualStatus,
  type CredentialsStatus,
} from "../api";

// ---------------------------------------------------------------------------
// Amazon credentials panel
// ---------------------------------------------------------------------------

function AmazonCredentialsPanel() {
  const [status, setStatus] = useState<CredentialsStatus | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [otpSecret, setOtpSecret] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = () =>
    getCredentials("amazon")
      .then(setStatus)
      .catch(() => setStatus({ configured: false }));

  useEffect(() => { load(); }, []);

  const onSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setMsg(null);
    try {
      await saveCredentials("amazon", { email, password, otp_secret: otpSecret || undefined });
      setMsg({ ok: true, text: "Credentials saved." });
      setPassword("");
      setOtpSecret("");
      await load();
    } catch (err) {
      setMsg({ ok: false, text: String(err) });
    } finally {
      setSaving(false);
    }
  };

  const onDelete = async () => {
    if (!confirm("Remove saved Amazon credentials?")) return;
    try {
      await deleteCredentials("amazon");
      setMsg({ ok: true, text: "Credentials removed." });
      setEmail("");
      await load();
    } catch (err) {
      setMsg({ ok: false, text: String(err) });
    }
  };

  return (
    <article className="panel">
      <p className="eyebrow">Retailer</p>
      <h3>Amazon Credentials</h3>
      <p className="muted" style={{ marginBottom: "1rem" }}>
        Stored locally in SQLite. Used to log in to Amazon and fetch your order history.
      </p>

      {status?.configured && (
        <div className="settings-status-row">
          <span className="status-pill good">Connected — {status.email}</span>
          {status.has_otp_secret && <span className="status-pill neutral">OTP key set</span>}
          <button className="btn-ghost" onClick={onDelete}>
            Remove
          </button>
        </div>
      )}

      <form onSubmit={onSave} className="settings-form">
        <label>
          Amazon email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder={status?.email ?? "you@example.com"}
            required
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={status?.configured ? "Leave blank to keep existing" : ""}
            required={!status?.configured}
            autoComplete="current-password"
          />
        </label>
        <label>
          OTP secret key <span className="muted">(optional — enables automatic 2FA)</span>
          <input
            type="password"
            value={otpSecret}
            onChange={(e) => setOtpSecret(e.target.value)}
            placeholder={status?.has_otp_secret ? "Leave blank to keep existing" : "Base32 TOTP secret"}
            autoComplete="one-time-code"
          />
        </label>
        <button type="submit" disabled={saving}>
          {saving ? "Saving..." : status?.configured ? "Update Credentials" : "Save Credentials"}
        </button>
      </form>

      {msg && <p className={msg.ok ? "success-msg" : "error"}>{msg.text}</p>}
    </article>
  );
}

// ---------------------------------------------------------------------------
// CSV import panel
// ---------------------------------------------------------------------------

function CsvImportPanel() {
  const fileRef = useRef<HTMLInputElement>(null);
  const [accountId, setAccountId] = useState("");
  const [importing, setImporting] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const onImport = async (e: React.FormEvent) => {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setImporting(true);
    setMsg(null);
    try {
      const result = await importTransactionsCsv(file, accountId || undefined);
      setMsg({ ok: true, text: `Imported ${result.imported} transaction(s).` });
      if (fileRef.current) fileRef.current.value = "";
    } catch (err) {
      setMsg({ ok: false, text: String(err) });
    } finally {
      setImporting(false);
    }
  };

  return (
    <article className="panel">
      <p className="eyebrow">Bank / Card Statements</p>
      <h3>Import Transactions CSV</h3>
      <p className="muted" style={{ marginBottom: "1rem" }}>
        Required columns: <code>transaction_id</code>, <code>posted_date</code>, <code>amount</code>,{" "}
        <code>merchant_raw</code>.
      </p>

      <form onSubmit={onImport} className="settings-form">
        <label>
          CSV file
          <input ref={fileRef} type="file" accept=".csv" required />
        </label>
        <label>
          Account ID <span className="muted">(optional tag for multi-card households)</span>
          <input
            type="text"
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
            placeholder="e.g. chase-sapphire"
          />
        </label>
        <button type="submit" disabled={importing}>
          {importing ? "Importing..." : "Import CSV"}
        </button>
      </form>

      {msg && <p className={msg.ok ? "success-msg" : "error"}>{msg.text}</p>}
    </article>
  );
}

// ---------------------------------------------------------------------------
// Export panel
// ---------------------------------------------------------------------------

function ExportPanel() {
  return (
    <article className="panel">
      <p className="eyebrow">Reports</p>
      <h3>Export CSV Reports</h3>
      <p className="muted" style={{ marginBottom: "1rem" }}>
        Downloads a zip containing itemized, unmatched, and monthly summary CSVs.
      </p>
      <a href={getExportUrl()} download="budget_buddy_export.zip">
        <button type="button">Download Export</button>
      </a>
    </article>
  );
}

// ---------------------------------------------------------------------------
// Actual Budget panel
// ---------------------------------------------------------------------------

function ActualBudgetPanel() {
  const [status, setStatus] = useState<ActualStatus | null>(null);
  const [baseUrl, setBaseUrl] = useState("");
  const [password, setPassword] = useState("");
  const [file, setFile] = useState("");
  const [accountName, setAccountName] = useState("");
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = () =>
    getActualStatus()
      .then(setStatus)
      .catch(() => setStatus({ configured: false }));

  useEffect(() => { load(); }, []);

  const onSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setMsg(null);
    try {
      await saveActualConfig({ base_url: baseUrl, password, file, account_name: accountName || undefined });
      setMsg({ ok: true, text: "Actual Budget config saved." });
      setPassword("");
      await load();
    } catch (err) {
      setMsg({ ok: false, text: String(err) });
    } finally {
      setSaving(false);
    }
  };

  const onDelete = async () => {
    if (!confirm("Remove Actual Budget configuration?")) return;
    try {
      await deleteActualConfig();
      setMsg({ ok: true, text: "Config removed." });
      await load();
    } catch (err) {
      setMsg({ ok: false, text: String(err) });
    }
  };

  const onSync = async () => {
    setSyncing(true);
    setMsg(null);
    try {
      const result = await runActualSync(false);
      setMsg({ ok: true, text: `Synced ${result.synced ?? 0} transaction(s) to Actual.` });
      await load();
    } catch (err) {
      setMsg({ ok: false, text: String(err) });
    } finally {
      setSyncing(false);
    }
  };

  return (
    <article className="panel">
      <p className="eyebrow">Integration</p>
      <h3>Actual Budget</h3>
      <p className="muted" style={{ marginBottom: "1rem" }}>
        Optionally sync retailer transactions to a local Actual Budget instance.
      </p>

      {status?.configured && (
        <div className="settings-status-row">
          <span className="status-pill good">Connected — {status.file}</span>
          <span className="status-pill neutral">{status.pending ?? 0} pending</span>
          <button className="btn-ghost" onClick={onDelete}>Remove</button>
          <button onClick={onSync} disabled={syncing}>
            {syncing ? "Syncing..." : "Sync Now"}
          </button>
        </div>
      )}

      <form onSubmit={onSave} className="settings-form">
        <label>
          Base URL
          <input
            type="url"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder={status?.base_url ?? "http://localhost:5006"}
            required
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={status?.configured ? "Leave blank to keep existing" : ""}
            required={!status?.configured}
          />
        </label>
        <label>
          Budget file name
          <input
            type="text"
            value={file}
            onChange={(e) => setFile(e.target.value)}
            placeholder={status?.file ?? "My Budget"}
            required
          />
        </label>
        <label>
          Account name <span className="muted">(optional — restrict matching to one account)</span>
          <input
            type="text"
            value={accountName}
            onChange={(e) => setAccountName(e.target.value)}
            placeholder={status?.account_name ?? "Chase Sapphire"}
          />
        </label>
        <button type="submit" disabled={saving}>
          {saving ? "Saving..." : status?.configured ? "Update Config" : "Save Config"}
        </button>
      </form>

      {msg && <p className={msg.ok ? "success-msg" : "error"}>{msg.text}</p>}
    </article>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function SettingsPage() {
  return (
    <section className="settings-grid">
      <AmazonCredentialsPanel />
      <CsvImportPanel />
      <ExportPanel />
      <ActualBudgetPanel />
    </section>
  );
}
