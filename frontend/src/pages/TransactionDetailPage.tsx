import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { assignTransactionBudget, formatMoney, getTransaction, getTransactionItems, listBudgetSubcategories } from "../api";
import type { RetailerTransaction, OrderItem, BudgetSubcategory } from "../types";
import { Panel } from "../components/Panel";
import { DetailSummaryList } from "../components/DetailSummaryList";
import { SimpleTable } from "../components/SimpleTable";

export function TransactionDetailPage() {
  const { txnId = "" } = useParams();
  const [txn, setTxn] = useState<RetailerTransaction | null>(null);
  const [items, setItems] = useState<OrderItem[]>([]);
  const [subcategories, setSubcategories] = useState<BudgetSubcategory[]>([]);
  const [savingCategory, setSavingCategory] = useState(false);
  const [categoryError, setCategoryError] = useState("");

  useEffect(() => {
    if (!txnId) return;
    getTransaction(txnId).then(setTxn).catch(() => setTxn(null));
    getTransactionItems(txnId).then((r) => setItems(r.rows)).catch(() => setItems([]));
  }, [txnId]);

  useEffect(() => {
    listBudgetSubcategories()
      .then((r) => setSubcategories(r.rows))
      .catch(() => setSubcategories([]));
  }, []);

  const onCategoryChange = async (subcategoryId: string) => {
    if (!txn) return;
    setSavingCategory(true);
    setCategoryError("");
    try {
      if (subcategoryId === "") {
        const updated = await assignTransactionBudget(txn.retailer_txn_id, {
          budget_category_id: null,
          budget_subcategory_id: null,
        });
        setTxn(updated);
        return;
      }
      const subcategory = subcategories.find((s) => String(s.subcategory_id) === subcategoryId);
      const updated = await assignTransactionBudget(txn.retailer_txn_id, {
        budget_category_id: subcategory?.category_id ?? null,
        budget_subcategory_id: Number(subcategoryId),
      });
      setTxn(updated);
    } catch {
      setCategoryError("Could not update category.");
    } finally {
      setSavingCategory(false);
    }
  };

  if (!txn) return <p>Loading transaction...</p>;

  return (
    <section className="transaction-layout">
      <p>
        <Link to="/transactions">← Back to Transactions</Link>
      </p>

      <Panel>
        <div className="txn-header-row">
          <div>
            <h2 className="txn-amount">{formatMoney(txn.amount_cents)}</h2>
            <p className="muted">
              {txn.txn_date ?? "n/a"} · {txn.raw_label ?? "n/a"} · {txn.retailer ?? "amazon"}
              {txn.payment_last4 ? ` · ****${txn.payment_last4}` : ""}
            </p>
          </div>
          <div className="txn-category-field">
            <label className="eyebrow" htmlFor="txn-category">
              Category
            </label>
            <select
              id="txn-category"
              value={txn.budget_subcategory_id ?? ""}
              disabled={savingCategory}
              onChange={(e) => onCategoryChange(e.target.value)}
            >
              <option value="">Uncategorized</option>
              {subcategories.map((s) => (
                <option key={s.subcategory_id} value={s.subcategory_id}>
                  {s.category_name ? `${s.category_name} › ${s.name}` : s.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="summary-facts">
          <DetailSummaryList
            items={[
              { label: "Transaction ID", value: txn.retailer_txn_id },
              {
                label: "Parent Order",
                value: <Link to={`/orders/${txn.order_id}`}>{txn.order_id}</Link>,
              },
              {
                label: "Order URL",
                value: (
                  <a href={txn.order_url ?? "#"} target="_blank" rel="noreferrer">
                    View on Amazon ↗
                  </a>
                ),
              },
            ]}
          />
        </div>
        {categoryError ? <p className="error">{categoryError}</p> : null}
      </Panel>

      <Panel>
        <h3>Items in this Transaction ({items.length})</h3>
        <SimpleTable
          columns={[
            {
              header: "Title",
              cell: (i: OrderItem) => i.title,
            },
            { header: "Qty", cell: (i) => i.quantity },
            { header: "Subtotal", cell: (i) => formatMoney(i.item_subtotal_cents) },
            { header: "Allocated", cell: (i) => formatMoney(i.allocated_amount_cents) },
            { header: "Item", cell: (i) => <Link to={`/items/${i.item_id}`}>{i.item_id}</Link> },
          ]}
          rows={items}
          rowKey={(i) => i.item_id}
          emptyMessage="No items found."
        />
        <p className="muted">
          Categories are mirrored from Actual Budget (see Budget Categories). New categories sync to Actual
          once, the first time this transaction reaches Actual — never overwritten after that.
        </p>
      </Panel>

      <Panel>
        <h3>Order Context</h3>
        <div className="summary-facts">
          <DetailSummaryList
            items={[
              { label: "Order ID", value: <Link to={`/orders/${txn.order_id}`}>{txn.order_id}</Link> },
              { label: "Order Date", value: txn.order_date ?? "n/a" },
              { label: "Order Total", value: formatMoney(txn.order_total_cents) },
              { label: "Order Tax", value: formatMoney(txn.tax_cents) },
              { label: "Payment Last4", value: txn.payment_last4 ?? "n/a" },
            ]}
          />
        </div>
      </Panel>
    </section>
  );
}
