import { useEffect, useState } from "react";
import { NavLink, Outlet, useMatch, useNavigate } from "react-router-dom";
import { Activity, FolderTree, GraduationCap, LayoutDashboard, MessageSquare, Network, Plug, Plus, Settings, ShieldAlert, Sparkles, Ticket } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api } from "../lib/api";
import { lastAnalysisId, rememberAnalysis, useAsync } from "../lib/hooks";
import { cx } from "./ui";

interface NavItem {
  label: string;
  icon: LucideIcon;
  path: string;
  scoped: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { label: "Overview", icon: LayoutDashboard, path: "", scoped: true },
  { label: "Repository Explorer", icon: FolderTree, path: "explorer", scoped: true },
  { label: "Code Intelligence", icon: Sparkles, path: "intelligence", scoped: true },
  { label: "Dependency Graph", icon: Network, path: "dependencies", scoped: true },
  { label: "Risk Analysis", icon: ShieldAlert, path: "risks", scoped: true },
  { label: "AI Assistant", icon: MessageSquare, path: "assistant", scoped: true },
  { label: "CodeQuest", icon: GraduationCap, path: "learn", scoped: true },
  { label: "MCP Integration", icon: Plug, path: "/mcp", scoped: false },
  { label: "Jira", icon: Ticket, path: "/jira", scoped: false },
  { label: "Settings", icon: Settings, path: "/settings", scoped: false },
];

function useApiHealth(): "checking" | "online" | "offline" {
  const [state, setState] = useState<"checking" | "online" | "offline">("checking");
  useEffect(() => {
    let active = true;
    api.config()
      .then(() => active && setState("online"))
      .catch(() => active && setState("offline"));
    return () => {
      active = false;
    };
  }, []);
  return state;
}

export function Layout() {
  const navigate = useNavigate();
  const nestedMatch = useMatch("/analyses/:analysisId/*");
  const projectMatch = useMatch("/analyses/:analysisId");
  const analysisId = (nestedMatch ?? projectMatch)?.params.analysisId ?? lastAnalysisId();
  const projects = useAsync(() => api.listAnalyses(), [analysisId]);
  const health = useApiHealth();
  const activeProject = projects.data?.find((item) => item.analysis_id === analysisId);

  useEffect(() => {
    if (analysisId) rememberAnalysis(analysisId);
  }, [analysisId]);

  const linkFor = (item: NavItem) => {
    if (!item.scoped) return item.path;
    if (!analysisId) return "/";
    return item.path ? `/analyses/${analysisId}/${item.path}` : `/analyses/${analysisId}`;
  };

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-navy-700 bg-navy-950 px-3 py-5 lg:flex">
        <div className="mb-7 flex items-center gap-2.5 px-2">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-sm font-bold text-navy-950">R</span>
          <span className="text-sm font-semibold text-ink-50">RepoMind</span>
        </div>
        <nav className="flex flex-1 flex-col gap-0.5" aria-label="Main">
          {NAV_ITEMS.map((item) => {
            const disabled = item.scoped && !analysisId;
            return (
              <NavLink
                key={item.label}
                to={linkFor(item)}
                end={item.path === ""}
                aria-disabled={disabled}
                className={({ isActive }) =>
                  cx(
                    "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition",
                    isActive ? "bg-navy-800 text-ink-50" : "text-ink-400 hover:bg-navy-850 hover:text-ink-100",
                    disabled && "pointer-events-none opacity-35",
                  )
                }
              >
                <item.icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                {item.label}
              </NavLink>
            );
          })}
        </nav>
        <div className="flex items-center gap-2 px-3 text-xs text-ink-500">
          <Activity className="h-3.5 w-3.5" aria-hidden="true" />
          Server
          <span className={cx("ml-auto font-medium", health === "online" ? "text-mint" : health === "offline" ? "text-rose-300" : "text-ink-500")}>
            {health === "online" ? "Online" : health === "offline" ? "Offline" : "Checking"}
          </span>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-navy-700 bg-navy-950/80 px-5 py-3 backdrop-blur">
          <select
            aria-label="Project"
            value={activeProject?.analysis_id ?? ""}
            onChange={(event) => event.target.value && navigate(`/analyses/${event.target.value}`)}
            className="min-w-0 max-w-xs flex-1 rounded-lg border border-navy-600 bg-navy-900 px-3 py-2 text-sm text-ink-100 focus:outline-none focus:ring-2 focus:ring-accent/20 sm:flex-none"
          >
            <option value="">{projects.data?.length ? "Select a project" : "No projects yet"}</option>
            {projects.data?.map((item) => (
              <option key={item.analysis_id} value={item.analysis_id}>{item.repository}</option>
            ))}
          </select>
          <button type="button" onClick={() => navigate("/")} className="inline-flex items-center gap-1.5 rounded-lg border border-navy-600 px-3 py-2 text-sm text-ink-200 hover:bg-navy-800">
            <Plus className="h-4 w-4" aria-hidden="true" />
            New project
          </button>
        </header>
        <nav className="scrollbar-thin flex gap-1 overflow-x-auto border-b border-navy-700 px-4 py-2 lg:hidden" aria-label="Mobile">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.label} to={linkFor(item)} end={item.path === ""} className={({ isActive }) => cx("shrink-0 rounded-md px-3 py-1.5 text-xs", isActive ? "bg-navy-800 text-ink-50" : "text-ink-400")}>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <main className="mx-auto w-full max-w-[1320px] flex-1 px-5 py-7 sm:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
