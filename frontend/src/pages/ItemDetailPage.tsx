import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { formatMoney, getItem, getItemTransactions } from "../api";
import type { RetailerTransaction, OrderItem } from "../types";
import { Panel } from "../components/Panel";
import { DetailSummaryList } from "../components/DetailSummaryList";
import { SimpleTable } from "../components/SimpleTable";

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
        <Panel className="order-summary-card">
          <h2>Item Summary</h2>
          <DetailSummaryList
            items={[
              { label: "Item ID", value: item.item_id },
              { label: "Title", value: item.title, title: item.title },
              { label: "Qty", value: item.quantity },
              { label: "Subtotal", value: formatMoney(item.item_subtotal_cents) },
              { label: "Tax", value: formatMoney(item.item_tax_cents) },
              { label: "Parent Order", value: <Link to={`/orders/${item.order_id}`}>{item.order_id}</Link> },
              {
                label: "Order URL",
                value: (
                  <a href={item.order_url ?? "#"} target="_blank" rel="noreferrer">
                    {item.order_url ?? "n/a"}
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
              { header: "Allocated", cell: (t) => formatMoney(t.allocated_amount_cents) },
              {
                header: "Label",
                cell: (t) => t.raw_label ?? "n/a",
                className: "truncate-cell",
                title: (t) => t.raw_label ?? "",
              },
            ]}
            rows={txns}
            rowKey={(t) => t.retailer_txn_id}
            emptyMessage="No transactions found."
          />
        </Panel>

        <Panel>
          <h3>Order Context</h3>
          <DetailSummaryList
            items={[
              { label: "Order ID", value: <Link to={`/orders/${item.order_id}`}>{item.order_id}</Link> },
              { label: "Order Date", value: item.order_date ?? "n/a" },
              { label: "Order Total", value: formatMoney(item.order_total_cents) },
              { label: "Order Tax", value: formatMoney(item.tax_cents) },
              {
                label: "Primary Txn",
                value: item.retailer_transaction_id ? (
                  <Link to={`/transactions/${item.retailer_transaction_id}`}>{item.retailer_transaction_id}</Link>
                ) : (
                  "n/a"
                ),
              },
            ]}
          />
        </Panel>
      </div>
    </section>
  );
}
