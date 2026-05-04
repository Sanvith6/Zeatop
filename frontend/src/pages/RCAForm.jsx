import { ArrowLeft, Loader2, Wand2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getWorkItem, submitRCA, suggestAI_RCA } from "../api.js";

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
  const [fieldErrors, setFieldErrors] = useState({});
  const [isSuggesting, setIsSuggesting] = useState(false);
  const [isFallback, setIsFallback] = useState(false);

  useEffect(() => {
    getWorkItem(id).then(setIncident).catch((err) => setError(err.message));
  }, [id]);

  function update(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
    // Clear field error when user starts typing
    if (fieldErrors[field]) {
      setFieldErrors((current) => ({ ...current, [field]: "" }));
    }
  }

  async function suggestRCA() {
    setIsSuggesting(true);
    setError("");
    setFieldErrors({});
    try {
      const suggestion = await suggestAI_RCA(id);
      setForm((current) => ({
        ...current,
        root_cause_category: suggestion.root_cause_category,
        fix_applied: suggestion.fix_applied,
        prevention_steps: suggestion.prevention_steps
      }));
      setIsFallback(!!suggestion.is_fallback);
      setMessage(suggestion.is_fallback 
        ? "Template suggestion applied (AI unavailable)." 
        : "AI Suggestion applied successfully!");
      setTimeout(() => setMessage(""), 5000);
    } catch (err) {
      setError(`AI Suggestion failed: ${err.message}`);
    } finally {
      setIsSuggesting(false);
    }
  }

  function validate() {
    const errors = {};
    if (!form.incident_start) errors.incident_start = "Start time is required";
    if (!form.incident_end) errors.incident_end = "End time is required";
    
    if (form.incident_start && form.incident_end) {
      if (new Date(form.incident_end) <= new Date(form.incident_start)) {
        errors.incident_end = "End time must be after start time";
      }
    }
    
    if (!form.fix_applied.trim()) errors.fix_applied = "Please describe the fix applied";
    if (!form.prevention_steps.trim()) errors.prevention_steps = "Please describe prevention steps";
    
    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  }

  async function onSubmit(event) {
    event.preventDefault();
    setError("");
    setMessage("");
    
    if (!validate()) return;

    try {
      const payload = {
        ...form,
        incident_start: new Date(form.incident_start).toISOString(),
        incident_end: new Date(form.incident_end).toISOString()
      };
      await submitRCA(id, payload);
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
        <button type="button" className="icon-text-button" onClick={suggestRCA} disabled={!incident || isSuggesting}>
          {isSuggesting ? <Loader2 size={16} className="animate-spin" /> : <Wand2 size={16} />} 
          {isSuggesting ? "Analyzing..." : "Suggest"}
        </button>
        {isFallback && <span className="fallback-note">(AI unavailable - template suggestion)</span>}
      </div>
      {error && <div className="error-banner">{error}</div>}
      {message && <div className="success-banner">{message}</div>}
      <form className="form" onSubmit={onSubmit}>
        <label>
          Incident Start
          <input 
            type="datetime-local" 
            className={fieldErrors.incident_start ? "input-error" : ""}
            value={form.incident_start} 
            onChange={(e) => update("incident_start", e.target.value)} 
          />
          {fieldErrors.incident_start && <span className="error-text">{fieldErrors.incident_start}</span>}
        </label>
        
        <label>
          Incident End
          <input 
            type="datetime-local" 
            className={fieldErrors.incident_end ? "input-error" : ""}
            value={form.incident_end} 
            onChange={(e) => update("incident_end", e.target.value)} 
          />
          {fieldErrors.incident_end && <span className="error-text">{fieldErrors.incident_end}</span>}
        </label>

        <label>
          Root Cause Category
          <select value={form.root_cause_category} onChange={(e) => update("root_cause_category", e.target.value)}>
            {categories.map((category) => <option key={category}>{category}</option>)}
          </select>
        </label>

        <label>
          Fix Applied
          <textarea 
            rows="5" 
            className={fieldErrors.fix_applied ? "input-error" : ""}
            value={form.fix_applied} 
            onChange={(e) => update("fix_applied", e.target.value)} 
          />
          {fieldErrors.fix_applied && <span className="error-text">{fieldErrors.fix_applied}</span>}
        </label>

        <label>
          Prevention Steps
          <textarea 
            rows="5" 
            className={fieldErrors.prevention_steps ? "input-error" : ""}
            value={form.prevention_steps} 
            onChange={(e) => update("prevention_steps", e.target.value)} 
          />
          {fieldErrors.prevention_steps && <span className="error-text">{fieldErrors.prevention_steps}</span>}
        </label>

        <button className="primary-button" type="submit">Submit RCA</button>
      </form>
    </section>
  );
}
