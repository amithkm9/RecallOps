import { createContext, useContext, useEffect, useRef, useState } from "react";
import {
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  Boxes,
  ChevronRight,
  FlaskConical,
  GitBranch,
  LayoutDashboard,
  Menu,
  Radio,
  Settings2,
  ShieldCheck,
  Timer,
  X,
  ArrowUpRight,
  Sparkles,
} from "lucide-react";
import {
  DashboardPage,
  IncidentsPage,
  InventoryPage,
  SettingsPage,
} from "./pages";
import {
  IncidentPage,
  GraphPage,
  TimeMachinePage,
  EvaluationPage,
} from "./investigation";
import { type Mode, token } from "./api";
const ModeContext = createContext<{
  mode: Mode;
  setMode: (mode: Mode) => void;
}>({ mode: "replay", setMode: () => {} });
export const useMode = () => useContext(ModeContext);
const navigation = [
  ["/", "Overview", LayoutDashboard],
  ["/incidents", "Incidents", ShieldCheck],
  ["/inventory", "Inventory", Boxes],
  ["/evidence", "Evidence graph", GitBranch],
  ["/time-machine", "Decision time machine", Timer],
  ["/evaluation", "Evaluation lab", FlaskConical],
  ["/settings", "Data & settings", Settings2],
] as const;
export default function App() {
  const [mode, updateMode] = useState<Mode>(() =>
    sessionStorage.getItem("recallops-mode") === "live" ? "live" : "replay",
  );
  const setMode = (next: Mode) => {
    sessionStorage.setItem("recallops-mode", next);
    updateMode(next);
  };
  const [open, setOpen] = useState(false);
  const [connected, setConnected] = useState(false);
  const [authVersion, setAuthVersion] = useState(0);
  const [accessRecovered, setAccessRecovered] = useState(false);
  const client = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  const sidebar = useRef<HTMLElement>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const update = () => setAuthVersion((version) => version + 1);
    window.addEventListener("recallops-auth-change", update);
    return () => window.removeEventListener("recallops-auth-change", update);
  }, []);
  useEffect(() => {
    const recovered = () => setAccessRecovered(true);
    window.addEventListener("recallops-local-access-recovered", recovered);
    return () =>
      window.removeEventListener("recallops-local-access-recovered", recovered);
  }, []);
  useEffect(() => {
    setOpen(false);
    window.scrollTo(0, 0);
  }, [location.pathname]);
  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    sidebar.current?.querySelector<HTMLButtonElement>(".mobile-close")?.focus();
    function keyboard(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        menuButton.current?.focus();
      }
      if (event.key === "Tab") {
        const items = sidebar.current?.querySelectorAll<HTMLElement>(
          "a[href], button:not([disabled])",
        );
        if (!items?.length) return;
        const first = items[0],
          last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        }
        if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener("keydown", keyboard);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", keyboard);
    };
  }, [open]);
  useEffect(() => {
    const controller = new AbortController();
    let retry: ReturnType<typeof setTimeout>;
    async function connect() {
      try {
        const r = await fetch("/api/events/stream", {
          headers: token() ? { Authorization: `Bearer ${token()}` } : {},
          signal: controller.signal,
        });
        if (!r.ok || !r.body) throw Error();
        setConnected(true);
        const reader = r.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (!controller.signal.aborted) {
          const { done, value } = await reader.read();
          if (done) break;
          // Heartbeats keep the connection alive; only data events change records.
          buffer += decoder.decode(value, { stream: true });
          const events = buffer.split("\n\n");
          buffer = events.pop() || "";
          if (
            events.some((event) =>
              event.split("\n").some((line) => line.startsWith("data:")),
            )
          )
            void client.invalidateQueries();
        }
        setConnected(false);
      } catch {
        setConnected(false);
      }
      if (!controller.signal.aborted) retry = setTimeout(connect, 5000);
    }
    void connect();
    return () => {
      controller.abort();
      clearTimeout(retry);
    };
  }, [client, authVersion]);
  return (
    <ModeContext.Provider value={{ mode, setMode }}>
      <div className="app">
        <a className="skip-link" href="#main-content">
          Skip to content
        </a>
        {open && (
          <button
            className="nav-backdrop"
            aria-label="Dismiss navigation"
            onClick={() => {
              setOpen(false);
              menuButton.current?.focus();
            }}
          />
        )}
        <aside
          id="workspace-navigation"
          ref={sidebar}
          className={`sidebar ${open ? "open" : ""}`}
        >
          <LinkBrand />
          <button
            className="mobile-close"
            onClick={() => {
              setOpen(false);
              menuButton.current?.focus();
            }}
            aria-label="Close navigation"
          >
            <X />
          </button>
          <div className="workspace">
            <div className="workspace-avatar">
              M<span />
            </div>
            <div>
              <strong>Marché workspace</strong>
              <small>Product safety team</small>
            </div>
          </div>
          <div className="nav-label">WORKSPACE</div>
          <nav aria-label="Main navigation">
            {navigation.map(([to, label, Icon], index) => (
              <div key={to}>
                {index === 3 && (
                  <div className="nav-label nav-section">INTELLIGENCE</div>
                )}
                {index === 6 && (
                  <div className="nav-label nav-section">MANAGE</div>
                )}
                <NavLink end={to === "/"} to={to}>
                  <Icon size={18} />
                  <span>{label}</span>
                  {to === "/time-machine" && (
                    <span className="nav-new">REPLAY</span>
                  )}
                </NavLink>
              </div>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <div className="sidebar-note">
              <Sparkles size={19} />
              <strong>Confidence in every call.</strong>
              <p>See how new evidence changes a recall investigation.</p>
              <NavLink to="/time-machine">
                Explore the replay <ArrowUpRight size={14} />
              </NavLink>
            </div>
            <div className="sidebar-foot">
              <span className={`dot ${connected ? "green" : ""}`} />
              {connected ? "Updates connected" : "Reconnecting to updates"}
            </div>
          </div>
        </aside>
        <div className="main">
          <div className="topbar">
            <div className="breadcrumb">
              <button
                className="menu-toggle"
                ref={menuButton}
                aria-label="Open navigation"
                aria-expanded={open}
                aria-controls="workspace-navigation"
                onClick={() => setOpen(!open)}
              >
                <Menu />
              </button>
              <span>Marché</span>
              <ChevronRight size={14} />
              <strong>
                {navigation.find(([to]) =>
                  to === "/"
                    ? location.pathname === "/"
                    : location.pathname.startsWith(to),
                )?.[1] || "Incident detail"}
              </strong>
            </div>
            <div className="topbar-actions">
              <span className="mode-label">
                <Radio size={13} />
                {mode === "replay" ? "RECORDED SCENARIO" : "OFFICIAL DATA"}
              </span>
              <select
                aria-label="Data mode"
                value={mode}
                onChange={(e) => {
                  setMode(e.target.value as Mode);
                  navigate("/");
                }}
              >
                <option value="replay">Replay demo mode</option>
                <option value="live">Live data mode</option>
              </select>
              <span className="avatar" title="Operator workspace">
                OP
              </span>
            </div>
          </div>
          <main id="main-content" tabIndex={-1}>
            {accessRecovered && (
              <div className="mode-notice" role="status">
                The saved access token was rejected and has been cleared. Local
                development access is restored.{" "}
                <NavLink to="/settings">
                  Create or enter a valid credential in Data & settings
                </NavLink>
              </div>
            )}
            <Routes>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/incidents" element={<IncidentsPage />} />
              <Route path="/incidents/:id" element={<IncidentPage />} />
              <Route path="/inventory" element={<InventoryPage />} />
              <Route path="/evidence" element={<GraphPage />} />
              <Route path="/time-machine" element={<TimeMachinePage />} />
              <Route path="/evaluation" element={<EvaluationPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="*" element={<DashboardPage />} />
            </Routes>
          </main>
          <footer>
            <span>
              <ShieldCheck size={14} /> RecallOps · Evidence behind every
              decision
            </span>
            <span>Internal holds only · No point-of-sale connection</span>
          </footer>
        </div>
      </div>
    </ModeContext.Provider>
  );
}
function LinkBrand() {
  return (
    <NavLink to="/" className="brand">
      <div className="brand-icon">
        <ShieldCheck size={23} strokeWidth={1.6} />
      </div>
      <span>
        Recall<span className="brand-light">Ops</span>
        <small>SAFETY INTELLIGENCE</small>
      </span>
    </NavLink>
  );
}
