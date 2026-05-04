export default function SeverityPill({ severity }) {
  return <span className={`severity-pill severity-${severity.toLowerCase()}`}>{severity}</span>;
}
