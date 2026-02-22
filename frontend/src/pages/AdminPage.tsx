import { useEffect, useMemo, useState } from "react";
import {
  createBudgetCategory,
  createBudgetSubcategory,
  listBudgetCategories,
  listBudgetSubcategories
} from "../api";
import type { BudgetCategory, BudgetSubcategory } from "../types";

export function AdminPage() {
  const [categories, setCategories] = useState<BudgetCategory[]>([]);
  const [subcategories, setSubcategories] = useState<BudgetSubcategory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [categoryName, setCategoryName] = useState("");
  const [categoryDescription, setCategoryDescription] = useState("");
  const [subcategoryCategoryId, setSubcategoryCategoryId] = useState<number | "">("");
  const [subcategoryName, setSubcategoryName] = useState("");
  const [subcategoryDescription, setSubcategoryDescription] = useState("");
  const [savingCategory, setSavingCategory] = useState(false);
  const [savingSubcategory, setSavingSubcategory] = useState(false);

  const loadAll = async () => {
    setLoading(true);
    setError("");
    try {
      const [c, s] = await Promise.all([listBudgetCategories(), listBudgetSubcategories()]);
      setCategories(c.rows);
      setSubcategories(s.rows);
      if (c.rows.length > 0 && subcategoryCategoryId === "") {
        setSubcategoryCategoryId(c.rows[0].category_id);
      }
    } catch {
      setError("Failed to load budget metadata.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAll();
  }, []);

  const categoryOptions = useMemo(() => categories, [categories]);

  const onCreateCategory = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!categoryName.trim()) return;
    setError("");
    setSavingCategory(true);
    try {
      await createBudgetCategory({
        name: categoryName.trim(),
        description: categoryDescription.trim() || undefined
      });
      setCategoryName("");
      setCategoryDescription("");
      await loadAll();
    } catch {
      setError("Could not create category (maybe duplicate name).");
    } finally {
      setSavingCategory(false);
    }
  };

  const onCreateSubcategory = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!subcategoryName.trim() || subcategoryCategoryId === "") return;
    setError("");
    setSavingSubcategory(true);
    try {
      await createBudgetSubcategory({
        category_id: Number(subcategoryCategoryId),
        name: subcategoryName.trim(),
        description: subcategoryDescription.trim() || undefined
      });
      setSubcategoryName("");
      setSubcategoryDescription("");
      await loadAll();
    } catch {
      setError("Could not create subcategory (maybe duplicate in category).");
    } finally {
      setSavingSubcategory(false);
    }
  };

  return (
    <section className="report-layout">
      <article className="panel">
        <h2>Admin: Budget Metadata</h2>
        <p className="muted">Create and manage categories/subcategories used for transaction budgeting.</p>
      </article>

      <div className="admin-grid">
        <article className="panel">
          <h3>Add Category</h3>
          <form className="admin-form" onSubmit={onCreateCategory}>
            <input
              placeholder="Category name (e.g. Groceries)"
              value={categoryName}
              onChange={(e) => setCategoryName(e.target.value)}
            />
            <input
              placeholder="Description (optional)"
              value={categoryDescription}
              onChange={(e) => setCategoryDescription(e.target.value)}
            />
            <button type="submit" disabled={savingCategory || !categoryName.trim()}>
              {savingCategory ? "Saving..." : "Create Category"}
            </button>
          </form>
        </article>

        <article className="panel">
          <h3>Add Subcategory</h3>
          <form className="admin-form" onSubmit={onCreateSubcategory}>
            <select
              value={subcategoryCategoryId}
              onChange={(e) => setSubcategoryCategoryId(e.target.value ? Number(e.target.value) : "")}
            >
              <option value="">Select category</option>
              {categoryOptions.map((c) => (
                <option key={c.category_id} value={c.category_id}>
                  {c.name}
                </option>
              ))}
            </select>
            <input
              placeholder="Subcategory name (e.g. Produce)"
              value={subcategoryName}
              onChange={(e) => setSubcategoryName(e.target.value)}
            />
            <input
              placeholder="Description (optional)"
              value={subcategoryDescription}
              onChange={(e) => setSubcategoryDescription(e.target.value)}
            />
            <button
              type="submit"
              disabled={savingSubcategory || subcategoryCategoryId === "" || !subcategoryName.trim()}
            >
              {savingSubcategory ? "Saving..." : "Create Subcategory"}
            </button>
          </form>
        </article>
      </div>

      {loading ? <p>Loading...</p> : null}
      {error ? <p className="error">{error}</p> : null}

      <div className="admin-grid">
        <article className="panel">
          <h3>Categories</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Name</th>
                  <th>Description</th>
                  <th>Subcategories</th>
                </tr>
              </thead>
              <tbody>
                {categories.map((c) => (
                  <tr key={c.category_id}>
                    <td>{c.category_id}</td>
                    <td>{c.name}</td>
                    <td>{c.description ?? "n/a"}</td>
                    <td>{c.subcategory_count ?? 0}</td>
                  </tr>
                ))}
                {!loading && categories.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="muted">
                      No categories yet.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </article>

        <article className="panel">
          <h3>Subcategories</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Category</th>
                  <th>Name</th>
                  <th>Description</th>
                </tr>
              </thead>
              <tbody>
                {subcategories.map((s) => (
                  <tr key={s.subcategory_id}>
                    <td>{s.subcategory_id}</td>
                    <td>{s.category_name ?? s.category_id}</td>
                    <td>{s.name}</td>
                    <td>{s.description ?? "n/a"}</td>
                  </tr>
                ))}
                {!loading && subcategories.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="muted">
                      No subcategories yet.
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
