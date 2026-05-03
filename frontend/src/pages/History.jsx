import { ArrowLeft, Clock } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getWorkItems } from "../api.js";
import SeverityPill from "../components/SeverityPill.jsx";
import StatusBadge from "../components/StatusBadge.jsx";

export default function History() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getWorkItems("CLOSED")
      .then(setItems)
      .finally(() => setLoading(false));
  }, []);

  return (
    <section className="page">
      <Link to="/" className="back-link"><ArrowLeft size={16} /> Dashboard</Link>
      <div className="page-header">
        <div>
          <h1>Incident History</h1>
          <p>Archived and closed work items</p>
        </div>
      </div>

      <div className="incident-grid-container">
        <div className="grid-header history-grid">
          <div className="grid-cell">ID</div>
          <div className="grid-cell">Component</div>
          <div className="grid-cell">Type</div>
          <div className="grid-cell">Severity</div>
          <div className="grid-cell">Status</div>
          <div className="grid-cell">Signals</div>
          <div className="grid-cell">MTTR</div>
          <div className="grid-cell">Closed At</div>
        </div>
        <div className="grid-body">
          {loading ? (
            <div className="grid-row-empty">Loading history...</div>
          ) : items.length === 0 ? (
            <div className="grid-row-empty">No archived incidents found.</div>
          ) : (
            items.map((item) => (
              <div key={item.id} className="grid-row history-grid">
                <div className="grid-cell">
                  <Link to={`/incident/${item.id}`}>{item.id.slice(0, 8)}</Link>
                </div>
                <div className="grid-cell"><strong>{item.component_id}</strong></div>
                <div className="grid-cell">{item.component_type}</div>
                <div className="grid-cell"><SeverityPill severity={item.severity} /></div>
                <div className="grid-cell"><StatusBadge status={item.status} /></div>
                <div className="grid-cell centered-badge">{item.signal_count}</div>
                <div className="grid-cell centered-badge">
                  {item.mttr_minutes ? `${item.mttr_minutes.toFixed(1)} min` : "—"}
                </div>
                <div className="grid-cell">{new Date(item.updated_at).toLocaleString()}</div>
              </div>
            ))
          )}
        </div>
      </div>
    </section>
  );
}
