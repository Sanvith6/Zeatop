import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import App from "./App.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import History from "./pages/History.jsx";
import IncidentDetail from "./pages/IncidentDetail.jsx";
import RCAForm from "./pages/RCAForm.jsx";
import "./styles.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<App />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/history" element={<History />} />
          <Route path="/incident/:id" element={<IncidentDetail />} />
          <Route path="/incident/:id/rca" element={<RCAForm />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);
