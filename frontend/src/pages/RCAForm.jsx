import { ArrowLeft, Wand2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getWorkItem, submitRCA } from "../api.js";

const categories = ["Infrastructure", "Code Deployment", "Configuration Change", "External Dependency", "Unknown"];

export default function RCAForm() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [incident, setIncident] = useState(null);
  const [form, setForm] = useState({
    incident_start: "",
    incident_end: "",
    root_cause_category: "Infrastructure",
    fix_applied: "",
    prevention_steps: ""
  });
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    getWorkItem(id).then(setIncident).catch((err) => setError(err.message));
  }, [id]);

  function update(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  function suggestRCA() {
    const signalText = incident?.signals?.[0]?.error_message || "Repeated failure signals";
    setForm((current) => ({
      ...current,
      root_cause_category: current.root_cause_category || "Unknown",
      fix_applied: current.fix_applied || `Mitigated incident after reviewing signal pattern: ${signalText}`,
      prevention_steps: current.prevention_steps || "Tune alert thresholds, add runbook automation, and review component capacity limits."
    }));
  }

  async function onSubmit(event) {
    event.preventDefault();
    setError("");
    setMessage("");
    if (!form.incident_start || !form.incident_end || !form.fix_applied.trim() || !form.prevention_steps.trim()) {
      setError("All fields are required");
      return;
    }
    try {
      const payload = {
        ...form,
        incident_start: new Date(form.incident_start).toISOString(),
        incident_end: new Date(form.incident_end).toISOString()
      };
      await submitRCA(id, payload);
      // Redirect back to incident detail so user can see the "Close" button
      navigate(`/incident/${id}`);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <section className="page narrow-page">
      <Link to={`/incident/${id}`} className="back-link"><ArrowLeft size={16} /> Incident</Link>
      <div className="page-header">
        <div>
          <h1>Root Cause Analysis</h1>
          <p>{incident?.component_id || id}</p>
        </div>
        <button type="button" className="icon-text-button" onClick={suggestRCA} disabled={!incident}>
          <Wand2 size={16} /> Suggest
        </button>
      </div>
      {error && <div className="error-banner">{error}</div>}
      {message && <div className="success-banner">{message}</div>}
      <form className="form" onSubmit={onSubmit}>
        <label>Incident Start<input type="datetime-local" value={form.incident_start} onChange={(e) => update("incident_start", e.target.value)} required /></label>
        <label>Incident End<input type="datetime-local" value={form.incident_end} onChange={(e) => update("incident_end", e.target.value)} required /></label>
        <label>Root Cause Category<select value={form.root_cause_category} onChange={(e) => update("root_cause_category", e.target.value)}>{categories.map((category) => <option key={category}>{category}</option>)}</select></label>
        <label>Fix Applied<textarea rows="5" value={form.fix_applied} onChange={(e) => update("fix_applied", e.target.value)} required /></label>
        <label>Prevention Steps<textarea rows="5" value={form.prevention_steps} onChange={(e) => update("prevention_steps", e.target.value)} required /></label>
        <button className="primary-button" type="submit">Submit RCA</button>
      </form>
    </section>
  );
}
