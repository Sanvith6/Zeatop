import { Activity, AlertTriangle, Clock, RefreshCw, Signal, ArrowUpDown } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getWorkItems } from "../api.js";
import SeverityPill from "../components/SeverityPill.jsx";
import StatusBadge from "../components/StatusBadge.jsx";

export default function Dashboard() {
  const [items, setItems] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [sortAsc, setSortAsc] = useState(true);

  async function loadItems() {
    try {
      setError("");
      setItems(await getWorkItems());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadItems();
    const timer = setInterval(loadItems, 5000);
    return () => clearInterval(timer);
  }, []);

  const severityRank = { P0: 0, P1: 1, P2: 2, P3: 3 };
  const sortedItems = [...items].sort((a, b) => {
    const diff = (severityRank[a.severity] ?? 99) - (severityRank[b.severity] ?? 99);
    return sortAsc ? diff : -diff;
  });

  const p0Count = items.filter((i) => i.severity === "P0").length;
  const totalSignals = items.reduce((sum, i) => sum + i.signal_count, 0);
  const mttrItems = items.filter((i) => i.mttr_minutes);
  const avgMttr = mttrItems.length > 0
    ? (mttrItems.reduce((sum, i) => sum + i.mttr_minutes, 0) / mttrItems.length).toFixed(1)
    : null;

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Live Incidents</h1>
          <p>{items.length} active work items</p>
        </div>
        <button className="icon-text-button" type="button" onClick={loadItems}>
          <RefreshCw size={16} /> Refresh
        </button>
      </div>

      {/* Stats cards */}
      <div className="stats-grid" id="dashboard-stats">
        <div className="stat-card stat-incidents">
          <div className="stat-icon"><Activity size={20} /></div>
          <div className="stat-content">
            <span className="stat-label">Active Incidents</span>
            <strong className="stat-value">{items.length}</strong>
          </div>
        </div>
        <div className="stat-card stat-critical">
          <div className="stat-icon"><AlertTriangle size={20} /></div>
          <div className="stat-content">
            <span className="stat-label">P0 Critical</span>
            <strong className="stat-value">{p0Count}</strong>
          </div>
        </div>
        <div className="stat-card stat-signals">
          <div className="stat-icon"><Signal size={20} /></div>
          <div className="stat-content">
            <span className="stat-label">Total Signals</span>
            <strong className="stat-value">{totalSignals.toLocaleString()}</strong>
          </div>
        </div>
        <div className="stat-card stat-mttr">
          <div className="stat-icon"><Clock size={20} /></div>
          <div className="stat-content">
            <span className="stat-label">Avg MTTR</span>
            <strong className="stat-value">{avgMttr ? `${avgMttr} min` : "—"}</strong>
          </div>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Component</th>
              <th>Type</th>
              <th>
                <button className="sort-button" type="button" onClick={() => setSortAsc((v) => !v)}>
                  Severity <ArrowUpDown size={12} />
                </button>
              </th>
              <th>Status</th>
              <th>Signals</th>
              <th>MTTR</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan="8">Loading incidents...</td></tr>
            ) : sortedItems.length === 0 ? (
              <tr><td colSpan="8">No active incidents</td></tr>
            ) : (
              sortedItems.map((item) => (
                <tr key={item.id} className={`row-${item.severity.toLowerCase()}`}>
                  <td><Link to={`/incident/${item.id}`}>{item.id.slice(0, 8)}</Link></td>
                  <td>{item.component_id}</td>
                  <td>{item.component_type}</td>
                  <td><SeverityPill severity={item.severity} /></td>
                  <td><StatusBadge status={item.status} /></td>
                  <td>{item.signal_count}</td>
                  <td>{item.mttr_minutes ? `${item.mttr_minutes.toFixed(1)} min` : "—"}</td>
                  <td>{new Date(item.created_at).toLocaleString()}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
