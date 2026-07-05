import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { formatMoney, getOrder, getOrderItems, getOrderTransactions } from "../api";
import type { RetailerTransaction, Order, OrderItem } from "../types";
import { Panel } from "../components/Panel";
import { DetailSummaryList } from "../components/DetailSummaryList";
import { SimpleTable } from "../components/SimpleTable";

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
        <Panel className="order-summary-card">
          <h2>Order Summary</h2>
          <DetailSummaryList
            items={[
              { label: "Order ID", value: order.order_id },
              { label: "Retailer", value: order.retailer ?? "amazon" },
              { label: "Date", value: order.order_date },
              { label: "Total", value: formatMoney(order.order_total_cents) },
              { label: "Tax", value: formatMoney(order.tax_cents) },
              { label: "Shipping", value: formatMoney(order.shipping_cents) },
              {
                label: "Order URL",
                value: (
                  <a href={order.order_url ?? "#"} target="_blank" rel="noreferrer">
                    {order.order_url ?? "n/a"}
                  </a>
                ),
              },
            ]}
          />
        </Panel>

        <Panel>
          <h3>Associated Transactions</h3>
          <SimpleTable
            columns={[
              {
                header: "Transaction",
                cell: (t: RetailerTransaction) => (
                  <Link to={`/transactions/${t.retailer_txn_id}`}>{t.retailer_txn_id}</Link>
                ),
              },
              { header: "Date", cell: (t) => t.txn_date ?? "n/a" },
              { header: "Amount", cell: (t) => formatMoney(t.amount_cents) },
            ]}
            rows={txns}
            rowKey={(t) => t.retailer_txn_id}
            emptyMessage="No transactions found."
          />
        </Panel>

        <Panel>
          <h3>Associated Items</h3>
          <SimpleTable
            columns={[
              { header: "Item", cell: (i: OrderItem) => <Link to={`/items/${i.item_id}`}>{i.item_id}</Link> },
              { header: "Qty", cell: (i) => i.quantity },
              { header: "Subtotal", cell: (i) => formatMoney(i.item_subtotal_cents) },
              { header: "Title", cell: (i) => i.title, className: "truncate-cell", title: (i) => i.title },
            ]}
            rows={items}
            rowKey={(i) => i.item_id}
            emptyMessage="No items found."
          />
        </Panel>
      </div>
    </section>
  );
}
