// AgentAtlas — Production Frontend v2.0
// Week 1: Auth shell, JWT, routing, navigation
// Week 2: Dashboard (real API), Inventory (search/filter/live)
// Week 3: Agent detail, visual relationship graph, change history
// Week 4: Connectors config, SIEM config, Settings / user management
// New in v2: WebSocket live event stream, visual SVG graph, real-time shadow pulse

import { useState, useEffect, useCallback, useRef, useReducer, createContext, useContext } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  AreaChart, Area, PieChart, Pie, Cell, CartesianGrid
} from "recharts";

// ── Design tokens ──────────────────────────────────────────────────────────────
const T = {
  navy:      "#0A1628",  navyLt:   "#0F2040",  navyBorder:"#1E3354",
  teal:      "#0D7377",  tealLt:   "#14A3A8",  tealPale:  "#E8F7F8",
  white:     "#FFFFFF",  offwhite: "#F4F6F9",  surface:   "#F8FAFB",
  slate:     "#374151",  muted:    "#6B7280",  border:    "#E5E7EB",
  red:       "#E24B4A",  redPale:  "#FEE2E2",
  amber:     "#D97706",  amberPale:"#FEF3C7",
  green:     "#059669",  greenPale:"#D1FAE5",
  blue:      "#2563EB",  bluePale: "#EFF6FF",
  purple:    "#7C3AED",  purplePale:"#EDE9FE",
  cloud: { azure:"#2563EB", aws:"#D97706", gcp:"#059669", local:"#9CA3AF", unknown:"#9CA3AF" },
  fw: { langchain:"#2563EB", crewai:"#059669", autogen:"#7C3AED", semantic_kernel:"#0D7377",
        llamaindex:"#D97706", ollama:"#374151", custom:"#9CA3AF", unknown:"#9CA3AF" },
};

// ── Constants ─────────────────────────────────────────────────────────────────
const API_BASE = "http://localhost:8215";
const WS_BASE  = "ws://localhost:8215";

// ── API client ────────────────────────────────────────────────────────────────
async function apiFetch(path, options = {}, token = null) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...headers, ...(options.headers || {}) }
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw { status: res.status, detail: err.error || "Request failed" };
  }
  return res.json();
}

// ── Auth context ──────────────────────────────────────────────────────────────
const AuthCtx = createContext(null);
const useAuth = () => useContext(AuthCtx);

function AuthProvider({ children }) {
  const [state, setState] = useState({
    user: null, token: null, isAuthenticated: false, isLoading: true
  });

  useEffect(() => {
    const token = sessionStorage.getItem("aa_token");
    const user  = sessionStorage.getItem("aa_user");
    if (token && user) {
      setState({ token, user: JSON.parse(user), isAuthenticated: true, isLoading: false });
    } else {
      setState(s => ({ ...s, isLoading: false }));
    }
  }, []);

  const login = async (username, password) => {
    const data = await apiFetch("/api/v1/auth/login", {
      method: "POST", body: JSON.stringify({ username, password })
    });
    const me = await apiFetch("/api/v1/auth/me", {}, data.access_token);
    sessionStorage.setItem("aa_token", data.access_token);
    sessionStorage.setItem("aa_user", JSON.stringify(me));
    setState({ token: data.access_token, user: me, isAuthenticated: true, isLoading: false });
    return me;
  };

  const logout = () => {
    sessionStorage.clear();
    setState({ user: null, token: null, isAuthenticated: false, isLoading: false });
  };

  return (
    <AuthCtx.Provider value={{ ...state, login, logout }}>
      {children}
    </AuthCtx.Provider>
  );
}

// ── WebSocket hook ────────────────────────────────────────────────────────────
function useWebSocket(token, onEvent) {
  const wsRef = useRef(null);
  const reconnectRef = useRef(null);

  useEffect(() => {
    if (!token) return;

    const connect = () => {
      try {
        const ws = new WebSocket(`${WS_BASE}/ws/events?token=${token}`);
        wsRef.current = ws;
        ws.onmessage = (e) => {
          try { onEvent(JSON.parse(e.data)); } catch (_) {}
        };
        ws.onclose = () => {
          reconnectRef.current = setTimeout(connect, 3000);
        };
        ws.onerror = () => ws.close();
      } catch (_) {}
    };

    connect();
    return () => {
      clearTimeout(reconnectRef.current);
      wsRef.current?.close();
    };
  }, [token]);
}

