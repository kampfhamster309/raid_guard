import { useEffect, useState } from "react";
import { clearToken, fetchAlert, fetchCurrentUser, getToken } from "./api";
import { LoginPage } from "./components/LoginPage";
import { Header } from "./components/Header";
import { FilterBar } from "./components/FilterBar";
import { AlertTable } from "./components/AlertTable";
import { AlertDrawer } from "./components/AlertDrawer";
import { DashboardPage } from "./components/DashboardPage";
import { ConfigPage } from "./components/ConfigPage";
import { IncidentsPage } from "./components/IncidentsPage";
import { DigestsPage } from "./components/DigestsPage";
import { BlocklistPage } from "./components/BlocklistPage";
import { StatusPage } from "./components/StatusPage";
import { useAlerts } from "./hooks/useAlerts";
import type { Alert, Severity, User } from "./types";

type SeverityFilter = Severity | "all";
type Page = "alerts" | "dashboard" | "status" | "incidents" | "digests" | "blocklist" | "config";

const TABS: { id: Page; label: string }[] = [
  { id: "alerts", label: "Alerts" },
  { id: "dashboard", label: "Dashboard" },
  { id: "status", label: "Status" },
  { id: "incidents", label: "Incidents" },
  { id: "digests", label: "Digests" },
  { id: "blocklist", label: "Blocklist" },
  { id: "config", label: "Config" },
];

function NavTabs({ page, onChange }: { page: Page; onChange: (p: Page) => void }) {
  return (
    <nav className="flex border-b border-slate-700 bg-slate-800 px-4">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          aria-current={page === tab.id ? "page" : undefined}
          className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
            page === tab.id
              ? "border-indigo-500 text-white"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          {tab.label}
        </button>
      ))}
    </nav>
  );
}

function AlertsPage({
  currentUser,
  onLogout,
}: {
  currentUser: User;
  onLogout: () => void;
}) {
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>("all");
  const [searchText, setSearchText] = useState("");
  const [selectedAlert, setSelectedAlert] = useState<Alert | null>(null);
  const [page, setPage] = useState<Page>("alerts");

  const { filteredAlerts, loading, error, wsStatus, refresh } = useAlerts({
    severityFilter,
    searchText,
  });

  // Open the alert drawer when a deep link like ?alert=<id> is present.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const alertId = params.get("alert");
    if (!alertId) return;
    fetchAlert(alertId)
      .then(setSelectedAlert)
      .catch(() => {});
  }, []);

  return (
    <div className="h-screen flex flex-col bg-slate-900 text-slate-100">
      <Header
        wsStatus={wsStatus}
        onRefresh={refresh}
        onLogout={onLogout}
        currentUser={currentUser}
      />
      <NavTabs page={page} onChange={setPage} />

      {page === "alerts" ? (
        <>
          <FilterBar
            severityFilter={severityFilter}
            onSeverityChange={setSeverityFilter}
            searchText={searchText}
            onSearchChange={setSearchText}
          />

          {loading && (
            <div className="flex-1 flex items-center justify-center text-slate-400 text-sm">
              Loading alerts…
            </div>
          )}
          {error && !loading && (
            <div className="flex-1 flex items-center justify-center text-red-400 text-sm">
              {error}
            </div>
          )}
          {!loading && !error && (
            <AlertTable alerts={filteredAlerts} onSelect={setSelectedAlert} />
          )}

          <AlertDrawer
            alert={selectedAlert}
            onClose={() => setSelectedAlert(null)}
          />
        </>
      ) : page === "dashboard" ? (
        <DashboardPage />
      ) : page === "status" ? (
        <StatusPage />
      ) : page === "incidents" ? (
        <IncidentsPage />
      ) : page === "digests" ? (
        <DigestsPage />
      ) : page === "blocklist" ? (
        <BlocklistPage currentUser={currentUser} />
      ) : (
        <ConfigPage currentUser={currentUser} />
      )}
    </div>
  );
}

export default function App() {
  const [authed, setAuthed] = useState(() => getToken() !== null);
  const [currentUser, setCurrentUser] = useState<User | null>(null);

  useEffect(() => {
    if (!authed) return;
    fetchCurrentUser()
      .then(setCurrentUser)
      .catch(() => {
        // Token expired or user deleted — force re-login.
        clearToken();
        setAuthed(false);
      });
  }, [authed]);

  const handleLogout = () => {
    clearToken();
    setCurrentUser(null);
    setAuthed(false);
  };

  if (!authed) {
    return <LoginPage onLogin={() => setAuthed(true)} />;
  }

  if (!currentUser) {
    return (
      <div className="h-screen flex items-center justify-center bg-slate-900 text-slate-400 text-sm">
        Loading…
      </div>
    );
  }

  return <AlertsPage currentUser={currentUser} onLogout={handleLogout} />;
}
