import { RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getWorkItems } from "../api.js";
import SeverityPill from "../components/SeverityPill.jsx";
import StatusBadge from "../components/StatusBadge.jsx";

export default function Dashboard() {
  const [items, setItems] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

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
      {error && <div className="error-banner">{error}</div>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Component</th>
              <th>Type</th>
              <th>Severity</th>
              <th>Status</th>
              <th>Signal Count</th>
              <th>Created At</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan="7">Loading incidents...</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan="7">No active incidents</td></tr>
            ) : (
              items.map((item) => (
                <tr key={item.id} className={`row-${item.severity.toLowerCase()}`}>
                  <td><Link to={`/incident/${item.id}`}>{item.id.slice(0, 8)}</Link></td>
                  <td>{item.component_id}</td>
                  <td>{item.component_type}</td>
                  <td><SeverityPill severity={item.severity} /></td>
                  <td><StatusBadge status={item.status} /></td>
                  <td>{item.signal_count}</td>
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
