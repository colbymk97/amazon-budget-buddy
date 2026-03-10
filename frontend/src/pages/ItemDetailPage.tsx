import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { formatMoney, getItem, getItemTransactions } from "../api";
import type { RetailerTransaction, OrderItem } from "../types";

export function ItemDetailPage() {
  const { itemId = "" } = useParams();
  const [item, setItem] = useState<OrderItem | null>(null);
  const [txns, setTxns] = useState<RetailerTransaction[]>([]);

  useEffect(() => {
    if (!itemId) return;
    getItem(itemId).then(setItem).catch(() => setItem(null));
    getItemTransactions(itemId).then((r) => setTxns(r.rows)).catch(() => setTxns([]));
  }, [itemId]);

  if (!item) return <p>Loading item...</p>;

  return (
    <section className="order-detail-layout">
      <p>
        <Link to="/items">← Back to Order Items</Link>
      </p>
      <div className="order-detail-grid">
        <article className="panel order-summary-card">
          <h2>Item Summary</h2>
          <p>
            <strong>Item ID:</strong> {item.item_id}
          </p>
          <p title={item.title}>
            <strong>Title:</strong> {item.title}
          </p>
          <p>
            <strong>Qty:</strong> {item.quantity}
          </p>
          <p>
            <strong>Subtotal:</strong> {formatMoney(item.item_subtotal_cents)}
          </p>
          <p>
            <strong>Tax:</strong> {formatMoney(item.item_tax_cents)}
          </p>
          <p>
            <strong>Parent Order:</strong> <Link to={`/orders/${item.order_id}`}>{item.order_id}</Link>
          </p>
          <p>
            <strong>Order URL:</strong>{" "}
            <a href={item.order_url ?? "#"} target="_blank" rel="noreferrer">
              {item.order_url ?? "n/a"}
            </a>
          </p>
        </article>

        <article className="panel">
          <h3>Associated Transactions</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Transaction</th>
                  <th>Date</th>
                  <th>Amount</th>
                  <th>Allocated</th>
                  <th>Label</th>
                </tr>
              </thead>
              <tbody>
                {txns.map((t) => (
                  <tr key={t.retailer_txn_id}>
                    <td>
                      <Link to={`/transactions/${t.retailer_txn_id}`}>{t.retailer_txn_id}</Link>
                    </td>
                    <td>{t.txn_date ?? "n/a"}</td>
                    <td>{formatMoney(t.amount_cents)}</td>
                    <td>{formatMoney(t.allocated_amount_cents)}</td>
                    <td className="truncate-cell" title={t.raw_label ?? ""}>
                      {t.raw_label ?? "n/a"}
                    </td>
                  </tr>
                ))}
                {txns.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="muted">
                      No transactions found.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </article>

        <article className="panel">
          <h3>Order Context</h3>
          <p>
            <strong>Order ID:</strong> <Link to={`/orders/${item.order_id}`}>{item.order_id}</Link>
          </p>
          <p>
            <strong>Order Date:</strong> {item.order_date ?? "n/a"}
          </p>
          <p>
            <strong>Order Total:</strong> {formatMoney(item.order_total_cents)}
          </p>
          <p>
            <strong>Order Tax:</strong> {formatMoney(item.tax_cents)}
          </p>
          <p>
            <strong>Primary Txn:</strong>{" "}
            {item.retailer_transaction_id ? (
              <Link to={`/transactions/${item.retailer_transaction_id}`}>{item.retailer_transaction_id}</Link>
            ) : (
              "n/a"
            )}
          </p>
        </article>
      </div>
    </section>
  );
}
