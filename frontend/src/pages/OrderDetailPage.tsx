import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { formatMoney, getOrder, getOrderItems, getOrderTransactions } from "../api";
import type { RetailerTransaction, Order, OrderItem } from "../types";

export function OrderDetailPage() {
  const { orderId = "" } = useParams();
  const [order, setOrder] = useState<Order | null>(null);
  const [txns, setTxns] = useState<RetailerTransaction[]>([]);
  const [items, setItems] = useState<OrderItem[]>([]);

  useEffect(() => {
    if (!orderId) return;
    getOrder(orderId).then(setOrder).catch(() => setOrder(null));
    getOrderTransactions(orderId).then((r) => setTxns(r.rows)).catch(() => setTxns([]));
    getOrderItems(orderId).then((r) => setItems(r.rows)).catch(() => setItems([]));
  }, [orderId]);

  if (!order) return <p>Loading order...</p>;

  return (
    <section className="order-detail-layout">
      <p>
        <Link to="/orders">← Back to Orders</Link>
      </p>
      <div className="order-detail-grid">
        <article className="panel order-summary-card">
          <h2>Order Summary</h2>
          <p>
            <strong>Order ID:</strong> {order.order_id}
          </p>
          <p>
            <strong>Retailer:</strong> {order.retailer ?? "amazon"}
          </p>
          <p>
            <strong>Date:</strong> {order.order_date}
          </p>
          <p>
            <strong>Total:</strong> {formatMoney(order.order_total_cents)}
          </p>
          <p>
            <strong>Tax:</strong> {formatMoney(order.tax_cents)}
          </p>
          <p>
            <strong>Shipping:</strong> {formatMoney(order.shipping_cents)}
          </p>
          <p>
            <strong>Order URL:</strong>{" "}
            <a href={order.order_url ?? "#"} target="_blank" rel="noreferrer">
              {order.order_url ?? "n/a"}
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
                  </tr>
                ))}
                {txns.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="muted">
                      No transactions found.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
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
                    <td className="truncate-cell" title={i.title}>
                      {i.title}
                    </td>
                  </tr>
                ))}
                {items.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="muted">
                      No items found.
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
