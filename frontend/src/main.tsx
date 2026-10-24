import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { CueColorsProvider } from "./components/CueColors";
import { ToastProvider } from "./components/Toast";
import "./styles.css";
import "./rekordbox-theme.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <CueColorsProvider>
      <ToastProvider>
        <App />
      </ToastProvider>
    </CueColorsProvider>
  </React.StrictMode>,
);
