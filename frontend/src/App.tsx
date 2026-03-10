import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { HomePage } from "./pages/HomePage";
import { OrdersPage } from "./pages/OrdersPage";
import { TransactionsPage } from "./pages/TransactionsPage";
import { ItemsPage } from "./pages/ItemsPage";
import { OrderDetailPage } from "./pages/OrderDetailPage";
import { TransactionDetailPage } from "./pages/TransactionDetailPage";
import { ItemDetailPage } from "./pages/ItemDetailPage";
import { BabySisterPage } from "./pages/BabySisterPage";
import { ReportsPage } from "./pages/ReportsPage";
import { AdminPage } from "./pages/AdminPage";

const navItems = [
  { to: "/", label: "Dashboard", meta: "Sync and health" },
  { to: "/orders", label: "Orders", meta: "Purchases ledger" },
  { to: "/transactions", label: "Transactions", meta: "Payment events" },
  { to: "/items", label: "Items", meta: "Line-item detail" },
  { to: "/reports", label: "Reports", meta: "Monthly analytics" },
  { to: "/admin", label: "Admin", meta: "Budget metadata" },
  { to: "/baby-sister", label: "Baby Sister", meta: "Bonus screen" }
] as const;

function sectionTitle(pathname: string): string {
  if (pathname === "/") return "Command Center";
  const match = navItems.find((item) => pathname === item.to || pathname.startsWith(`${item.to}/`));
  return match?.label ?? "Amazon Spending";
}

export function App() {
  const location = useLocation();

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <p className="eyebrow">Personal finance stack</p>
          <h1>Amazon Spending</h1>
          <p className="brand-copy">
            A darker, cleaner workspace for reviewing imports, transactions, and reporting as the app grows.
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
          Local-first data, API-backed UI
        </div>
      </aside>

      <div className="content-shell">
        <header className="topbar">
          <div>
            <p className="eyebrow">Workspace</p>
            <h2>{sectionTitle(location.pathname)}</h2>
          </div>
          <div className="topbar-meta">
            <span className="topbar-chip">SQLite source</span>
            <span className="topbar-chip">Built for iteration</span>
          </div>
        </header>

        <main>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/orders" element={<OrdersPage />} />
            <Route path="/orders/:orderId" element={<OrderDetailPage />} />
            <Route path="/transactions" element={<TransactionsPage />} />
            <Route path="/transactions/:txnId" element={<TransactionDetailPage />} />
            <Route path="/items" element={<ItemsPage />} />
            <Route path="/items/:itemId" element={<ItemDetailPage />} />
            <Route path="/reports" element={<ReportsPage />} />
            <Route path="/admin" element={<AdminPage />} />
            <Route path="/baby-sister" element={<BabySisterPage />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
