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
  const [severityFilter, setSeverityFilter] = useState("ALL");

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
    
    // Determine WebSocket URL based on current host
    const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsHost = window.location.hostname === "localhost" ? "localhost:8000" : window.location.host;
    const wsUrl = `${wsProtocol}//${wsHost}/ws/incidents`;
    
    console.log("Connecting to WebSocket:", wsUrl);
    const socket = new WebSocket(wsUrl);

    socket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      console.log("Real-time update received:", data);
      
      // For any incident event, refresh the list to ensure accurate state.
      // In a more complex app, we could update the specific item in state,
      // but reloading from the Redis-cached API is safer and still sub-100ms.
      loadItems();
    };

    socket.onclose = () => {
      console.warn("WebSocket closed. Falling back to polling in 5s...");
      const timer = setTimeout(loadItems, 5000);
      return () => clearTimeout(timer);
    };

    return () => {
      socket.close();
    };
  }, []);

  const severityRank = { P0: 0, P1: 1, P2: 2, P3: 3 };
  
  const filteredItems = items.filter(item => 
    severityFilter === "ALL" || item.severity === severityFilter
  );

  const sortedItems = [...filteredItems].sort((a, b) => {
    const diff = (severityRank[a.severity] ?? 99) - (severityRank[b.severity] ?? 99);
    return sortAsc ? diff : -diff;
  });

  const p0Count = items.filter((i) => i.severity === "P0").length;
  const totalSignals = items.reduce((sum, i) => sum + i.signal_count, 0);
  
  // Noise Reduction calculation
  const noiseReduction = totalSignals > 0 
    ? (((totalSignals - items.length) / totalSignals) * 100).toFixed(2)
    : "0.00";

  const mttrItems = items.filter((i) => i.mttr_minutes);
  const avgMttr = mttrItems.length > 0
    ? (mttrItems.reduce((sum, i) => sum + i.mttr_minutes, 0) / mttrItems.length).toFixed(1)
    : null;

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Live Incidents</h1>
          <p>{filteredItems.length} active work items {severityFilter !== "ALL" && `(filtered by ${severityFilter})`}</p>
        </div>
        <div className="header-actions">
          <Link to="/history" className="icon-text-button">
            <Clock size={16} /> View History
          </Link>
          <select 
            className="filter-select"
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value)}
          >
            <option value="ALL">All Severities</option>
            <option value="P0">P0 - Critical</option>
            <option value="P1">P1 - High</option>
            <option value="P2">P2 - Medium</option>
            <option value="P3">P3 - Low</option>
          </select>
          <button className="icon-text-button" type="button" onClick={loadItems}>
            <RefreshCw size={16} /> Refresh
          </button>
        </div>
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
            <span className="stat-label">Noise Reduction</span>
            <strong className="stat-value">{noiseReduction}%</strong>
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

      <div className="incident-grid-container">
        <div className="grid-header">
          <div className="grid-cell col-id">ID</div>
          <div className="grid-cell col-comp">Component</div>
          <div className="grid-cell col-type">Type</div>
          <div className="grid-cell col-sev">
            <button className="sort-button" type="button" onClick={() => setSortAsc((v) => !v)}>
              Severity <ArrowUpDown size={12} />
            </button>
          </div>
          <div className="grid-cell col-status">Status</div>
          <div className="grid-cell col-signals">Signals</div>
          <div className="grid-cell col-eff">Efficiency</div>
          <div className="grid-cell col-mttr">MTTR</div>
          <div className="grid-cell col-created">Created</div>
        </div>

        <div className="grid-body">
          {loading ? (
            <div className="grid-row-empty">Loading incidents...</div>
          ) : sortedItems.length === 0 ? (
            <div className="grid-row-empty">No active incidents</div>
          ) : (
            sortedItems.map((item) => (
              <div key={item.id} className={`grid-row row-${item.severity.toLowerCase()}`}>
                <div className="grid-cell col-id">
                  <Link to={`/incident/${item.id}`}>{item.id.slice(0, 8)}</Link>
                </div>
                <div className="grid-cell col-comp">{item.component_id}</div>
                <div className="grid-cell col-type">{item.component_type}</div>
                <div className="grid-cell col-sev">
                  <SeverityPill severity={item.severity} />
                </div>
                <div className="grid-cell col-status">
                  <StatusBadge status={item.status} />
                </div>
                <div className="grid-cell col-signals">
                  <div className="signals-badge">
                    <Signal size={12} /> {item.signal_count}
                  </div>
                </div>
                <div className="grid-cell col-eff">
                  <div className="efficiency-cell">
                    <strong>{item.signal_count > 1 ? (((item.signal_count - 1) / item.signal_count) * 100).toFixed(1) : "0.0"}%</strong>
                  </div>
                </div>
                <div className="grid-cell col-mttr">
                  {item.mttr_minutes ? `${item.mttr_minutes.toFixed(1)} min` : "—"}
                </div>
                <div className="grid-cell col-created">
                  {new Date(item.created_at).toLocaleString()}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </section>
  );
}
