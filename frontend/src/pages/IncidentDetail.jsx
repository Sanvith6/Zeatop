import { ArrowLeft, CheckCircle2, PlayCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getWorkItem, transitionWorkItem } from "../api.js";
import SeverityPill from "../components/SeverityPill.jsx";
import StatusBadge from "../components/StatusBadge.jsx";

export default function IncidentDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [incident, setIncident] = useState(null);
  const [activeTab, setActiveTab] = useState("signals");
  const [error, setError] = useState("");

  async function loadIncident() {
    try {
      setError("");
      setIncident(await getWorkItem(id));
    } catch (err) {
      setError(err.message);
    }
  }

  async function transition(newState) {
    try {
      await transitionWorkItem(id, newState);
      await loadIncident();
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    loadIncident();
  }, [id]);

  if (!incident) {
    return <section className="page"><Link to="/" className="back-link"><ArrowLeft size={16} /> Dashboard</Link>{error || "Loading incident..."}</section>;
  }

  return (
    <section className="page">
      <Link to="/" className="back-link"><ArrowLeft size={16} /> Dashboard</Link>
      <div className="incident-summary">
        <div>
          <h1>{incident.component_id}</h1>
          <p>{incident.id}</p>
        </div>
        <div className="summary-actions">
          <SeverityPill severity={incident.severity} />
          <StatusBadge status={incident.status} />
        </div>
      </div>
      {error && <div className="error-banner">{error}</div>}
      <div className="meta-grid">
        <div><span>Type</span><strong>{incident.component_type}</strong></div>
        <div><span>Signals</span><strong>{incident.signal_count}</strong></div>
        <div><span>Created</span><strong>{new Date(incident.created_at).toLocaleString()}</strong></div>
        <div><span>MTTR</span><strong>{incident.mttr_minutes ? `${incident.mttr_minutes.toFixed(1)} min` : "Pending"}</strong></div>
      </div>
      <div className="action-row">
        <button type="button" className="icon-text-button" disabled={incident.status !== "OPEN"} onClick={() => transition("INVESTIGATING")}>
          <PlayCircle size={16} /> Start Investigating
        </button>
        <button type="button" className="icon-text-button" disabled={incident.status !== "INVESTIGATING"} onClick={() => transition("RESOLVED")}>
          <CheckCircle2 size={16} /> Mark Resolved
        </button>
        {incident.status === "RESOLVED" && <button type="button" className="primary-button" onClick={() => navigate(`/incident/${id}/rca`)}>RCA</button>}
      </div>
      <div className="tabs">
        <button className={activeTab === "signals" ? "active" : ""} onClick={() => setActiveTab("signals")}>Raw Signals</button>
        <button className={activeTab === "timeline" ? "active" : ""} onClick={() => setActiveTab("timeline")}>Timeline</button>
      </div>
      {activeTab === "signals" ? <SignalsTable signals={incident.signals} /> : <Timeline events={incident.timeline} />}
    </section>
  );
}

function SignalsTable({ signals }) {
  return (
    <div className="table-wrap">
      <table>
        <thead><tr><th>Time</th><th>Component</th><th>Type</th><th>Severity</th><th>Error</th></tr></thead>
        <tbody>
          {signals.length === 0 ? <tr><td colSpan="5">No linked signals yet</td></tr> : signals.map((signal) => (
            <tr key={signal._id}>
              <td>{new Date(signal.timestamp).toLocaleString()}</td>
              <td>{signal.component_id}</td>
              <td>{signal.component_type}</td>
              <td><SeverityPill severity={signal.severity} /></td>
              <td>{signal.error_message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Timeline({ events }) {
  return (
    <div className="timeline">
      {events.length === 0 ? <p>No status history</p> : events.map((event, index) => (
        <div className="timeline-row" key={`${event.to_status}-${event.changed_at}-${index}`}>
          <span>{new Date(event.changed_at).toLocaleString()}</span>
          <strong>{event.from_status || "CREATED"} to {event.to_status}</strong>
        </div>
      ))}
    </div>
  );
}
