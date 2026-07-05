import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { HomePage } from "./pages/HomePage";
import { StatusPage } from "./pages/StatusPage";
import { OrdersPage } from "./pages/OrdersPage";
import { TransactionsPage } from "./pages/TransactionsPage";
import { ItemsPage } from "./pages/ItemsPage";
import { OrderDetailPage } from "./pages/OrderDetailPage";
import { TransactionDetailPage } from "./pages/TransactionDetailPage";
import { ItemDetailPage } from "./pages/ItemDetailPage";
import { ReportsPage } from "./pages/ReportsPage";
import { AdminPage } from "./pages/AdminPage";

const navItems = [
  { to: "/", label: "Dashboard", meta: "Spend overview" },
  { to: "/status", label: "Status", meta: "Sync & import health" },
  { to: "/orders", label: "Orders", meta: "Purchases ledger" },
  { to: "/transactions", label: "Transactions", meta: "Payment events" },
  { to: "/items", label: "Items", meta: "Line-item detail" },
  { to: "/reports", label: "Reports", meta: "Monthly analytics" },
  { to: "/admin", label: "Budget Categories", meta: "Mirrored from Actual" }
] as const;

function sectionTitle(pathname: string): string {
  const match = navItems.find((item) => pathname === item.to || pathname.startsWith(`${item.to}/`));
  return match?.label ?? "Budget Buddy";
}

export function App() {
  const location = useLocation();

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <p className="eyebrow">Local-first · Open source</p>
          <h1>Budget Buddy</h1>
          <p className="brand-copy">
            Tracks your own retailer order history and reconciles it against Actual Budget — all from a
            SQLite database that stays on this machine.
          </p>
        </div>

        <nav className="primary-nav" aria-label="Primary">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
            >
              <span>{item.label}</span>
              <small>{item.meta}</small>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-note">
          <span className="status-dot" />
          All data stays local — nothing leaves this machine.
        </div>
      </aside>

      <div className="content-shell">
        <header className="topbar">
          <div>
            <h2>{sectionTitle(location.pathname)}</h2>
          </div>
        </header>

        <main>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/status" element={<StatusPage />} />
            <Route path="/orders" element={<OrdersPage />} />
            <Route path="/orders/:orderId" element={<OrderDetailPage />} />
            <Route path="/transactions" element={<TransactionsPage />} />
            <Route path="/transactions/:txnId" element={<TransactionDetailPage />} />
            <Route path="/items" element={<ItemsPage />} />
            <Route path="/items/:itemId" element={<ItemDetailPage />} />
            <Route path="/reports" element={<ReportsPage />} />
            <Route path="/admin" element={<AdminPage />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