// ── Toast system ──────────────────────────────────────────────────────────────
const ToastCtx = createContext(null);
function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const add = useCallback((msg, type = "info") => {
    const id = Date.now();
    setToasts(t => [...t, { id, msg, type }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 4000);
  }, []);
  return (
    <ToastCtx.Provider value={add}>
      {children}
      <div style={{ position:"fixed", bottom:24, right:24, zIndex:9999, display:"flex", flexDirection:"column", gap:8 }}>
        {toasts.map(t => (
          <div key={t.id} style={{
            background: t.type === "error" ? T.red : t.type === "success" ? T.green : T.navy,
            color: "#fff", padding:"10px 16px", borderRadius:8, fontSize:13, fontWeight:500,
            boxShadow:"0 4px 12px rgba(0,0,0,0.15)", maxWidth:320,
            animation:"slideIn .2s ease"
          }}>{t.msg}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
const useToast = () => useContext(ToastCtx);

// ── Shared UI components ──────────────────────────────────────────────────────
function Spinner({ size = 20 }) {
  return (
    <div style={{
      width:size, height:size, border:`2px solid ${T.border}`,
      borderTopColor:T.teal, borderRadius:"50%", animation:"spin 0.7s linear infinite"
    }} />
  );
}

function Badge({ children, color = "gray" }) {
  const map = {
    green:  { bg:T.greenPale,  text:"#065F46" },
    red:    { bg:T.redPale,    text:"#991B1B" },
    amber:  { bg:T.amberPale,  text:"#92400E" },
    blue:   { bg:T.bluePale,   text:"#1D4ED8" },
    teal:   { bg:T.tealPale,   text:T.teal    },
    purple: { bg:T.purplePale, text:"#5B21B6" },
    gray:   { bg:T.offwhite,   text:T.muted   },
  };
  const c = map[color] || map.gray;
  return (
    <span style={{
      fontSize:11, fontWeight:600, padding:"2px 8px", borderRadius:20,
      background:c.bg, color:c.text, whiteSpace:"nowrap"
    }}>{children}</span>
  );
}

function StatusDot({ status }) {
  const colors = {
    healthy:"#22C55E", running:"#22C55E", active:"#22C55E",
    warning:T.amber, error:T.red, stopped:T.muted, unknown:T.muted
  };
  const pulse = status === "healthy" || status === "running" || status === "active";
  return (
    <span style={{ position:"relative", display:"inline-flex", alignItems:"center" }}>
      {pulse && (
        <span style={{
          position:"absolute", width:11, height:11, borderRadius:"50%",
          background:colors[status], opacity:0.35, animation:"pulse 2s ease-in-out infinite"
        }} />
      )}
      <span style={{
        width:7, height:7, borderRadius:"50%",
        background:colors[status] || T.muted, position:"relative"
      }} />
    </span>
  );
}

function Button({ children, onClick, variant="primary", size="md", disabled=false, style={} }) {
  const base = {
    display:"inline-flex", alignItems:"center", gap:6, fontWeight:500,
    border:"none", cursor:disabled?"not-allowed":"pointer",
    borderRadius:8, transition:"all .15s", opacity:disabled?0.5:1,
    fontSize: size==="sm"?12:14, padding: size==="sm"?"6px 12px":"8px 16px",
  };
  const variants = {
    primary:  { background:T.teal, color:"#fff" },
    secondary:{ background:T.offwhite, color:T.slate, border:`1px solid ${T.border}` },
    danger:   { background:T.red, color:"#fff" },
    ghost:    { background:"transparent", color:T.muted, border:`1px solid ${T.border}` },
  };
  return (
    <button onClick={onClick} disabled={disabled}
      style={{ ...base, ...variants[variant], ...style }}>
      {children}
    </button>
  );
}

function Input({ value, onChange, placeholder, type="text", style={} }) {
  return (
    <input
      type={type} value={value} onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      style={{
        border:`1px solid ${T.border}`, borderRadius:8, padding:"8px 12px",
        fontSize:13, outline:"none", width:"100%", background:"#fff", color:T.slate,
        transition:"border .15s", boxSizing:"border-box", ...style
      }}
      onFocus={e => e.target.style.borderColor = T.teal}
      onBlur={e => e.target.style.borderColor = T.border}
    />
  );
}

function Select({ value, onChange, options, style={} }) {
  return (
    <select value={value} onChange={e => onChange(e.target.value)}
      style={{
        border:`1px solid ${T.border}`, borderRadius:8, padding:"8px 12px",
        fontSize:13, background:"#fff", color:T.slate, cursor:"pointer",
        outline:"none", ...style
      }}>
      {options.map(o => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}

function Card({ children, style={}, onClick }) {
  return (
    <div onClick={onClick}
      style={{
        background:"#fff", border:`1px solid ${T.border}`, borderRadius:12,
        padding:"16px 20px", cursor:onClick?"pointer":undefined,
        transition:onClick?"box-shadow .15s":undefined, ...style
      }}
      onMouseEnter={e => onClick && (e.currentTarget.style.boxShadow="0 4px 12px rgba(0,0,0,0.08)")}
      onMouseLeave={e => onClick && (e.currentTarget.style.boxShadow="none")}
    >{children}</div>
  );
}

function Modal({ open, onClose, title, children, width=480 }) {
  if (!open) return null;
  return (
    <div onClick={onClose} style={{
      position:"fixed", inset:0, background:"rgba(0,0,0,0.45)",
      display:"flex", alignItems:"center", justifyContent:"center", zIndex:1000
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        background:"#fff", borderRadius:12, width, maxWidth:"90vw",
        maxHeight:"85vh", overflow:"auto", boxShadow:"0 20px 60px rgba(0,0,0,0.2)"
      }}>
        <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center",
          padding:"16px 20px", borderBottom:`1px solid ${T.border}` }}>
          <span style={{ fontWeight:600, fontSize:15, color:T.navy }}>{title}</span>
          <button onClick={onClose} style={{ background:"none", border:"none",
            cursor:"pointer", color:T.muted, fontSize:18, lineHeight:1 }}>✕</button>
        </div>
        <div style={{ padding:"20px" }}>{children}</div>
      </div>
    </div>
  );
}

function EmptyState({ icon = "🔍", title, subtitle, action }) {
  return (
    <div style={{ textAlign:"center", padding:"60px 20px", color:T.muted }}>
      <div style={{ fontSize:36, marginBottom:12 }}>{icon}</div>
      <div style={{ fontWeight:600, fontSize:15, color:T.slate, marginBottom:6 }}>{title}</div>
      <div style={{ fontSize:13, marginBottom:action?16:0 }}>{subtitle}</div>
      {action}
    </div>
  );
}

// ── Stat card ─────────────────────────────────────────────────────────────────
function StatCard({ label, value, sub, color, pulse, icon, onClick }) {
  return (
    <Card onClick={onClick} style={{ cursor:onClick?"pointer":undefined }}>
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start" }}>
        <div>
          <div style={{ fontSize:12, color:T.muted, marginBottom:6, fontWeight:500 }}>{label}</div>
          <div style={{ display:"flex", alignItems:"center", gap:8 }}>
            <span style={{ fontSize:28, fontWeight:700, color:color || T.navy }}>{value}</span>
            {pulse && (
              <span style={{
                width:8, height:8, borderRadius:"50%", background:T.red,
                animation:"pulse 1.5s ease-in-out infinite", flexShrink:0
              }} />
            )}
          </div>
          {sub && <div style={{ fontSize:12, color:T.muted, marginTop:4 }}>{sub}</div>}
        </div>
        {icon && (
          <div style={{
            width:40, height:40, borderRadius:10, display:"flex", alignItems:"center",
            justifyContent:"center", fontSize:20,
            background: color ? `${color}18` : T.offwhite
          }}>{icon}</div>
        )}
      </div>
    </Card>
  );
}

// ── Cloud / framework badge ───────────────────────────────────────────────────
function CloudBadge({ cloud }) {
  const colors = { azure:"#2563EB", aws:"#D97706", gcp:"#059669", local:"#6B7280", unknown:"#9CA3AF" };
  const labels = { azure:"Azure", aws:"AWS", gcp:"GCP", local:"Local", unknown:"?" };
  const c = colors[cloud] || colors.unknown;
  return (
    <span style={{
      fontSize:10, fontWeight:700, padding:"2px 6px", borderRadius:4,
      background:`${c}18`, color:c, border:`1px solid ${c}30`
    }}>{labels[cloud] || cloud}</span>
  );
}

// ── Page shell: sidebar + main ────────────────────────────────────────────────
function Sidebar({ page, setPage, liveCount, shadowCount, wsConnected }) {
  const { user, logout } = useAuth();

  const navItems = [
    { id:"dashboard",   label:"Dashboard",   icon:"⬡" },
    { id:"inventory",   label:"AI Inventory", icon:"◫" },
    { id:"connectors",  label:"Connectors",  icon:"⌁" },
    { id:"siem",        label:"SIEM",        icon:"⊞" },
    { id:"settings",    label:"Settings",    icon:"⚙" },
  ];

  return (
    <div style={{
      width:220, background:T.navy, color:"#fff", display:"flex",
      flexDirection:"column", height:"100vh", flexShrink:0, position:"sticky", top:0
    }}>
      {/* Brand */}
      <div style={{ padding:"20px 18px 16px", borderBottom:`1px solid ${T.navyBorder}` }}>
        <div style={{ display:"flex", alignItems:"center", gap:10 }}>
          <div style={{
            width:32, height:32, borderRadius:8, background:T.teal,
            display:"flex", alignItems:"center", justifyContent:"center",
            fontSize:16, fontWeight:700
          }}>A</div>
          <div>
            <div style={{ fontWeight:700, fontSize:14 }}>AgentAtlas</div>
            <div style={{ fontSize:10, color:"#94A3B8", marginTop:1 }}>Enterprise</div>
          </div>
        </div>
      </div>

      {/* Live agent count */}
      <div style={{
        margin:"12px 12px 4px", background:T.navyLt, borderRadius:10,
        padding:"10px 12px", border:`1px solid ${T.navyBorder}`
      }}>
        <div style={{ fontSize:10, color:"#94A3B8", marginBottom:4 }}>LIVE AGENT COUNT</div>
        <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
          <span style={{ fontSize:22, fontWeight:700 }}>{liveCount}</span>
          <div style={{ display:"flex", alignItems:"center", gap:4, fontSize:10, color:T.red }}>
            <span style={{
              width:6, height:6, borderRadius:"50%", background:T.red,
              animation:"pulse 1.5s ease-in-out infinite", display:"inline-block"
            }} />
            {shadowCount} shadow
          </div>
        </div>
        <div style={{ display:"flex", alignItems:"center", gap:4, marginTop:4, fontSize:10, color:wsConnected?"#22C55E":"#94A3B8" }}>
          <span style={{ width:5, height:5, borderRadius:"50%", background:wsConnected?"#22C55E":"#94A3B8", display:"inline-block" }} />
          {wsConnected ? "Live stream active" : "Connecting..."}
        </div>
      </div>

      {/* Nav */}
      <nav style={{ flex:1, padding:"8px 0" }}>
        {navItems.map(item => (
          <div key={item.id} onClick={() => setPage(item.id)}
            style={{
              display:"flex", alignItems:"center", gap:10,
              padding:"10px 18px", cursor:"pointer", fontSize:13, fontWeight:500,
              color: page===item.id ? "#fff" : "#94A3B8",
              background: page===item.id ? T.teal : "transparent",
              margin:"1px 8px", borderRadius:8,
              transition:"all .15s"
            }}>
            <span style={{ fontSize:16 }}>{item.icon}</span>
            {item.label}
          </div>
        ))}
      </nav>

      {/* User footer */}
      <div style={{ padding:"12px 14px", borderTop:`1px solid ${T.navyBorder}` }}>
        <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:8 }}>
          <div style={{
            width:28, height:28, borderRadius:"50%", background:T.teal,
            display:"flex", alignItems:"center", justifyContent:"center",
            fontSize:11, fontWeight:700
          }}>{(user?.username || "?")[0].toUpperCase()}</div>
          <div>
            <div style={{ fontSize:12, fontWeight:500 }}>{user?.username}</div>
            <div style={{ fontSize:10, color:"#94A3B8" }}>{user?.role}</div>
          </div>
        </div>
        <button onClick={logout} style={{
          width:"100%", background:"transparent", border:`1px solid ${T.navyBorder}`,
          color:"#94A3B8", borderRadius:6, padding:"6px 0", fontSize:12,
          cursor:"pointer", transition:"all .15s"
        }}>Sign out</button>
      </div>
    </div>
  );
}

// ── Live event feed (sidebar panel) ──────────────────────────────────────────
function EventFeed({ events }) {
  const severity = { critical:"#EF4444", high:T.red, warning:T.amber, info:T.teal };
  const latest = events.slice(0, 6);
  return (
    <div style={{ display:"flex", flexDirection:"column", gap:6 }}>
      {latest.length === 0 && (
        <div style={{ fontSize:12, color:T.muted, textAlign:"center", padding:"20px 0" }}>
          No events yet — discovery will populate this
        </div>
      )}
      {latest.map((e, i) => (
        <div key={i} style={{
          display:"flex", alignItems:"flex-start", gap:8,
          padding:"8px 10px", borderRadius:8, background:T.offwhite,
          borderLeft:`3px solid ${severity[e.severity] || T.muted}`
        }}>
          <div style={{ flex:1, minWidth:0 }}>
            <div style={{ fontSize:12, fontWeight:500, color:T.slate,
              whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis" }}>
              {e.event_type?.replace(/\./g, " ") || "event"}
            </div>
            <div style={{ fontSize:11, color:T.muted }}>
              {e.payload?.agent_id || e.payload?.job_id || "—"}
            </div>
          </div>
          <div style={{ fontSize:10, color:T.muted, whiteSpace:"nowrap", marginTop:2 }}>
            {e.created_at ? new Date(e.created_at).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"}) : ""}
          </div>
        </div>
      ))}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// WEEK 1 — Login
// ═══════════════════════════════════════════════════════════════════════════════
function LoginPage() {
  const { login } = useAuth();
  const toast = useToast();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleLogin = async () => {
    if (!username || !password) { setError("Enter credentials"); return; }
    setLoading(true); setError("");
    try {
      await login(username, password);
    } catch (e) {
      setError(e.detail || "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      minHeight:"100vh", background:`linear-gradient(135deg, ${T.navy} 0%, #0F2A50 100%)`,
      display:"flex", alignItems:"center", justifyContent:"center", padding:20
    }}>
      <div style={{
        background:"#fff", borderRadius:16, padding:"40px 36px",
        width:"100%", maxWidth:380, boxShadow:"0 24px 64px rgba(0,0,0,0.25)"
      }}>
        {/* Logo */}
        <div style={{ textAlign:"center", marginBottom:32 }}>
          <div style={{
            width:52, height:52, borderRadius:14, background:T.teal,
            display:"flex", alignItems:"center", justifyContent:"center",
            fontSize:24, fontWeight:800, color:"#fff", margin:"0 auto 12px"
          }}>A</div>
          <div style={{ fontWeight:800, fontSize:22, color:T.navy }}>AgentAtlas</div>
          <div style={{ fontSize:13, color:T.muted, marginTop:4 }}>Enterprise AI Discovery</div>
        </div>

        <div style={{ display:"flex", flexDirection:"column", gap:12 }}>
          <div>
            <label style={{ fontSize:12, fontWeight:600, color:T.slate, display:"block", marginBottom:6 }}>
              Username
            </label>
            <Input value={username} onChange={setUsername} placeholder="admin"
              onKeyDown={e => e.key === "Enter" && handleLogin()} />
          </div>
          <div>
            <label style={{ fontSize:12, fontWeight:600, color:T.slate, display:"block", marginBottom:6 }}>
              Password
            </label>
            <Input value={password} onChange={setPassword} placeholder="••••••••"
              type="password" onKeyDown={e => e.key === "Enter" && handleLogin()} />
          </div>

          {error && (
            <div style={{ background:T.redPale, color:"#991B1B", fontSize:13,
              padding:"8px 12px", borderRadius:8, fontWeight:500 }}>{error}</div>
          )}

          <Button onClick={handleLogin} disabled={loading} style={{ width:"100%", justifyContent:"center", marginTop:4 }}>
            {loading ? <Spinner size={16} /> : "Sign in"}
          </Button>
        </div>

        <div style={{ marginTop:20, padding:"12px", background:T.offwhite, borderRadius:8, fontSize:12, color:T.muted }}>
          <strong>Demo:</strong> admin / Admin@123 &nbsp;·&nbsp; analyst / Analyst@123
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// WEEK 2 — Dashboard
// ═══════════════════════════════════════════════════════════════════════════════
function DashboardPage({ onNavigate, liveEvents }) {
  const { token } = useAuth();
  const [stats, setStats]         = useState(null);
  const [connectors, setConnectors] = useState([]);
  const [jobs, setJobs]           = useState([]);
  const [loading, setLoading]     = useState(true);

  const load = useCallback(async () => {
    try {
      const [s, c, j] = await Promise.all([
        apiFetch("/api/v1/agents/stats", {}, token),
        apiFetch("/api/v1/connectors", {}, token),
        apiFetch("/api/v1/discovery/jobs", {}, token),
      ]);
      setStats(s);
      setConnectors((c.connectors || []).slice(0, 6));
      setJobs((j.jobs || []).slice(0, 5));
    } catch (_) {}
    setLoading(false);
  }, [token]);

  useEffect(() => { load(); }, [load]);

  // Refresh stats when a live job.completed event arrives
  useEffect(() => {
    const last = liveEvents[0];
    if (last?.event_type === "job.completed") load();
  }, [liveEvents[0]?.event_id]);

  const cloudData = stats ? Object.entries(stats.by_cloud || {}).map(([k,v]) => ({ name:k.toUpperCase(), value:v, fill:T.cloud[k] || T.muted })) : [];
  const fwData    = stats ? Object.entries(stats.by_framework || {}).slice(0,6).map(([k,v]) => ({ name:k, value:v })) : [];

  const trendData = [
    { day:"Mon", agents:stats?.total ? Math.floor(stats.total*0.89):0 },
    { day:"Tue", agents:stats?.total ? Math.floor(stats.total*0.91):0 },
    { day:"Wed", agents:stats?.total ? Math.floor(stats.total*0.93):0 },
    { day:"Thu", agents:stats?.total ? Math.floor(stats.total*0.96):0 },
    { day:"Fri", agents:stats?.total ? Math.floor(stats.total*0.98):0 },
    { day:"Sat", agents:stats?.total ? Math.floor(stats.total*0.99):0 },
    { day:"Sun", agents:stats?.total || 0 },
  ];

  if (loading) {
    return (
      <div style={{ display:"flex", alignItems:"center", justifyContent:"center", height:400 }}>
        <Spinner size={32} />
      </div>
    );
  }

  return (
    <div style={{ padding:"24px", display:"flex", flexDirection:"column", gap:20 }}>
      {/* Page header */}
      <div>
        <h1 style={{ fontSize:22, fontWeight:700, color:T.navy, margin:0 }}>Overview</h1>
        <p style={{ fontSize:13, color:T.muted, margin:"4px 0 0" }}>
          Real-time AI agent inventory across your estate
        </p>
      </div>

      {/* Stat cards */}
      <div style={{ display:"grid", gridTemplateColumns:"repeat(4,1fr)", gap:12 }}>
        <StatCard label="Total agents"   value={stats?.total   ?? "—"} icon="◫" color={T.teal}
          onClick={() => onNavigate("inventory")} sub="across all surfaces" />
        <StatCard label="Running now"    value={stats?.running  ?? "—"} icon="▶" color={T.green}
          sub="active this session" />
        <StatCard label="Shadow AI"      value={stats?.shadow   ?? "—"} icon="⚠" color={T.red}
          pulse={stats?.shadow > 0} sub="no registered owner"
          onClick={() => onNavigate("inventory", { shadow_only:true })} />
        <StatCard label="Orphaned"       value={stats?.orphaned ?? "—"} icon="⊘" color={T.amber}
          sub="owner unverified"
          onClick={() => onNavigate("inventory", { orphaned_only:true })} />
      </div>

      {/* Charts row */}
      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr 320px", gap:16 }}>
        {/* Discovery trend */}
        <Card>
          <div style={{ fontWeight:600, fontSize:14, color:T.navy, marginBottom:16 }}>
            7-day discovery trend
          </div>
          <ResponsiveContainer width="100%" height={160}>
            <AreaChart data={trendData}>
              <defs>
                <linearGradient id="teal" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor={T.teal} stopOpacity={0.2}/>
                  <stop offset="95%" stopColor={T.teal} stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={T.border} />
              <XAxis dataKey="day" tick={{ fontSize:11, fill:T.muted }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize:11, fill:T.muted }} axisLine={false} tickLine={false} />
              <Tooltip contentStyle={{ fontSize:12, border:`1px solid ${T.border}`, borderRadius:8 }} />
              <Area type="monotone" dataKey="agents" stroke={T.teal} strokeWidth={2} fill="url(#teal)" />
            </AreaChart>
          </ResponsiveContainer>
        </Card>

        {/* Framework breakdown */}
        <Card>
          <div style={{ fontWeight:600, fontSize:14, color:T.navy, marginBottom:16 }}>
            Agents by framework
          </div>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={fwData} layout="vertical">
              <XAxis type="number" tick={{ fontSize:11, fill:T.muted }} axisLine={false} tickLine={false} />
              <YAxis type="category" dataKey="name" tick={{ fontSize:11, fill:T.muted }} axisLine={false} tickLine={false} width={80} />
              <Tooltip contentStyle={{ fontSize:12, border:`1px solid ${T.border}`, borderRadius:8 }} />
              <Bar dataKey="value" fill={T.teal} radius={[0,4,4,0]} barSize={14} />
            </BarChart>
          </ResponsiveContainer>
        </Card>

        {/* Cloud distribution */}
        <Card>
          <div style={{ fontWeight:600, fontSize:14, color:T.navy, marginBottom:12 }}>
            By cloud provider
          </div>
          <PieChart width={140} height={140} style={{ margin:"0 auto" }}>
            <Pie data={cloudData} cx={65} cy={65} innerRadius={40} outerRadius={65}
              dataKey="value" paddingAngle={3}>
              {cloudData.map((entry,i) => <Cell key={i} fill={entry.fill} />)}
            </Pie>
            <Tooltip contentStyle={{ fontSize:12, border:`1px solid ${T.border}`, borderRadius:8 }} />
          </PieChart>
          <div style={{ display:"flex", flexWrap:"wrap", gap:"6px 12px", marginTop:8 }}>
            {cloudData.map((d,i) => (
              <div key={i} style={{ display:"flex", alignItems:"center", gap:5, fontSize:11, color:T.muted }}>
                <span style={{ width:8, height:8, borderRadius:2, background:d.fill, display:"inline-block" }} />
                {d.name} ({d.value})
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Bottom row */}
      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:16 }}>
        {/* Connector health */}
        <Card>
          <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:14 }}>
            <span style={{ fontWeight:600, fontSize:14, color:T.navy }}>Connector health</span>
            <Button variant="ghost" size="sm" onClick={() => onNavigate("connectors")}>View all</Button>
          </div>
          <div style={{ display:"flex", flexDirection:"column", gap:8 }}>
            {connectors.length === 0 && <div style={{ fontSize:13, color:T.muted }}>No connectors configured</div>}
            {connectors.map(c => (
              <div key={c.connector_id} style={{
                display:"flex", alignItems:"center", justifyContent:"space-between",
                padding:"8px 10px", borderRadius:8, background:T.offwhite
              }}>
                <div style={{ display:"flex", alignItems:"center", gap:8 }}>
                  <StatusDot status={c.status} />
                  <span style={{ fontSize:13, fontWeight:500, color:T.slate }}>{c.display_name}</span>
                </div>
                <div style={{ display:"flex", alignItems:"center", gap:8 }}>
                  <span style={{ fontSize:11, color:T.muted }}>{c.agents_found} agents</span>
                  <Badge color={c.status==="healthy"?"green":c.status==="warning"?"amber":"red"}>
                    {c.status}
                  </Badge>
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* Live event feed */}
        <Card>
          <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:14 }}>
            <div style={{ display:"flex", alignItems:"center", gap:8 }}>
              <span style={{ fontWeight:600, fontSize:14, color:T.navy }}>Live events</span>
              <span style={{
                fontSize:10, fontWeight:600, padding:"2px 6px", borderRadius:20,
                background:T.tealPale, color:T.teal
              }}>WebSocket</span>
            </div>
          </div>
          <EventFeed events={liveEvents} />
        </Card>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// WEEK 2 — Inventory
// ═══════════════════════════════════════════════════════════════════════════════
function InventoryPage({ onSelectAgent, initialFilters = {} }) {
  const { token } = useAuth();
  const [agents, setAgents]   = useState([]);
  const [total, setTotal]     = useState(0);
  const [page, setPage]       = useState(1);
  const [loading, setLoading] = useState(true);
  const [query, setQuery]     = useState("");
  const [cloudF, setCloudF]   = useState(initialFilters.cloud || "");
  const [fwF, setFwF]         = useState(initialFilters.framework || "");
  const [envF, setEnvF]       = useState(initialFilters.env || "");
  const [shadowOnly, setShadowOnly]     = useState(!!initialFilters.shadow_only);
  const [orphanedOnly, setOrphanedOnly] = useState(!!initialFilters.orphaned_only);
  const PAGE_SIZE = 15;

  const search = useCallback(async (p = 1) => {
    setLoading(true);
    try {
      const body = {
        query: query || undefined,
        cloud: cloudF || undefined,
        framework: fwF || undefined,
        env: envF || undefined,
        shadow_only: shadowOnly,
        orphaned_only: orphanedOnly,
        page: p,
        page_size: PAGE_SIZE,
      };
      const d = await apiFetch("/api/v1/agents/search", {
        method:"POST", body:JSON.stringify(body)
      }, token);
      setAgents(d.items || []);
      setTotal(d.total || 0);
      setPage(p);
    } catch (_) {}
    setLoading(false);
  }, [token, query, cloudF, fwF, envF, shadowOnly, orphanedOnly]);

  useEffect(() => { search(1); }, [cloudF, fwF, envF, shadowOnly, orphanedOnly]);

  const handleSearch = () => search(1);

  const statusColor = { running:"green", stopped:"gray", error:"red", unknown:"gray" };
  const envColor    = { production:"teal", dev:"blue", uat:"amber", staging:"purple", unknown:"gray" };

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div style={{ padding:"24px", display:"flex", flexDirection:"column", gap:16 }}>
      {/* Header */}
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start" }}>
        <div>
          <h1 style={{ fontSize:22, fontWeight:700, color:T.navy, margin:0 }}>AI Inventory</h1>
          <p style={{ fontSize:13, color:T.muted, margin:"4px 0 0" }}>
            {total} agents discovered across all surfaces
          </p>
        </div>
      </div>

      {/* Filters */}
      <Card style={{ padding:"14px 16px" }}>
        <div style={{ display:"grid", gridTemplateColumns:"1fr auto auto auto", gap:10, alignItems:"center" }}>
          <div style={{ display:"flex", gap:8, alignItems:"center" }}>
            <Input value={query} onChange={setQuery} placeholder="Search agents, owners, models…"
              onKeyDown={e => e.key==="Enter" && handleSearch()} style={{ maxWidth:300 }} />
            <Button onClick={handleSearch} variant="secondary" size="sm">Search</Button>
          </div>
          <Select value={cloudF} onChange={setCloudF} options={[
            {value:"",label:"All clouds"},{value:"azure",label:"Azure"},
            {value:"aws",label:"AWS"},{value:"gcp",label:"GCP"},{value:"local",label:"Local"}
          ]} />
          <Select value={envF} onChange={setEnvF} options={[
            {value:"",label:"All envs"},{value:"production",label:"Production"},
            {value:"dev",label:"Dev"},{value:"uat",label:"UAT"},{value:"staging",label:"Staging"}
          ]} />
          <div style={{ display:"flex", gap:12, alignItems:"center" }}>
            <label style={{ display:"flex", alignItems:"center", gap:6, fontSize:13, color:T.slate, cursor:"pointer" }}>
              <input type="checkbox" checked={shadowOnly} onChange={e => setShadowOnly(e.target.checked)} />
              Shadow only
            </label>
            <label style={{ display:"flex", alignItems:"center", gap:6, fontSize:13, color:T.slate, cursor:"pointer" }}>
              <input type="checkbox" checked={orphanedOnly} onChange={e => setOrphanedOnly(e.target.checked)} />
              Orphaned
            </label>
          </div>
        </div>
      </Card>

      {/* Table */}
      <Card style={{ padding:0, overflow:"hidden" }}>
        <div style={{ overflowX:"auto" }}>
          <table style={{ width:"100%", borderCollapse:"collapse" }}>
            <thead>
              <tr style={{ background:T.offwhite, borderBottom:`1px solid ${T.border}` }}>
                {["Agent", "Framework", "Cloud", "Environment", "Model", "Status", "Owner", ""].map(h => (
                  <th key={h} style={{
                    padding:"10px 14px", textAlign:"left",
                    fontSize:11, fontWeight:600, color:T.muted, whiteSpace:"nowrap"
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={8} style={{ textAlign:"center", padding:40 }}>
                  <Spinner />
                </td></tr>
              )}
              {!loading && agents.length === 0 && (
                <tr><td colSpan={8}>
                  <EmptyState icon="◫" title="No agents found"
                    subtitle="Adjust your filters or trigger a discovery scan" />
                </td></tr>
              )}
              {!loading && agents.map(a => (
                <tr key={a.agent_id}
                  onClick={() => onSelectAgent(a.agent_id)}
                  style={{
                    borderBottom:`1px solid ${T.border}`, cursor:"pointer",
                    transition:"background .1s"
                  }}
                  onMouseEnter={e => e.currentTarget.style.background=T.offwhite}
                  onMouseLeave={e => e.currentTarget.style.background="#fff"}
                >
                  <td style={{ padding:"12px 14px" }}>
                    <div style={{ fontWeight:600, fontSize:13, color:T.navy }}>{a.name}</div>
                    <div style={{ fontSize:11, color:T.muted, marginTop:2 }}>{a.agent_id}</div>
                  </td>
                  <td style={{ padding:"12px 14px" }}>
                    <Badge color="teal">{a.framework || "—"}</Badge>
                  </td>
                  <td style={{ padding:"12px 14px" }}>
                    <CloudBadge cloud={a.cloud} />
                  </td>
                  <td style={{ padding:"12px 14px" }}>
                    <Badge color={envColor[a.env] || "gray"}>{a.env || "—"}</Badge>
                  </td>
                  <td style={{ padding:"12px 14px", fontSize:12, color:T.muted }}>
                    {a.model_name || "—"}
                  </td>
                  <td style={{ padding:"12px 14px" }}>
                    <div style={{ display:"flex", alignItems:"center", gap:6 }}>
                      <StatusDot status={a.status} />
                      <span style={{ fontSize:12, color:T.slate }}>{a.status}</span>
                    </div>
                  </td>
                  <td style={{ padding:"12px 14px" }}>
                    <div style={{ display:"flex", flexDirection:"column", gap:3 }}>
                      {a.is_shadow && <Badge color="red">Shadow</Badge>}
                      {a.is_orphaned && <Badge color="amber">Orphaned</Badge>}
                      {!a.is_shadow && !a.is_orphaned && (
                        <span style={{ fontSize:12, color:T.muted }}>{a.owner || "—"}</span>
                      )}
                    </div>
                  </td>
                  <td style={{ padding:"12px 14px" }}>
                    <Button variant="ghost" size="sm">View →</Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div style={{
            display:"flex", justifyContent:"space-between", alignItems:"center",
            padding:"12px 16px", borderTop:`1px solid ${T.border}`
          }}>
            <span style={{ fontSize:12, color:T.muted }}>
              Showing {(page-1)*PAGE_SIZE+1}–{Math.min(page*PAGE_SIZE,total)} of {total}
            </span>
            <div style={{ display:"flex", gap:6 }}>
              <Button variant="ghost" size="sm" disabled={page===1} onClick={() => search(page-1)}>← Prev</Button>
              <Button variant="ghost" size="sm" disabled={page===totalPages} onClick={() => search(page+1)}>Next →</Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// WEEK 3 — Agent Detail with visual relationship graph
// ═══════════════════════════════════════════════════════════════════════════════

// SVG force-layout simulation (no D3 dependency)
function useGraphLayout(nodes, edges) {
  const [positions, setPositions] = useState({});

  useEffect(() => {
    if (!nodes || nodes.length === 0) return;

    const W = 580, H = 340;
    const pos = {};

    // Initial positions in a circle
    nodes.forEach((n, i) => {
      const angle = (i / nodes.length) * 2 * Math.PI - Math.PI / 2;
      const r = nodes.length > 1 ? 120 : 0;
      pos[n.id] = {
        x: W/2 + r * Math.cos(angle),
        y: H/2 + r * Math.sin(angle),
        vx: 0, vy: 0
      };
    });

    // Simple force simulation
    for (let iter = 0; iter < 80; iter++) {
      // Repulsion between all nodes
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i+1; j < nodes.length; j++) {
          const a = pos[nodes[i].id], b = pos[nodes[j].id];
          const dx = b.x - a.x, dy = b.y - a.y;
          const dist = Math.sqrt(dx*dx + dy*dy) || 1;
          const force = 2500 / (dist * dist);
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;
          a.vx -= fx; a.vy -= fy;
          b.vx += fx; b.vy += fy;
        }
      }
      // Attraction along edges
      edges.forEach(e => {
        const a = pos[e.source], b = pos[e.target];
        if (!a || !b) return;
        const dx = b.x - a.x, dy = b.y - a.y;
        const dist = Math.sqrt(dx*dx + dy*dy) || 1;
        const force = (dist - 140) * 0.04;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        a.vx += fx; a.vy += fy;
        b.vx -= fx; b.vy -= fy;
      });
      // Center gravity
      nodes.forEach(n => {
        const p = pos[n.id];
        p.vx += (W/2 - p.x) * 0.008;
        p.vy += (H/2 - p.y) * 0.008;
      });
      // Apply velocity + damping + bounds
      nodes.forEach(n => {
        const p = pos[n.id];
        p.x += p.vx * 0.6;
        p.y += p.vy * 0.6;
        p.vx *= 0.7;
        p.vy *= 0.7;
        p.x = Math.max(60, Math.min(W-60, p.x));
        p.y = Math.max(40, Math.min(H-40, p.y));
      });
    }
    setPositions({ ...pos });
  }, [nodes?.length, edges?.length]);

  return positions;
}

function RelationshipGraph({ graph, rootId }) {
  const positions = useGraphLayout(graph?.nodes, graph?.edges);
  const [hoveredNode, setHoveredNode] = useState(null);
  const W = 580, H = 340;

  if (!graph || graph.nodes.length === 0) {
    return (
      <EmptyState icon="⊞" title="No relationships mapped"
        subtitle="This agent has no known connections to other agents" />
    );
  }

  if (Object.keys(positions).length === 0) {
    return <div style={{ display:"flex", justifyContent:"center", padding:60 }}><Spinner /></div>;
  }

  const fwColor = (fw) => T.fw[fw] || T.muted;
  const relColor = { CALLS:"#2563EB", DELEGATES_TO:"#059669", USES_TOOL:"#D97706", default:T.muted };

  return (
    <div style={{ position:"relative", background:T.offwhite, borderRadius:10, overflow:"hidden" }}>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display:"block" }}>
        <defs>
          <marker id="gr-arrow" viewBox="0 0 10 10" refX="8" refY="5"
            markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke"
              strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          </marker>
        </defs>

        {/* Edges */}
        {graph.edges.map((e, i) => {
          const from = positions[e.source], to = positions[e.target];
          if (!from || !to) return null;
          const color = relColor[e.type] || relColor.default;
          const mx = (from.x + to.x) / 2;
          const my = (from.y + to.y) / 2 - 20;
          return (
            <g key={i}>
              <path
                d={`M${from.x},${from.y} Q${mx},${my} ${to.x},${to.y}`}
                fill="none" stroke={color} strokeWidth={1.5} opacity={0.7}
                markerEnd="url(#gr-arrow)"
              />
              <text x={mx} y={my-4} textAnchor="middle"
                style={{ fontSize:10, fill:T.muted }}>
                {e.type?.replace(/_/g," ").toLowerCase()}
              </text>
            </g>
          );
        })}

        {/* Nodes */}
        {graph.nodes.map(n => {
          const p = positions[n.id];
          if (!p) return null;
          const isRoot = n.id === rootId;
          const isHovered = hoveredNode === n.id;
          const r = isRoot ? 26 : 20;
          const color = fwColor(n.framework);
          return (
            <g key={n.id}
              onMouseEnter={() => setHoveredNode(n.id)}
              onMouseLeave={() => setHoveredNode(null)}
              style={{ cursor:"pointer" }}>
              <circle
                cx={p.x} cy={p.y} r={r + (isHovered?2:0)}
                fill={isRoot ? T.teal : "#fff"}
                stroke={color} strokeWidth={isRoot?2:1.5}
              />
              {isRoot && (
                <circle cx={p.x} cy={p.y} r={r+5}
                  fill="none" stroke={T.teal} strokeWidth={1} opacity={0.3}
                  strokeDasharray="3 2" />
              )}
              <text x={p.x} y={p.y} textAnchor="middle" dominantBaseline="central"
                style={{ fontSize:9, fontWeight:700, fill:isRoot?"#fff":color, userSelect:"none" }}>
                {(n.framework || n.type || "?").slice(0,3).toUpperCase()}
              </text>
              <text x={p.x} y={p.y + r + 10} textAnchor="middle"
                style={{ fontSize:10, fill:T.slate, userSelect:"none", fontWeight:isRoot?600:400 }}>
                {n.name?.length > 16 ? n.name.slice(0,14)+"…" : n.name}
              </text>
            </g>
          );
        })}
      </svg>

      {/* Legend */}
      <div style={{ position:"absolute", bottom:8, left:10, display:"flex", gap:10 }}>
        {Object.entries(relColor).filter(([k]) => k !== "default").map(([type, color]) => (
          <div key={type} style={{ display:"flex", alignItems:"center", gap:4, fontSize:10, color:T.muted }}>
            <span style={{ width:16, height:2, background:color, display:"inline-block" }} />
            {type.replace(/_/g," ").toLowerCase()}
          </div>
        ))}
      </div>
    </div>
  );
}

function AgentDetailPage({ agentId, onBack }) {
  const { token, user } = useAuth();
  const toast = useToast();
  const [agent, setAgent]   = useState(null);
  const [graph, setGraph]   = useState(null);
  const [history, setHistory] = useState([]);
  const [tab, setTab]       = useState("overview");
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [editOwner, setEditOwner] = useState("");

  useEffect(() => {
    if (!agentId) return;
    setLoading(true);
    Promise.all([
      apiFetch(`/api/v1/agents/${agentId}`, {}, token),
      apiFetch(`/api/v1/agents/${agentId}/graph`, {}, token),
      apiFetch(`/api/v1/agents/${agentId}/history`, {}, token),
    ]).then(([a, g, h]) => {
      setAgent(a); setGraph(g); setHistory(h.changes || []);
      setEditOwner(a.owner || "");
    }).catch(() => {}).finally(() => setLoading(false));
  }, [agentId, token]);

  const saveOwner = async () => {
    try {
      const updated = await apiFetch(`/api/v1/agents/${agentId}`,
        { method:"PATCH", body:JSON.stringify({ owner:editOwner }) }, token);
      setAgent(updated);
      setEditing(false);
      toast("Owner updated", "success");
    } catch (e) {
      toast(e.detail || "Update failed", "error");
    }
  };

  const tabs = [
    { id:"overview",  label:"Overview" },
    { id:"graph",     label:`Graph (${graph?.edges?.length ?? 0} links)` },
    { id:"history",   label:`History (${history.length})` },
  ];

  if (loading) {
    return (
      <div style={{ padding:24 }}>
        <Button variant="ghost" onClick={onBack} style={{ marginBottom:16 }}>← Back</Button>
        <div style={{ display:"flex", justifyContent:"center", padding:80 }}><Spinner size={32} /></div>
      </div>
    );
  }

  if (!agent) {
    return (
      <div style={{ padding:24 }}>
        <Button variant="ghost" onClick={onBack} style={{ marginBottom:16 }}>← Back</Button>
        <EmptyState icon="⊘" title="Agent not found" subtitle="This agent may have been removed" />
      </div>
    );
  }

  return (
    <div style={{ padding:"24px", display:"flex", flexDirection:"column", gap:16 }}>
      {/* Breadcrumb */}
      <div style={{ display:"flex", alignItems:"center", gap:8 }}>
        <button onClick={onBack} style={{
          background:"none", border:"none", color:T.teal, cursor:"pointer",
          fontSize:13, fontWeight:500, padding:0
        }}>← Inventory</button>
        <span style={{ color:T.muted }}>/</span>
        <span style={{ fontSize:13, color:T.muted }}>{agent.name}</span>
      </div>

      {/* Agent header */}
      <Card>
        <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start" }}>
          <div>
            <div style={{ display:"flex", alignItems:"center", gap:10, marginBottom:8 }}>
              <h2 style={{ fontSize:20, fontWeight:700, color:T.navy, margin:0 }}>{agent.name}</h2>
              {agent.is_shadow && <Badge color="red">Shadow AI</Badge>}
              {agent.is_orphaned && <Badge color="amber">Orphaned</Badge>}
              <StatusDot status={agent.status} />
              <span style={{ fontSize:13, color:T.muted }}>{agent.status}</span>
            </div>
            <div style={{ display:"flex", gap:8, flexWrap:"wrap" }}>
              <CloudBadge cloud={agent.cloud} />
              <Badge color="teal">{agent.framework || "—"}</Badge>
              <Badge color="blue">{agent.env || "—"}</Badge>
              <Badge color="gray">{agent.agent_type || "—"}</Badge>
            </div>
          </div>
          <div style={{ fontSize:11, color:T.muted, textAlign:"right" }}>
            <div>ID: {agent.agent_id}</div>
            <div style={{ marginTop:4 }}>
              Discovered {agent.discovered_at ? new Date(agent.discovered_at).toLocaleDateString() : "—"}
            </div>
          </div>
        </div>
      </Card>

      {/* Tabs */}
      <div style={{ display:"flex", gap:2, borderBottom:`1px solid ${T.border}`, paddingBottom:0 }}>
        {tabs.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            background:"none", border:"none", cursor:"pointer",
            padding:"8px 16px", fontSize:13, fontWeight:500,
            color: tab===t.id ? T.teal : T.muted,
            borderBottom: tab===t.id ? `2px solid ${T.teal}` : "2px solid transparent",
            marginBottom:-1, transition:"all .15s"
          }}>{t.label}</button>
        ))}
      </div>

      {/* Overview tab */}
      {tab === "overview" && (
        <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:16 }}>
          <Card>
            <div style={{ fontWeight:600, fontSize:14, color:T.navy, marginBottom:14 }}>Identity</div>
            <div style={{ display:"flex", flexDirection:"column", gap:10 }}>
              {[
                ["Agent ID",    agent.agent_id],
                ["Name",        agent.name],
                ["Type",        agent.agent_type || "—"],
                ["Framework",   agent.framework  || "—"],
                ["Connector",   agent.connector  || "—"],
              ].map(([k,v]) => (
                <div key={k} style={{ display:"flex", justifyContent:"space-between", fontSize:13 }}>
                  <span style={{ color:T.muted }}>{k}</span>
                  <span style={{ fontWeight:500, color:T.slate }}>{v}</span>
                </div>
              ))}
            </div>
          </Card>

          <Card>
            <div style={{ fontWeight:600, fontSize:14, color:T.navy, marginBottom:14 }}>Model</div>
            <div style={{ display:"flex", flexDirection:"column", gap:10 }}>
              {[
                ["Provider",    agent.model_provider || "—"],
                ["Model",       agent.model_name     || "—"],
                ["Tools",       agent.tools ?? "—"],
                ["Region",      agent.region         || "—"],
                ["Device",      agent.endpoint_device || "—"],
              ].map(([k,v]) => (
                <div key={k} style={{ display:"flex", justifyContent:"space-between", fontSize:13 }}>
                  <span style={{ color:T.muted }}>{k}</span>
                  <span style={{ fontWeight:500, color:T.slate }}>{v}</span>
                </div>
              ))}
            </div>
          </Card>

          <Card style={{ gridColumn:"1/-1" }}>
            <div style={{ fontWeight:600, fontSize:14, color:T.navy, marginBottom:14 }}>
              Ownership & governance
            </div>
            <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr 1fr", gap:16 }}>
              <div>
                <div style={{ fontSize:11, color:T.muted, marginBottom:4 }}>Owner</div>
                {editing ? (
                  <div style={{ display:"flex", gap:6 }}>
                    <Input value={editOwner} onChange={setEditOwner} placeholder="owner@corp.com"
                      style={{ fontSize:12, padding:"5px 8px" }} />
                    <Button size="sm" onClick={saveOwner}>Save</Button>
                    <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
                  </div>
                ) : (
                  <div style={{ display:"flex", alignItems:"center", gap:8 }}>
                    <span style={{ fontSize:13, fontWeight:500, color:T.slate }}>
                      {agent.owner || <span style={{ color:T.muted }}>Unassigned</span>}
                    </span>
                    {user?.role === "admin" && (
                      <button onClick={() => setEditing(true)} style={{
                        background:"none", border:`1px solid ${T.border}`, borderRadius:6,
                        cursor:"pointer", fontSize:11, color:T.muted, padding:"2px 8px"
                      }}>Edit</button>
                    )}
                  </div>
                )}
              </div>
              <div>
                <div style={{ fontSize:11, color:T.muted, marginBottom:4 }}>Business unit</div>
                <span style={{ fontSize:13, fontWeight:500, color:T.slate }}>
                  {agent.business_unit || <span style={{ color:T.muted }}>—</span>}
                </span>
              </div>
              <div>
                <div style={{ fontSize:11, color:T.muted, marginBottom:4 }}>Risk flags</div>
                <div style={{ display:"flex", gap:4, flexWrap:"wrap" }}>
                  {agent.is_shadow   && <Badge color="red">Shadow</Badge>}
                  {agent.is_orphaned && <Badge color="amber">Orphaned</Badge>}
                  {!agent.is_shadow && !agent.is_orphaned && (
                    <Badge color="green">Compliant</Badge>
                  )}
                </div>
              </div>
            </div>
          </Card>
        </div>
      )}

      {/* Graph tab */}
      {tab === "graph" && (
        <Card>
          <div style={{ fontWeight:600, fontSize:14, color:T.navy, marginBottom:14 }}>
            Agent relationships
            <span style={{ fontSize:12, color:T.muted, fontWeight:400, marginLeft:8 }}>
              {graph?.nodes?.length || 0} agents · {graph?.edges?.length || 0} connections
            </span>
          </div>
          <RelationshipGraph graph={graph} rootId={agentId} />
        </Card>
      )}

      {/* History tab */}
      {tab === "history" && (
        <Card>
          <div style={{ fontWeight:600, fontSize:14, color:T.navy, marginBottom:14 }}>Change history</div>
          {history.length === 0 ? (
            <EmptyState icon="📋" title="No history yet"
              subtitle="Changes to this agent will appear here" />
          ) : (
            <div style={{ display:"flex", flexDirection:"column", gap:8 }}>
              {history.map((h, i) => (
                <div key={i} style={{
                  display:"flex", alignItems:"flex-start", gap:12,
                  padding:"10px 12px", borderRadius:8, background:T.offwhite,
                  borderLeft:`3px solid ${T.teal}`
                }}>
                  <div style={{ flex:1 }}>
                    <div style={{ fontSize:13, fontWeight:500, color:T.slate }}>{h.summary || h.change_type}</div>
                    <div style={{ fontSize:11, color:T.muted, marginTop:3 }}>
                      {h.connector_id && `via ${h.connector_id} · `}
                      v{h.version} · {h.changed_at ? new Date(h.changed_at).toLocaleString() : "—"}
                    </div>
                  </div>
                  <Badge color="teal">{h.change_type}</Badge>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// WEEK 4 — Connectors
// ═══════════════════════════════════════════════════════════════════════════════
function ConnectorsPage() {
  const { token, user } = useAuth();
  const toast = useToast();
  const [connectors, setConnectors] = useState([]);
  const [jobs, setJobs]     = useState([]);
  const [coverage, setCoverage] = useState(null);
  const [loading, setLoading]   = useState(true);
  const [showAdd, setShowAdd]   = useState(false);
  const [scanning, setScanning] = useState({});
  const [newConn, setNewConn]   = useState({
    connector_id:"", display_name:"", connector_type:"ai_platform"
  });

  const load = useCallback(async () => {
    try {
      const [c, j, cov] = await Promise.all([
        apiFetch("/api/v1/connectors", {}, token),
        apiFetch("/api/v1/discovery/jobs", {}, token),
        apiFetch("/api/v1/discovery/coverage", {}, token),
      ]);
      setConnectors(c.connectors || []);
      setJobs((j.jobs || []).slice(0, 8));
      setCoverage(cov);
    } catch (_) {}
    setLoading(false);
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const testConnector = async (id) => {
    try {
      const r = await apiFetch(`/api/v1/connectors/${id}/test`, { method:"POST" }, token);
      toast(r.ok ? `${id}: connection OK` : `${id}: test failed`, r.ok?"success":"error");
    } catch (e) {
      toast(e.detail || "Test failed", "error");
    }
  };

  const triggerScan = async (id) => {
    setScanning(s => ({ ...s, [id]:true }));
    try {
      await apiFetch("/api/v1/discovery/trigger", {
        method:"POST", body:JSON.stringify({ connector_id:id, job_type:"incremental" })
      }, token);
      toast(`Discovery started for ${id}`, "success");
      setTimeout(() => { load(); setScanning(s => ({ ...s, [id]:false })); }, 3000);
    } catch (e) {
      toast(e.detail || "Scan failed", "error");
      setScanning(s => ({ ...s, [id]:false }));
    }
  };

  const deleteConnector = async (id) => {
    try {
      await apiFetch(`/api/v1/connectors/${id}`, { method:"DELETE" }, token);
      toast("Connector removed", "success");
      load();
    } catch (e) {
      toast(e.detail || "Delete failed", "error");
    }
  };

  const addConnector = async () => {
    if (!newConn.connector_id || !newConn.display_name) {
      toast("Fill in all required fields", "error"); return;
    }
    try {
      await apiFetch("/api/v1/connectors", { method:"POST", body:JSON.stringify(newConn) }, token);
      toast("Connector added", "success");
      setShowAdd(false);
      setNewConn({ connector_id:"", display_name:"", connector_type:"ai_platform" });
      load();
    } catch (e) {
      toast(e.detail || "Failed to add", "error");
    }
  };

  const jobStatus = { completed:"green", running:"blue", failed:"red", queued:"amber" };

  return (
    <div style={{ padding:"24px", display:"flex", flexDirection:"column", gap:16 }}>
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start" }}>
        <div>
          <h1 style={{ fontSize:22, fontWeight:700, color:T.navy, margin:0 }}>Connectors</h1>
          <p style={{ fontSize:13, color:T.muted, margin:"4px 0 0" }}>
            {coverage ? `${coverage.coverage_pct}% coverage · ${coverage.healthy_connectors}/${coverage.total_connectors} healthy` : "Loading…"}
          </p>
        </div>
        {user?.role === "admin" && (
          <Button onClick={() => setShowAdd(true)}>+ Add connector</Button>
        )}
      </div>

      {/* Coverage bar */}
      {coverage && (
        <Card style={{ padding:"12px 16px" }}>
          <div style={{ display:"flex", justifyContent:"space-between", marginBottom:6, fontSize:12 }}>
            <span style={{ color:T.slate, fontWeight:500 }}>Discovery coverage</span>
            <span style={{ color:T.muted }}>{coverage.coverage_pct}%</span>
          </div>
          <div style={{ background:T.offwhite, borderRadius:4, height:6, overflow:"hidden" }}>
            <div style={{
              height:"100%", width:`${coverage.coverage_pct}%`,
              background: coverage.coverage_pct > 80 ? T.green : coverage.coverage_pct > 50 ? T.amber : T.red,
              borderRadius:4, transition:"width .4s"
            }} />
          </div>
        </Card>
      )}

      {/* Connectors grid */}
      <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fill,minmax(300px,1fr))", gap:12 }}>
        {loading && [1,2,3].map(i => (
          <Card key={i} style={{ height:140, background:T.offwhite, animation:"pulse 1.5s ease-in-out infinite" }} />
        ))}
        {!loading && connectors.map(c => (
          <Card key={c.connector_id}>
            <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start", marginBottom:10 }}>
              <div>
                <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:4 }}>
                  <StatusDot status={c.status} />
                  <span style={{ fontWeight:600, fontSize:14, color:T.navy }}>{c.display_name}</span>
                </div>
                <div style={{ fontSize:11, color:T.muted }}>{c.connector_type} · {c.agents_found} agents found</div>
              </div>
              <Badge color={c.status==="healthy"?"green":c.status==="warning"?"amber":"gray"}>{c.status}</Badge>
            </div>

            <div style={{ fontSize:11, color:T.muted, marginBottom:12 }}>
              Schedule: {c.schedule || "—"} ·
              Last run: {c.last_run ? new Date(c.last_run).toLocaleString() : "Never"}
            </div>

            <div style={{ display:"flex", gap:6, flexWrap:"wrap" }}>
              <Button size="sm" variant="secondary" onClick={() => testConnector(c.connector_id)}>
                Test
              </Button>
              {user?.role === "admin" && (
                <>
                  <Button size="sm" variant="secondary"
                    onClick={() => triggerScan(c.connector_id)}
                    disabled={scanning[c.connector_id]}>
                    {scanning[c.connector_id] ? "Scanning…" : "Scan now"}
                  </Button>
                  <Button size="sm" variant="danger"
                    onClick={() => deleteConnector(c.connector_id)}>
                    Remove
                  </Button>
                </>
              )}
            </div>
          </Card>
        ))}
        {!loading && connectors.length === 0 && (
          <div style={{ gridColumn:"1/-1" }}>
            <EmptyState icon="⌁" title="No connectors configured"
              subtitle="Add a connector to start discovering AI agents"
              action={user?.role==="admin" && <Button onClick={() => setShowAdd(true)}>Add first connector</Button>} />
          </div>
        )}
      </div>

      {/* Recent jobs */}
      {jobs.length > 0 && (
        <Card>
          <div style={{ fontWeight:600, fontSize:14, color:T.navy, marginBottom:14 }}>Recent discovery jobs</div>
          <table style={{ width:"100%", borderCollapse:"collapse" }}>
            <thead>
              <tr style={{ borderBottom:`1px solid ${T.border}` }}>
                {["Job ID","Connector","Type","Status","Agents","Duration"].map(h => (
                  <th key={h} style={{ padding:"6px 10px", textAlign:"left", fontSize:11, fontWeight:600, color:T.muted }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {jobs.map(j => {
                const dur = j.completed_at && j.started_at
                  ? `${Math.round((new Date(j.completed_at)-new Date(j.started_at))/1000)}s`
                  : "—";
                return (
                  <tr key={j.job_id} style={{ borderBottom:`1px solid ${T.border}` }}>
                    <td style={{ padding:"8px 10px", fontSize:11, color:T.muted }}>{j.job_id.slice(-8)}</td>
                    <td style={{ padding:"8px 10px", fontSize:12, fontWeight:500 }}>{j.connector_id}</td>
                    <td style={{ padding:"8px 10px", fontSize:12, color:T.muted }}>{j.job_type}</td>
                    <td style={{ padding:"8px 10px" }}>
                      <Badge color={jobStatus[j.status] || "gray"}>{j.status}</Badge>
                    </td>
                    <td style={{ padding:"8px 10px", fontSize:12 }}>{j.agents_found ?? "—"}</td>
                    <td style={{ padding:"8px 10px", fontSize:12, color:T.muted }}>{dur}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}

      {/* Add connector modal */}
      <Modal open={showAdd} onClose={() => setShowAdd(false)} title="Add connector">
        <div style={{ display:"flex", flexDirection:"column", gap:14 }}>
          {[
            { label:"Connector ID", key:"connector_id", placeholder:"azure_ai_foundry" },
            { label:"Display name", key:"display_name", placeholder:"Azure AI Foundry" },
          ].map(f => (
            <div key={f.key}>
              <label style={{ fontSize:12, fontWeight:600, color:T.slate, display:"block", marginBottom:6 }}>
                {f.label}
              </label>
              <Input value={newConn[f.key]} onChange={v => setNewConn(c => ({ ...c, [f.key]:v }))}
                placeholder={f.placeholder} />
            </div>
          ))}
          <div>
            <label style={{ fontSize:12, fontWeight:600, color:T.slate, display:"block", marginBottom:6 }}>
              Type
            </label>
            <Select value={newConn.connector_type}
              onChange={v => setNewConn(c => ({ ...c, connector_type:v }))}
              options={[
                {value:"ai_platform",    label:"Cloud AI Platform"},
                {value:"developer_platform", label:"Developer Platform"},
                {value:"agent_framework",label:"Agent Framework"},
                {value:"endpoint",       label:"Endpoint / EDR"},
                {value:"cloud_platform", label:"Container / K8s"},
              ]} />
          </div>
          <div style={{ display:"flex", gap:8, justifyContent:"flex-end", marginTop:4 }}>
            <Button variant="secondary" onClick={() => setShowAdd(false)}>Cancel</Button>
            <Button onClick={addConnector}>Add connector</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// WEEK 4 — SIEM
// ═══════════════════════════════════════════════════════════════════════════════
function SIEMPage() {
  const { token, user } = useAuth();
  const toast = useToast();
  const [targets, setTargets]   = useState([]);
  const [health, setHealth]     = useState(null);
  const [loading, setLoading]   = useState(true);
  const [showAdd, setShowAdd]   = useState(false);
  const [exporting, setExporting] = useState(false);
  const [newTarget, setNewTarget] = useState({
    name:"", siem_type:"splunk", delivery_method:"rest_push"
  });

  const load = useCallback(async () => {
    try {
      const [h, t] = await Promise.all([
        apiFetch("/api/v1/siem/health", {}, token),
        apiFetch("/api/v1/siem/targets", {}, token),
      ]);
      setHealth(h);
      setTargets(h.targets || t.targets || []);
    } catch (_) {}
    setLoading(false);
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const addTarget = async () => {
    if (!newTarget.name) { toast("Name is required", "error"); return; }
    try {
      await apiFetch("/api/v1/siem/targets", {
        method:"POST", body:JSON.stringify(newTarget)
      }, token);
      toast("SIEM target added", "success");
      setShowAdd(false);
      setNewTarget({ name:"", siem_type:"splunk", delivery_method:"rest_push" });
      load();
    } catch (e) {
      toast(e.detail || "Failed", "error");
    }
  };

  const batchExport = async () => {
    setExporting(true);
    try {
      const r = await apiFetch("/api/v1/siem/export/batch", { method:"POST" }, token);
      toast(`Exported ${r.events_exported} events to ${r.targets_delivered} targets`, "success");
      load();
    } catch (e) {
      toast(e.detail || "Export failed", "error");
    } finally {
      setExporting(false);
    }
  };

  const siemTypes = ["splunk","sentinel","elastic","qradar","chronicle","syslog","kafka","webhook"];

  return (
    <div style={{ padding:"24px", display:"flex", flexDirection:"column", gap:16 }}>
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start" }}>
        <div>
          <h1 style={{ fontSize:22, fontWeight:700, color:T.navy, margin:0 }}>SIEM Integration</h1>
          <p style={{ fontSize:13, color:T.muted, margin:"4px 0 0" }}>
            {health ? `${health.total_events_delivered_today || 0} events delivered today` : "Loading…"}
          </p>
        </div>
        <div style={{ display:"flex", gap:8 }}>
          {user?.role === "admin" && (
            <>
              <Button variant="secondary" onClick={batchExport} disabled={exporting}>
                {exporting ? "Exporting…" : "Batch export"}
              </Button>
              <Button onClick={() => setShowAdd(true)}>+ Add target</Button>
            </>
          )}
        </div>
      </div>

      {/* Health summary */}
      {health && (
        <div style={{ display:"grid", gridTemplateColumns:"repeat(4,1fr)", gap:12 }}>
          <StatCard label="Active targets"     value={health.active_targets ?? "—"}    icon="⊞" color={T.teal} />
          <StatCard label="Events delivered"   value={health.total_events_delivered_today ?? 0} icon="↑" color={T.green} />
          <StatCard label="Failures today"     value={health.total_failures_today ?? 0}  icon="⚠" color={T.red}
            pulse={(health.total_failures_today ?? 0) > 0} />
          <StatCard label="Total targets"      value={health.total_targets ?? "—"}      icon="⊞" color={T.blue} />
        </div>
      )}

      {/* Targets */}
      <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fill,minmax(280px,1fr))", gap:12 }}>
        {loading && [1,2].map(i => (
          <Card key={i} style={{ height:120, background:T.offwhite, animation:"pulse 1.5s ease-in-out infinite" }} />
        ))}
        {!loading && targets.map(t => {
          const rate = t.delivery_rate_pct ?? 100;
          return (
            <Card key={t.target_id}>
              <div style={{ display:"flex", justifyContent:"space-between", marginBottom:8 }}>
                <div>
                  <div style={{ fontWeight:600, fontSize:14, color:T.navy }}>{t.name}</div>
                  <div style={{ fontSize:11, color:T.muted, marginTop:2 }}>
                    {t.siem_type} · {t.delivery_method}
                  </div>
                </div>
                <Badge color={t.status==="active"?"green":"gray"}>{t.status}</Badge>
              </div>
              <div style={{ display:"flex", justifyContent:"space-between", fontSize:12, marginBottom:8 }}>
                <span style={{ color:T.muted }}>Delivery rate</span>
                <span style={{ fontWeight:600, color:rate>95?T.green:rate>80?T.amber:T.red }}>
                  {rate.toFixed(1)}%
                </span>
              </div>
              <div style={{ background:T.offwhite, borderRadius:4, height:4 }}>
                <div style={{
                  height:"100%", width:`${rate}%`,
                  background:rate>95?T.green:rate>80?T.amber:T.red,
                  borderRadius:4
                }} />
              </div>
              <div style={{ display:"flex", justifyContent:"space-between", fontSize:11, color:T.muted, marginTop:8 }}>
                <span>{t.events_delivered || 0} delivered</span>
                <span>{t.events_failed || 0} failed</span>
                <span>{t.last_export ? new Date(t.last_export).toLocaleTimeString() : "Never"}</span>
              </div>
            </Card>
          );
        })}
        {!loading && targets.length === 0 && (
          <div style={{ gridColumn:"1/-1" }}>
            <EmptyState icon="⊞" title="No SIEM targets"
              subtitle="Add a SIEM target to start forwarding AI agent events"
              action={user?.role==="admin" && <Button onClick={() => setShowAdd(true)}>Add target</Button>} />
          </div>
        )}
      </div>

      {/* Add target modal */}
      <Modal open={showAdd} onClose={() => setShowAdd(false)} title="Add SIEM target">
        <div style={{ display:"flex", flexDirection:"column", gap:14 }}>
          <div>
            <label style={{ fontSize:12, fontWeight:600, color:T.slate, display:"block", marginBottom:6 }}>Name</label>
            <Input value={newTarget.name} onChange={v => setNewTarget(t => ({ ...t, name:v }))}
              placeholder="Splunk Production" />
          </div>
          <div>
            <label style={{ fontSize:12, fontWeight:600, color:T.slate, display:"block", marginBottom:6 }}>SIEM type</label>
            <Select value={newTarget.siem_type}
              onChange={v => setNewTarget(t => ({ ...t, siem_type:v }))}
              options={siemTypes.map(s => ({ value:s, label:s.charAt(0).toUpperCase()+s.slice(1) }))} />
          </div>
          <div>
            <label style={{ fontSize:12, fontWeight:600, color:T.slate, display:"block", marginBottom:6 }}>Delivery method</label>
            <Select value={newTarget.delivery_method}
              onChange={v => setNewTarget(t => ({ ...t, delivery_method:v }))}
              options={[
                {value:"rest_push",    label:"REST push (HEC / DCR)"},
                {value:"syslog_tcp",   label:"Syslog TCP"},
                {value:"syslog_udp",   label:"Syslog UDP"},
                {value:"kafka",        label:"Kafka topic"},
                {value:"webhook",      label:"Webhook"},
              ]} />
          </div>
          <div style={{ display:"flex", gap:8, justifyContent:"flex-end", marginTop:4 }}>
            <Button variant="secondary" onClick={() => setShowAdd(false)}>Cancel</Button>
            <Button onClick={addTarget}>Add target</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// WEEK 4 — Settings
// ═══════════════════════════════════════════════════════════════════════════════
function SettingsPage() {
  const { token, user } = useAuth();
  const toast = useToast();
  const [users, setUsers]     = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [newUser, setNewUser] = useState({ username:"", password:"", role:"read_only", tenant_id:"ten_demo" });

  const loadUsers = () => {
    apiFetch("/api/v1/users", {}, token)
      .then(d => { setUsers(d.users || []); setLoading(false); })
      .catch(() => setLoading(false));
  };

  useEffect(() => { loadUsers(); }, []);

  const createUser = async () => {
    if (!newUser.username || !newUser.password) { toast("Fill all fields", "error"); return; }
    try {
      await apiFetch("/api/v1/users", { method:"POST", body:JSON.stringify(newUser) }, token);
      toast("User created", "success");
      setShowAdd(false);
      setNewUser({ username:"", password:"", role:"read_only", tenant_id:"ten_demo" });
      loadUsers();
    } catch (e) { toast(e.detail || "Failed", "error"); }
  };

  const deleteUser = async (username) => {
    if (username === user?.username) { toast("Cannot delete your own account", "error"); return; }
    try {
      await apiFetch(`/api/v1/users/${username}`, { method:"DELETE" }, token);
      toast("User removed", "success");
      loadUsers();
    } catch (e) { toast(e.detail || "Failed", "error"); }
  };

  return (
    <div style={{ padding:"24px", display:"flex", flexDirection:"column", gap:16 }}>
      <div>
        <h1 style={{ fontSize:22, fontWeight:700, color:T.navy, margin:0 }}>Settings</h1>
        <p style={{ fontSize:13, color:T.muted, margin:"4px 0 0" }}>
          Platform administration and user management
        </p>
      </div>

      {/* Current user info */}
      <Card>
        <div style={{ fontWeight:600, fontSize:14, color:T.navy, marginBottom:14 }}>Your account</div>
        <div style={{ display:"flex", alignItems:"center", gap:16 }}>
          <div style={{
            width:48, height:48, borderRadius:"50%", background:T.teal,
            display:"flex", alignItems:"center", justifyContent:"center",
            fontSize:18, fontWeight:700, color:"#fff"
          }}>
            {(user?.username || "?")[0].toUpperCase()}
          </div>
          <div>
            <div style={{ fontWeight:600, fontSize:15, color:T.navy }}>{user?.username}</div>
            <div style={{ fontSize:12, color:T.muted, marginTop:2 }}>
              {user?.role === "admin" ? "Administrator" : "Read-only analyst"} · {user?.tenant_id}
            </div>
          </div>
          <Badge color={user?.role==="admin"?"teal":"gray"}>{user?.role}</Badge>
        </div>
      </Card>

      {/* User management */}
      <Card>
        <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:14 }}>
          <span style={{ fontWeight:600, fontSize:14, color:T.navy }}>
            Team members ({users.length})
          </span>
          {user?.role === "admin" && (
            <Button size="sm" onClick={() => setShowAdd(true)}>+ Add user</Button>
          )}
        </div>

        {loading ? (
          <div style={{ display:"flex", justifyContent:"center", padding:30 }}><Spinner /></div>
        ) : (
          <div style={{ display:"flex", flexDirection:"column", gap:6 }}>
            {users.map(u => (
              <div key={u.user_id} style={{
                display:"flex", alignItems:"center", justifyContent:"space-between",
                padding:"10px 12px", borderRadius:8, background:T.offwhite
              }}>
                <div style={{ display:"flex", alignItems:"center", gap:10 }}>
                  <div style={{
                    width:30, height:30, borderRadius:"50%",
                    background: u.role==="admin" ? T.teal : T.border,
                    display:"flex", alignItems:"center", justifyContent:"center",
                    fontSize:11, fontWeight:700, color: u.role==="admin" ? "#fff" : T.muted
                  }}>
                    {u.username[0].toUpperCase()}
                  </div>
                  <div>
                    <div style={{ fontSize:13, fontWeight:500, color:T.slate }}>{u.username}</div>
                    <div style={{ fontSize:11, color:T.muted }}>{u.user_id}</div>
                  </div>
                </div>
                <div style={{ display:"flex", alignItems:"center", gap:10 }}>
                  <Badge color={u.role==="admin"?"teal":"gray"}>{u.role}</Badge>
                  {user?.role==="admin" && u.username!==user?.username && (
                    <Button size="sm" variant="danger" onClick={() => deleteUser(u.username)}>
                      Remove
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Add user modal */}
      <Modal open={showAdd} onClose={() => setShowAdd(false)} title="Add team member">
        <div style={{ display:"flex", flexDirection:"column", gap:14 }}>
          {[
            { label:"Username", key:"username", placeholder:"analyst.smith", type:"text" },
            { label:"Password", key:"password", placeholder:"Secure@123", type:"password" },
          ].map(f => (
            <div key={f.key}>
              <label style={{ fontSize:12, fontWeight:600, color:T.slate, display:"block", marginBottom:6 }}>
                {f.label}
              </label>
              <Input value={newUser[f.key]} type={f.type}
                onChange={v => setNewUser(u => ({ ...u, [f.key]:v }))}
                placeholder={f.placeholder} />
            </div>
          ))}
          <div>
            <label style={{ fontSize:12, fontWeight:600, color:T.slate, display:"block", marginBottom:6 }}>Role</label>
            <Select value={newUser.role}
              onChange={v => setNewUser(u => ({ ...u, role:v }))}
              options={[
                { value:"read_only", label:"Analyst (read-only)" },
                { value:"admin",     label:"Administrator" },
              ]} />
          </div>
          <div style={{ display:"flex", gap:8, justifyContent:"flex-end", marginTop:4 }}>
            <Button variant="secondary" onClick={() => setShowAdd(false)}>Cancel</Button>
            <Button onClick={createUser}>Create user</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// ROOT APP — routing + WebSocket + global state
// ═══════════════════════════════════════════════════════════════════════════════
function App() {
  const { isAuthenticated, isLoading, token } = useAuth();
  const [page, setPage]             = useState("dashboard");
  const [selectedAgent, setSelectedAgent] = useState(null);
  const [inventoryFilters, setInventoryFilters] = useState({});
  const [liveEvents, setLiveEvents] = useState([]);
  const [liveCount, setLiveCount]   = useState(0);
  const [shadowCount, setShadowCount] = useState(0);
  const [wsConnected, setWsConnected] = useState(false);
  const wsRef = useRef(null);
  const reconnectRef = useRef(null);

  // Fetch live agent counts
  const refreshCounts = useCallback(async () => {
    if (!token) return;
    try {
      const s = await apiFetch("/api/v1/agents/stats", {}, token);
      setLiveCount(s.total || 0);
      setShadowCount(s.shadow || 0);
    } catch (_) {}
  }, [token]);

  useEffect(() => { if (isAuthenticated) refreshCounts(); }, [isAuthenticated]);

  // WebSocket connection
  useEffect(() => {
    if (!token) return;

    const connect = () => {
      try {
        const ws = new WebSocket(`${WS_BASE}/ws/events?token=${token}`);
        wsRef.current = ws;

        ws.onopen  = () => setWsConnected(true);
        ws.onclose = () => {
          setWsConnected(false);
          reconnectRef.current = setTimeout(connect, 4000);
        };
        ws.onerror = () => ws.close();
        ws.onmessage = (e) => {
          try {
            const event = JSON.parse(e.data);
            if (event.type === "connected") return;
            setLiveEvents(prev => [event, ...prev.slice(0, 49)]);
            // Refresh counts when discovery finds new agents
            if (event.event_type?.includes("agent") || event.event_type?.includes("job")) {
              refreshCounts();
            }
          } catch (_) {}
        };
      } catch (_) {}
    };

    connect();
    return () => {
      clearTimeout(reconnectRef.current);
      wsRef.current?.close();
    };
  }, [token, refreshCounts]);

  if (isLoading) {
    return (
      <div style={{ display:"flex", alignItems:"center", justifyContent:"center",
        height:"100vh", background:T.navy }}>
        <Spinner size={40} />
      </div>
    );
  }

  if (!isAuthenticated) return <LoginPage />;

  const navigateTo = (p, filters) => {
    setPage(p);
    if (filters) setInventoryFilters(filters);
    if (p !== "inventory") setSelectedAgent(null);
  };

  const selectAgent = (id) => {
    setSelectedAgent(id);
    setPage("agent_detail");
  };

  return (
    <div style={{ display:"flex", height:"100vh", background:T.surface, overflow:"hidden" }}>
      <style>{`
        @keyframes spin  { to { transform: rotate(360deg); } }
        @keyframes pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.6;transform:scale(1.3)} }
        @keyframes slideIn { from{transform:translateX(20px);opacity:0} to{transform:none;opacity:1} }
        * { box-sizing: border-box; }
        body { margin:0; font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; }
        ::-webkit-scrollbar { width:5px; height:5px; }
        ::-webkit-scrollbar-track { background:transparent; }
        ::-webkit-scrollbar-thumb { background:${T.border}; border-radius:10px; }
      `}</style>

      <Sidebar page={page} setPage={navigateTo}
        liveCount={liveCount} shadowCount={shadowCount} wsConnected={wsConnected} />

      <main style={{ flex:1, overflow:"auto" }}>
        {page === "dashboard"   && <DashboardPage onNavigate={navigateTo} liveEvents={liveEvents} />}
        {page === "inventory"   && <InventoryPage onSelectAgent={selectAgent} initialFilters={inventoryFilters} />}
        {page === "agent_detail" && <AgentDetailPage agentId={selectedAgent} onBack={() => navigateTo("inventory")} />}
        {page === "connectors"  && <ConnectorsPage />}
        {page === "siem"        && <SIEMPage />}
        {page === "settings"    && <SettingsPage />}
      </main>
    </div>
  );
}

// ── Entry point ────────────────────────────────────────────────────────────────
export default function AgentAtlasApp() {
  return (
    <ToastProvider>
      <AuthProvider>
        <App />
      </AuthProvider>
    </ToastProvider>
  );
}
