import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { installDemoFetch } from "./demo/demoMode";

// Before anything fetches, so demo mode never lets a real user name through
installDemoFetch();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
