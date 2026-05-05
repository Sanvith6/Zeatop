import { Moon, Sun, Activity } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, Outlet } from "react-router-dom";

export default function App() {
  const [darkMode, setDarkMode] = useState(() => localStorage.getItem("darkMode") === "true");

  useEffect(() => {
    document.documentElement.dataset.theme = darkMode ? "dark" : "light";
    localStorage.setItem("darkMode", String(darkMode));
  }, [darkMode]);

  return (
    <div className="app-shell">
      <header className="topbar">
        <Link className="brand" to="/">
          <Activity size={24} />
          <span>Zeatop SRE</span>
        </Link>
        <div className="status-indicator">
          <div className="pulse-dot"></div>
          <span>Systems Nominal</span>
        </div>
        <button className="icon-button" type="button" title="Toggle dark mode" onClick={() => setDarkMode((value) => !value)}>
          {darkMode ? <Sun size={18} /> : <Moon size={18} />}
        </button>
      </header>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
