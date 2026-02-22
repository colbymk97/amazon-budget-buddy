import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { formatMoney, getTransaction, getTransactionItems } from "../api";
import type { AmazonTransaction, OrderItem } from "../types";

export function TransactionDetailPage() {
  const { txnId = "" } = useParams();
  const [txn, setTxn] = useState<AmazonTransaction | null>(null);
  const [items, setItems] = useState<OrderItem[]>([]);

  useEffect(() => {
    if (!txnId) return;
    getTransaction(txnId).then(setTxn).catch(() => setTxn(null));
    getTransactionItems(txnId).then((r) => setItems(r.rows)).catch(() => setItems([]));
  }, [txnId]);

  if (!txn) return <p>Loading transaction...</p>;

  return (
    <section className="order-detail-layout">
      <p>
        <Link to="/transactions">← Back to Transactions</Link>
      </p>
      <div className="order-detail-grid">
        <article className="panel order-summary-card">
          <h2>Transaction Summary</h2>
          <p>
            <strong>Transaction ID:</strong> {txn.amazon_txn_id}
          </p>
          <p>
            <strong>Date:</strong> {txn.txn_date ?? "n/a"}
          </p>
          <p>
            <strong>Amount:</strong> {formatMoney(txn.amount_cents)}
          </p>
          <p title={txn.raw_label ?? ""}>
            <strong>Label:</strong> {txn.raw_label ?? "n/a"}
          </p>
          <p>
            <strong>Parent Order:</strong> <Link to={`/orders/${txn.order_id}`}>{txn.order_id}</Link>
          </p>
          <p>
            <strong>Order URL:</strong>{" "}
            <a href={txn.order_url ?? "#"} target="_blank" rel="noreferrer">
              {txn.order_url ?? "n/a"}
            </a>
          </p>
        </article>

        <article className="panel">
          <h3>Associated Items</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Item</th>
                  <th>Qty</th>
                  <th>Subtotal</th>
                  <th>Allocated</th>
                  <th>Title</th>
                </tr>
              </thead>
              <tbody>
                {items.map((i) => (
                  <tr key={i.item_id}>
                    <td>
                      <Link to={`/items/${i.item_id}`}>{i.item_id}</Link>
                    </td>
                    <td>{i.quantity}</td>
                    <td>{formatMoney(i.item_subtotal_cents)}</td>
                    <td>{formatMoney(i.allocated_amount_cents)}</td>
                    <td className="truncate-cell" title={i.title}>
                      {i.title}
                    </td>
                  </tr>
                ))}
                {items.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="muted">
                      No items found.
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
            <strong>Order ID:</strong> <Link to={`/orders/${txn.order_id}`}>{txn.order_id}</Link>
          </p>
          <p>
            <strong>Order Date:</strong> {txn.order_date ?? "n/a"}
          </p>
          <p>
            <strong>Order Total:</strong> {formatMoney(txn.order_total_cents)}
          </p>
          <p>
            <strong>Order Tax:</strong> {formatMoney(txn.tax_cents)}
          </p>
          <p>
            <strong>Payment Last4:</strong> {txn.payment_last4 ?? "n/a"}
          </p>
        </article>
      </div>
    </section>
  );
}
