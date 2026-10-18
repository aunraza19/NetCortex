"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  AlertTriangle,
  ChevronDown,
  Command,
  LayoutDashboard,
  Menu,
  RadioTower,
  Settings,
  ShieldCheck,
  X,
} from "lucide-react";
import { useState } from "react";
import { apiMode } from "@/lib/transport";
const nav = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/incidents", label: "Incidents", icon: AlertTriangle },
  { href: "/demo", label: "Demo panel", icon: Command },
  { href: "/settings", label: "Settings", icon: Settings },
];
export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  return (
    <div className="app-shell">
      <aside className={`sidebar ${open ? "sidebar-open" : ""}`}>
        <div className="brand">
          <span className="brand-mark">
            <Activity size={19} />
          </span>
          <div>
            <strong>netcortex</strong>
            <small>NETWORK OPERATIONS</small>
          </div>
          <button
            className="icon-button mobile-close"
            aria-label="Close navigation"
            onClick={() => setOpen(false)}
          >
            <X size={18} />
          </button>
        </div>
        <div className="workspace-select">
          <span className="workspace-dot" />
          <span>North region</span>
          <ChevronDown size={14} />
        </div>
        <div className="nav-label">WORKSPACE</div>
        <nav>
          {nav.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              onClick={() => setOpen(false)}
              className={`nav-link ${path === n.href || (n.href !== "/" && path.startsWith(n.href)) ? "active" : ""}`}
            >
              <n.icon size={17} />
              <span>{n.label}</span>
              {n.label === "Incidents" && <b className="nav-count">2</b>}
            </Link>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="connection-card">
            <span className="status-orb" />
            <div>
              <strong>
                {apiMode === "mock" ? "Replay mode" : "API connection"}
              </strong>
              <small>
                {apiMode === "mock" ? "Local fixture data" : "Live service"}
              </small>
            </div>
          </div>
          <div className="operator">
            <div className="avatar">AR</div>
            <div>
              <strong>Network operator</strong>
              <small>North region</small>
            </div>
            <ChevronDown size={15} />
          </div>
        </div>
      </aside>
      {open && (
        <button
          className="sidebar-scrim"
          aria-label="Close navigation"
          onClick={() => setOpen(false)}
        />
      )}
      <div className="main-area">
        <header className="topbar">
          <button
            className="icon-button mobile-menu"
            aria-label="Open navigation"
            onClick={() => setOpen(true)}
          >
            <Menu size={20} />
          </button>
          <div className="breadcrumb">
            <RadioTower size={15} />
            <span>Operations</span>
            <span className="crumb-slash">/</span>
            <span className="crumb-current">
              {path === "/"
                ? "Overview"
                : path.split("/")[1]?.replace(/^./, (s) => s.toUpperCase())}
            </span>
          </div>
          <div className="topbar-right">
            <div className="demo-badge">
              <span />
              {apiMode === "mock" ? "Demo: replayed data" : "Live network data"}
            </div>
            <div className="live-indicator">
              <span className="pulse" />
              {apiMode === "mock" ? "Replay" : "Live mode"}
            </div>
            <button className="operator-chip">
              <div className="avatar avatar-small">AR</div>
              <span>Operator</span>
              <ChevronDown size={14} />
            </button>
          </div>
        </header>
        <main>{children}</main>
        <footer className="footer">
          <span>
            <ShieldCheck size={13} /> Changes require operator approval
          </span>
          <span>
            NetCortex <i>·</i> Pakistan Standard Time
          </span>
        </footer>
      </div>
    </div>
  );
}
