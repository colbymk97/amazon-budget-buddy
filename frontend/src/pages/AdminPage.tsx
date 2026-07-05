import { useEffect, useState } from "react";
import { listBudgetCategories, listBudgetSubcategories, syncActualCategories } from "../api";
import type { BudgetCategory, BudgetSubcategory } from "../types";

export function AdminPage() {
  const [categories, setCategories] = useState<BudgetCategory[]>([]);
  const [subcategories, setSubcategories] = useState<BudgetSubcategory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState("");

  const loadAll = async () => {
    setLoading(true);
    setError("");
    try {
      const [c, s] = await Promise.all([listBudgetCategories(), listBudgetSubcategories()]);
      setCategories(c.rows);
      setSubcategories(s.rows);
    } catch {
      setError("Failed to load budget categories.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAll();
  }, []);

  const onRefreshFromActual = async () => {
    setSyncing(true);
    setSyncMessage("");
    setError("");
    try {
      const result = await syncActualCategories();
      setSyncMessage(`Synced ${result.categories_synced} categories from Actual.`);
      await loadAll();
    } catch {
      setError("Could not refresh categories from Actual. Is it configured and reachable?");
    } finally {
      setSyncing(false);
    }
  };

  return (
    <section className="report-layout">
      <article className="panel">
        <h2>Budget Categories</h2>
        <p className="muted">
          Categories are mirrored read-only from Actual Budget — pick them there, then pull the latest
          list here.
        </p>
        <button onClick={onRefreshFromActual} disabled={syncing}>
          {syncing ? "Refreshing..." : "Refresh from Actual"}
        </button>
        {syncMessage ? <p className="muted">{syncMessage}</p> : null}
      </article>

      {loading ? <p>Loading...</p> : null}
      {error ? <p className="error">{error}</p> : null}

      <div className="admin-grid">
        <article className="panel">
          <h3>Category Groups</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Name</th>
                  <th>Subcategories</th>
                </tr>
              </thead>
              <tbody>
                {categories.map((c) => (
                  <tr key={c.category_id}>
                    <td>{c.category_id}</td>
                    <td>{c.name}</td>
                    <td>{c.subcategory_count ?? 0}</td>
                  </tr>
                ))}
                {!loading && categories.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="muted">
                      No categories yet — configure Actual and click "Refresh from Actual".
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </article>

        <article className="panel">
          <h3>Categories</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Group</th>
                  <th>Name</th>
                </tr>
              </thead>
              <tbody>
                {subcategories.map((s) => (
                  <tr key={s.subcategory_id}>
                    <td>{s.subcategory_id}</td>
                    <td>{s.category_name ?? s.category_id}</td>
                    <td>{s.name}</td>
                  </tr>
                ))}
                {!loading && subcategories.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="muted">
                      No categories yet.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </article>
      </div>
    </section>
  );
}
