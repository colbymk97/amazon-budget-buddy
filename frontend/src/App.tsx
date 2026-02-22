import { NavLink, Route, Routes } from "react-router-dom";
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

export function App() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <h1>Amazon Spending</h1>
        <nav>
          <NavLink to="/">Home</NavLink>
          <NavLink to="/orders">Orders</NavLink>
          <NavLink to="/transactions">Transactions</NavLink>
          <NavLink to="/items">Order Items</NavLink>
          <NavLink to="/reports">Reports</NavLink>
          <NavLink to="/admin">Admin</NavLink>
          <NavLink to="/baby-sister">BABY SISTER</NavLink>
        </nav>
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
  );
}
