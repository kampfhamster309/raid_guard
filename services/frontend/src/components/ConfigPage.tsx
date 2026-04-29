import { useEffect, useState } from "react";
import {
  changePassword,
  createUser,
  deletePushSubscription,
  deleteUser,
  fetchHaSettings,
  fetchLlmSettings,
  fetchPiholeSettings,
  fetchUsers,
  fetchVapidPublicKey,
  savePushSubscription,
  testHaSend,
  testLlm,
  updateHaSettings,
  updateLlmSettings,
  updatePiholeSettings,
} from "../api";
import { useRules } from "../hooks/useRules";
import type { HaSettings, LlmSettings, PiholeSettings, User } from "../types";
import { TuningSuggestionsSection } from "./TuningSuggestionsSection";

type TestStatus = "idle" | "sending" | "success" | "error";

function _urlBase64ToUint8Array(base64String: string): ArrayBuffer {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  const buffer = new ArrayBuffer(rawData.length);
  const view = new Uint8Array(buffer);
  for (let i = 0; i < rawData.length; i++) {
    view[i] = rawData.charCodeAt(i);
  }
  return buffer;
}

// ── User Management section (admin only) ──────────────────────────────────────

function UserManagementSection({ currentUser }: { currentUser: User }) {
  const [users, setUsers] = useState<User[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState<"admin" | "viewer">("viewer");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [deletingUser, setDeletingUser] = useState<string | null>(null);

  useEffect(() => {
    fetchUsers()
      .then(setUsers)
      .catch((e) => setLoadError(e instanceof Error ? e.message : "Failed to load users"));
  }, []);

  const handleCreate = async () => {
    const username = newUsername.trim();
    if (!username || newPassword.length < 8) return;
    setCreating(true);
    setCreateError(null);
    try {
      const user = await createUser({ username, password: newPassword, role: newRole });
      setUsers((prev) => [...prev, user]);
      setNewUsername("");
      setNewPassword("");
      setNewRole("viewer");
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : "Create failed");
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (username: string) => {
    setDeletingUser(username);
    try {
      await deleteUser(username);
      setUsers((prev) => prev.filter((u) => u.username !== username));
    } catch {
      // leave list unchanged
    } finally {
      setDeletingUser(null);
    }
  };

  return (
    <section>
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-slate-100">User Management</h2>
        <p className="text-sm text-slate-400 mt-0.5">
          Manage dashboard users. Admins have full access; viewers are read-only.
        </p>
      </div>

      <div className="rounded-lg border border-slate-700 p-4 space-y-4">
        {loadError && (
          <p className="text-red-400 text-sm">{loadError}</p>
        )}

        {/* User list */}
        {users.length > 0 && (
          <div className="divide-y divide-slate-700/50">
            {users.map((u) => (
              <div key={u.username} className="flex items-center justify-between py-2.5">
                <div className="flex items-center gap-2">
                  <span className="text-sm text-slate-200">{u.username}</span>
                  <span
                    className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                      u.role === "admin"
                        ? "bg-indigo-700 text-indigo-100"
                        : "bg-slate-700 text-slate-300"
                    }`}
                  >
                    {u.role}
                  </span>
                  {u.username === currentUser.username && (
                    <span className="text-[10px] text-slate-500">(you)</span>
                  )}
                </div>
                {u.username !== currentUser.username && (
                  <button
                    onClick={() => void handleDelete(u.username)}
                    disabled={deletingUser === u.username}
                    className="px-2 py-1 text-xs rounded bg-slate-700 hover:bg-red-700 disabled:opacity-40 transition-colors text-slate-300"
                  >
                    {deletingUser === u.username ? "Deleting…" : "Delete"}
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Create user form */}
        <div className="pt-2 border-t border-slate-700">
          <p className="text-xs text-slate-400 mb-3">Add a new user:</p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <input
              type="text"
              value={newUsername}
              onChange={(e) => setNewUsername(e.target.value)}
              placeholder="Username"
              aria-label="New username"
              className="bg-slate-800 border border-slate-600 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="Password (min 8 chars)"
              aria-label="New user password"
              className="bg-slate-800 border border-slate-600 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <div className="flex gap-2">
              <select
                value={newRole}
                onChange={(e) => setNewRole(e.target.value as "admin" | "viewer")}
                aria-label="New user role"
                className="flex-1 bg-slate-800 border border-slate-600 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                <option value="viewer">viewer</option>
                <option value="admin">admin</option>
              </select>
              <button
                onClick={() => void handleCreate()}
                disabled={creating || !newUsername.trim() || newPassword.length < 8}
                className="px-3 py-2 text-xs font-medium rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-white whitespace-nowrap"
              >
                {creating ? "Creating…" : "Add"}
              </button>
            </div>
          </div>
          {createError && (
            <p className="text-xs text-red-400 mt-2">{createError}</p>
          )}
        </div>
      </div>
    </section>
  );
}

// ── Change Password section (all users) ───────────────────────────────────────

function ChangePasswordSection({ currentUser }: { currentUser: User }) {
  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [status, setStatus] = useState<"idle" | "saving" | "success" | "error">("idle");
  const [message, setMessage] = useState<string | null>(null);

  const handleSave = async () => {
    setMessage(null);
    if (newPw !== confirmPw) {
      setStatus("error");
      setMessage("New passwords do not match.");
      return;
    }
    if (newPw.length < 8) {
      setStatus("error");
      setMessage("Password must be at least 8 characters.");
      return;
    }
    setStatus("saving");
    try {
      await changePassword(currentUser.username, currentPw, newPw);
      setStatus("success");
      setMessage("Password changed successfully.");
      setCurrentPw("");
      setNewPw("");
      setConfirmPw("");
    } catch (e) {
      setStatus("error");
      setMessage(e instanceof Error ? e.message : "Change failed");
    }
  };

  return (
    <section>
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-slate-100">Change Password</h2>
        <p className="text-sm text-slate-400 mt-0.5">
          Update your own password.
        </p>
      </div>

      <div className="rounded-lg border border-slate-700 p-4 space-y-3">
        <div>
          <label className="block text-xs text-slate-400 mb-1">Current password</label>
          <input
            type="password"
            value={currentPw}
            onChange={(e) => setCurrentPw(e.target.value)}
            autoComplete="current-password"
            className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1">New password</label>
          <input
            type="password"
            value={newPw}
            onChange={(e) => setNewPw(e.target.value)}
            autoComplete="new-password"
            className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1">Confirm new password</label>
          <input
            type="password"
            value={confirmPw}
            onChange={(e) => setConfirmPw(e.target.value)}
            autoComplete="new-password"
            className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>
        <div className="pt-1">
          <button
            onClick={() => void handleSave()}
            disabled={status === "saving" || !currentPw || !newPw || !confirmPw}
            className="px-4 py-2 rounded text-sm font-medium bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-white"
          >
            {status === "saving" ? "Saving…" : "Change password"}
          </button>
        </div>
        {message && (
          <div
            className={`rounded px-3 py-2 text-xs ${
              status === "success"
                ? "bg-emerald-900/50 text-emerald-300 border border-emerald-700"
                : "bg-red-900/50 text-red-300 border border-red-700"
            }`}
          >
            {message}
          </div>
        )}
      </div>
    </section>
  );
}

// ── Main ConfigPage ───────────────────────────────────────────────────────────

export function ConfigPage({ currentUser }: { currentUser: User }) {
  const isAdmin = currentUser.role === "admin";

  const { categories, loading, error, reloadStatus, reloadMessage, toggleCategory, reload } =
    useRules();

  // ── LLM settings ──────────────────────────────────────────────────────────
  const [llmSettings, setLlmSettings] = useState<LlmSettings | null>(null);
  const [llmDraft, setLlmDraft] = useState<LlmSettings | null>(null);
  const [llmSaveStatus, setLlmSaveStatus] = useState<"idle" | "saving" | "success" | "error">("idle");
  const [llmSaveMessage, setLlmSaveMessage] = useState<string | null>(null);
  const [llmTestStatus, setLlmTestStatus] = useState<"idle" | "testing" | "success" | "error">("idle");
  const [llmTestContent, setLlmTestContent] = useState<string | null>(null);

  useEffect(() => {
    fetchLlmSettings()
      .then((s) => { setLlmSettings(s); setLlmDraft(s); })
      .catch(() => {});
  }, []);

  const saveLlm = async () => {
    if (!llmDraft) return;
    setLlmSaveStatus("saving");
    setLlmSaveMessage(null);
    try {
      const updated = await updateLlmSettings(llmDraft);
      setLlmSettings(updated);
      setLlmDraft(updated);
      setLlmSaveStatus("success");
      setLlmSaveMessage("Settings saved. Restart the backend container for the enricher to pick up the new config.");
    } catch (e) {
      setLlmSaveStatus("error");
      setLlmSaveMessage(e instanceof Error ? e.message : "Save failed");
    }
  };

  const runLlmTest = async () => {
    setLlmTestStatus("testing");
    setLlmTestContent(null);
    try {
      const { content } = await testLlm();
      setLlmTestStatus("success");
      try {
        setLlmTestContent(JSON.stringify(JSON.parse(content), null, 2));
      } catch {
        setLlmTestContent(content);
      }
    } catch (e) {
      setLlmTestStatus("error");
      setLlmTestContent(e instanceof Error ? e.message : "Test failed");
    }
  };

  // ── Pi-hole settings ───────────────────────────────────────────────────────
  const [piholeSettings, setPiholeSettings] = useState<PiholeSettings | null>(null);
  const [piholeDraft, setPiholeDraft] = useState<{ url: string; password: string } | null>(null);
  const [piholeSaveStatus, setPiholeSaveStatus] = useState<"idle" | "saving" | "success" | "error">("idle");
  const [piholeSaveMessage, setPiholeSaveMessage] = useState<string | null>(null);

  useEffect(() => {
    fetchPiholeSettings()
      .then((s) => {
        setPiholeSettings(s);
        setPiholeDraft({ url: s.url, password: "" });
      })
      .catch(() => {});
  }, []);

  const savePihole = async () => {
    if (!piholeDraft || !piholeSettings) return;
    setPiholeSaveStatus("saving");
    setPiholeSaveMessage(null);
    try {
      const updated = await updatePiholeSettings({
        url: piholeDraft.url,
        enabled: piholeSettings.enabled,
        password: piholeDraft.password,
      });
      setPiholeSettings(updated);
      setPiholeDraft((d) => d ? { ...d, password: "" } : d);
      setPiholeSaveStatus("success");
      setPiholeSaveMessage("Pi-hole settings saved.");
    } catch (e) {
      setPiholeSaveStatus("error");
      setPiholeSaveMessage(e instanceof Error ? e.message : "Save failed");
    }
  };

  const togglePihole = async () => {
    if (!piholeSettings || !piholeDraft) return;
    try {
      const updated = await updatePiholeSettings({
        url: piholeSettings.url,
        enabled: !piholeSettings.enabled,
        password: "",
      });
      setPiholeSettings(updated);
    } catch {
      // leave state unchanged
    }
  };

  // ── Home Assistant settings ────────────────────────────────────────────────
  const [haSettings, setHaSettings] = useState<HaSettings | null>(null);
  const [haLoading, setHaLoading] = useState(true);
  const [testStatus, setTestStatus] = useState<TestStatus>("idle");
  const [testMessage, setTestMessage] = useState<string | null>(null);

  useEffect(() => {
    fetchHaSettings()
      .then(setHaSettings)
      .catch(() => {})
      .finally(() => setHaLoading(false));
  }, []);

  // ── Web Push subscription ──────────────────────────────────────────────────
  const [pushSupported] = useState(
    () => "serviceWorker" in navigator && "PushManager" in window
  );
  const [pushPermission, setPushPermission] = useState<NotificationPermission | "unsupported">(
    () => (!("Notification" in window) ? "unsupported" : Notification.permission)
  );
  const [pushSubscribed, setPushSubscribed] = useState(false);
  const [pushStatus, setPushStatus] = useState<"idle" | "working" | "success" | "error">("idle");
  const [pushMessage, setPushMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!pushSupported) return;
    navigator.serviceWorker.ready
      .then((reg) => reg.pushManager.getSubscription())
      .then((sub) => setPushSubscribed(sub !== null))
      .catch(() => {});
  }, [pushSupported]);

  const subscribePush = async () => {
    setPushStatus("working");
    setPushMessage(null);
    try {
      const permission = await Notification.requestPermission();
      setPushPermission(permission);
      if (permission !== "granted") {
        setPushStatus("error");
        setPushMessage("Notification permission denied.");
        return;
      }
      const vapidKey = await fetchVapidPublicKey();
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: _urlBase64ToUint8Array(vapidKey),
      });
      await savePushSubscription(sub);
      setPushSubscribed(true);
      setPushStatus("success");
      setPushMessage("Push notifications enabled.");
    } catch (e) {
      setPushStatus("error");
      setPushMessage(e instanceof Error ? e.message : "Failed to subscribe.");
    }
  };

  const unsubscribePush = async () => {
    setPushStatus("working");
    setPushMessage(null);
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        await deletePushSubscription(sub.endpoint);
        await sub.unsubscribe();
      }
      setPushSubscribed(false);
      setPushStatus("success");
      setPushMessage("Push notifications disabled.");
    } catch (e) {
      setPushStatus("error");
      setPushMessage(e instanceof Error ? e.message : "Failed to unsubscribe.");
    }
  };

  const toggleHa = async () => {
    if (!haSettings) return;
    try {
      const updated = await updateHaSettings({ enabled: !haSettings.enabled });
      setHaSettings(updated);
    } catch {
      // leave state unchanged on error
    }
  };

  const toggleHaHealthAlerts = async () => {
    if (!haSettings) return;
    try {
      const updated = await updateHaSettings({ health_alerts_enabled: !haSettings.health_alerts_enabled });
      setHaSettings(updated);
    } catch {
      // leave state unchanged on error
    }
  };

  const sendTest = async () => {
    setTestStatus("sending");
    setTestMessage(null);
    try {
      await testHaSend();
      setTestStatus("success");
      setTestMessage("Test notification sent.");
    } catch (e) {
      setTestStatus("error");
      setTestMessage(e instanceof Error ? e.message : "Test failed");
    }
  };

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="max-w-3xl mx-auto space-y-6">

        {/* ── Rule Categories ────────────────────────────────────────────── */}
        <section>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-100">Rule Categories</h2>
              <p className="text-sm text-slate-400 mt-0.5">
                Toggle ET Open rule categories. Click <span className="font-medium text-slate-300">Reload Suricata</span> to apply changes to the running engine.
              </p>
            </div>
            {isAdmin && (
              <button
                onClick={reload}
                disabled={reloadStatus === "reloading"}
                className="px-4 py-2 rounded text-sm font-medium bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-white"
              >
                {reloadStatus === "reloading" ? "Reloading…" : "Reload Suricata"}
              </button>
            )}
          </div>

          {reloadMessage && (
            <div
              className={`mb-4 rounded px-4 py-3 text-sm ${
                reloadStatus === "success"
                  ? "bg-emerald-900/50 text-emerald-300 border border-emerald-700"
                  : "bg-red-900/50 text-red-300 border border-red-700"
              }`}
            >
              {reloadMessage}
            </div>
          )}

          {loading && (
            <p className="text-slate-400 text-sm">Loading categories…</p>
          )}
          {error && (
            <p className="text-red-400 text-sm">{error}</p>
          )}

          {!loading && !error && (
            <div className="rounded-lg border border-slate-700 divide-y divide-slate-700">
              {categories.map((cat) => (
                <div
                  key={cat.id}
                  className="flex items-center justify-between px-4 py-3 hover:bg-slate-800/50 transition-colors"
                >
                  <div className="min-w-0 pr-4">
                    <p className="text-sm font-medium text-slate-200">{cat.name}</p>
                    <p className="text-xs text-slate-400 mt-0.5 truncate">{cat.description}</p>
                  </div>
                  <button
                    role="switch"
                    aria-checked={cat.enabled}
                    onClick={isAdmin ? () => void toggleCategory(cat.id) : undefined}
                    disabled={!isAdmin}
                    className={`relative inline-flex h-5 w-9 flex-shrink-0 rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 focus:ring-offset-slate-900 disabled:opacity-50 disabled:cursor-not-allowed ${
                      cat.enabled ? "bg-indigo-600" : "bg-slate-600"
                    }`}
                  >
                    <span
                      className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform mt-0.5 ${
                        cat.enabled ? "translate-x-4" : "translate-x-0.5"
                      }`}
                    />
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* ── AI Enrichment ──────────────────────────────────────────────── */}
        <section>
          <div className="mb-4">
            <h2 className="text-lg font-semibold text-slate-100">AI Enrichment</h2>
            <p className="text-sm text-slate-400 mt-0.5">
              LM Studio connection settings for per-alert AI analysis. Save changes, then restart the backend container for the enricher to use the new config.
            </p>
          </div>

          <div className="rounded-lg border border-slate-700 p-4 space-y-4">
            {llmDraft === null ? (
              <p className="text-slate-400 text-sm">Loading…</p>
            ) : (
              <>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div className="sm:col-span-2">
                    <label className="block text-xs text-slate-400 mb-1">LM Studio base URL</label>
                    <input
                      type="text"
                      value={llmDraft.url}
                      onChange={(e) => setLlmDraft({ ...llmDraft, url: e.target.value })}
                      placeholder="http://192.168.1.x:1234/v1"
                      disabled={!isAdmin}
                      className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50"
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <label className="block text-xs text-slate-400 mb-1">Model name</label>
                    <input
                      type="text"
                      value={llmDraft.model}
                      onChange={(e) => setLlmDraft({ ...llmDraft, model: e.target.value })}
                      placeholder="gemma-4-27b"
                      disabled={!isAdmin}
                      className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">Request timeout (seconds)</label>
                    <input
                      type="number"
                      min={1}
                      max={600}
                      value={llmDraft.timeout}
                      onChange={(e) => setLlmDraft({ ...llmDraft, timeout: Number(e.target.value) })}
                      disabled={!isAdmin}
                      className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">Max response tokens</label>
                    <input
                      type="number"
                      min={64}
                      max={4096}
                      value={llmDraft.max_tokens}
                      onChange={(e) => setLlmDraft({ ...llmDraft, max_tokens: Number(e.target.value) })}
                      disabled={!isAdmin}
                      className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50"
                    />
                  </div>
                </div>

                <div className="flex items-center gap-3 pt-1">
                  {isAdmin && (
                    <button
                      onClick={() => void saveLlm()}
                      disabled={llmSaveStatus === "saving"}
                      className="px-4 py-2 rounded text-sm font-medium bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-white"
                    >
                      {llmSaveStatus === "saving" ? "Saving…" : "Save"}
                    </button>
                  )}
                  <button
                    onClick={() => void runLlmTest()}
                    disabled={llmTestStatus === "testing" || !llmSettings?.url || !llmSettings?.model}
                    className="px-4 py-2 rounded text-sm font-medium bg-slate-700 hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-slate-200"
                  >
                    {llmTestStatus === "testing" ? "Testing…" : "Send test prompt"}
                  </button>
                </div>

                {llmSaveMessage && (
                  <div
                    className={`rounded px-3 py-2 text-xs ${
                      llmSaveStatus === "success"
                        ? "bg-emerald-900/50 text-emerald-300 border border-emerald-700"
                        : "bg-red-900/50 text-red-300 border border-red-700"
                    }`}
                  >
                    {llmSaveMessage}
                  </div>
                )}

                {llmTestContent !== null && (
                  <div>
                    <p className="text-xs text-slate-400 mb-1">
                      {llmTestStatus === "success" ? "LLM response:" : "Error:"}
                    </p>
                    <pre
                      className={`rounded p-3 text-xs overflow-x-auto whitespace-pre-wrap break-all ${
                        llmTestStatus === "success"
                          ? "bg-slate-800 text-slate-300"
                          : "bg-red-900/30 text-red-300 border border-red-700"
                      }`}
                    >
                      {llmTestContent}
                    </pre>
                  </div>
                )}
              </>
            )}
          </div>
        </section>

        {/* ── Notifications ──────────────────────────────────────────────── */}
        <section>
          <div className="mb-4">
            <h2 className="text-lg font-semibold text-slate-100">Notifications</h2>
            <p className="text-sm text-slate-400 mt-0.5">
              Push alerts to external services. The severity threshold controls which alerts trigger a notification.
            </p>
          </div>

          <div className="rounded-lg border border-slate-700 divide-y divide-slate-700">
            {/* Home Assistant row */}
            <div className="px-4 py-4">
              <div className="flex items-center justify-between">
                <div className="min-w-0 pr-4">
                  <p className="text-sm font-medium text-slate-200">Home Assistant</p>
                  <p className="text-xs text-slate-400 mt-0.5">
                    {haLoading
                      ? "Loading…"
                      : haSettings?.configured
                      ? "Webhook configured — push alert to your HA automations."
                      : "HA_WEBHOOK_URL not set. Configure it in your .env to enable."}
                  </p>
                </div>
                <div className="flex items-center gap-3 flex-shrink-0">
                  {isAdmin && haSettings?.configured && (
                    <button
                      onClick={() => void sendTest()}
                      disabled={testStatus === "sending" || !haSettings?.configured}
                      className="px-3 py-1.5 rounded text-xs font-medium bg-slate-700 hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-slate-200"
                    >
                      {testStatus === "sending" ? "Sending…" : "Send test"}
                    </button>
                  )}
                  <button
                    role="switch"
                    aria-checked={haSettings?.enabled ?? false}
                    aria-label="Home Assistant notifications"
                    onClick={isAdmin ? () => void toggleHa() : undefined}
                    disabled={haLoading || !haSettings?.configured || !isAdmin}
                    className={`relative inline-flex h-5 w-9 flex-shrink-0 rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 focus:ring-offset-slate-900 disabled:opacity-40 disabled:cursor-not-allowed ${
                      haSettings?.enabled && haSettings?.configured
                        ? "bg-indigo-600"
                        : "bg-slate-600"
                    }`}
                  >
                    <span
                      className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform mt-0.5 ${
                        haSettings?.enabled && haSettings?.configured
                          ? "translate-x-4"
                          : "translate-x-0.5"
                      }`}
                    />
                  </button>
                </div>
              </div>

              {/* Health alerts sub-row */}
              {haSettings?.configured && (
                <div className="flex items-center justify-between mt-3 pt-3 border-t border-slate-700/50">
                  <div className="min-w-0 pr-4">
                    <p className="text-sm font-medium text-slate-200">Health Alerts</p>
                    <p className="text-xs text-slate-400 mt-0.5">
                      Notify when a pipeline component becomes unhealthy or recovers.
                    </p>
                  </div>
                  <button
                    role="switch"
                    aria-checked={haSettings?.health_alerts_enabled ?? true}
                    aria-label="Health alert notifications"
                    onClick={isAdmin ? () => void toggleHaHealthAlerts() : undefined}
                    disabled={haLoading || !haSettings?.configured || !isAdmin}
                    className={`relative inline-flex h-5 w-9 flex-shrink-0 rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 focus:ring-offset-slate-900 disabled:opacity-40 disabled:cursor-not-allowed ${
                      haSettings?.health_alerts_enabled && haSettings?.configured
                        ? "bg-indigo-600"
                        : "bg-slate-600"
                    }`}
                  >
                    <span
                      className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform mt-0.5 ${
                        haSettings?.health_alerts_enabled && haSettings?.configured
                          ? "translate-x-4"
                          : "translate-x-0.5"
                      }`}
                    />
                  </button>
                </div>
              )}

              {testMessage && (
                <div
                  className={`mt-3 rounded px-3 py-2 text-xs ${
                    testStatus === "success"
                      ? "bg-emerald-900/50 text-emerald-300 border border-emerald-700"
                      : "bg-red-900/50 text-red-300 border border-red-700"
                  }`}
                >
                  {testMessage}
                </div>
              )}
            </div>

            {/* Web Push row */}
            <div className="px-4 py-4">
              <div className="flex items-center justify-between">
                <div className="min-w-0 pr-4">
                  <p className="text-sm font-medium text-slate-200">Web Push</p>
                  <p className="text-xs text-slate-400 mt-0.5">
                    {!pushSupported
                      ? "Not supported in this browser."
                      : pushPermission === "denied"
                      ? "Permission denied — unblock notifications in browser settings."
                      : pushSubscribed
                      ? "Subscribed — alerts will be pushed to this browser."
                      : "Subscribe to receive alerts as push notifications in this browser."}
                  </p>
                </div>
                {pushSupported && pushPermission !== "denied" && (
                  <button
                    onClick={() => void (pushSubscribed ? unsubscribePush() : subscribePush())}
                    disabled={pushStatus === "working"}
                    aria-label={pushSubscribed ? "Unsubscribe from push notifications" : "Subscribe to push notifications"}
                    className={`px-3 py-1.5 rounded text-xs font-medium transition-colors flex-shrink-0 disabled:opacity-50 disabled:cursor-not-allowed ${
                      pushSubscribed
                        ? "bg-slate-700 hover:bg-slate-600 text-slate-200"
                        : "bg-indigo-600 hover:bg-indigo-500 text-white"
                    }`}
                  >
                    {pushStatus === "working"
                      ? "Working…"
                      : pushSubscribed
                      ? "Unsubscribe"
                      : "Subscribe"}
                  </button>
                )}
              </div>
              {pushMessage && (
                <div
                  className={`mt-3 rounded px-3 py-2 text-xs ${
                    pushStatus === "success"
                      ? "bg-emerald-900/50 text-emerald-300 border border-emerald-700"
                      : "bg-red-900/50 text-red-300 border border-red-700"
                  }`}
                >
                  {pushMessage}
                </div>
              )}
            </div>
          </div>
        </section>

        {/* ── Pi-hole Sinkhole ───────────────────────────────────────────── */}
        <section>
          <div className="mb-4">
            <h2 className="text-lg font-semibold text-slate-100">Pi-hole Sinkhole</h2>
            <p className="text-sm text-slate-400 mt-0.5">
              DNS sinkhole via Pi-hole v6. Set the base URL and admin password, then
              use the Sinkhole tab to manage blocked domains.
            </p>
          </div>

          <div className="rounded-lg border border-slate-700 p-4 space-y-4">
            {piholeDraft === null ? (
              <p className="text-slate-400 text-sm">Loading…</p>
            ) : (
              <>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div className="sm:col-span-2">
                    <label className="block text-xs text-slate-400 mb-1">Pi-hole base URL</label>
                    <input
                      type="text"
                      value={piholeDraft.url}
                      onChange={(e) => setPiholeDraft({ ...piholeDraft, url: e.target.value })}
                      placeholder="http://192.168.178.3"
                      disabled={!isAdmin}
                      className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50"
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <label className="block text-xs text-slate-400 mb-1">Admin password</label>
                    <input
                      type="password"
                      value={piholeDraft.password}
                      onChange={(e) => setPiholeDraft({ ...piholeDraft, password: e.target.value })}
                      placeholder={piholeSettings?.configured ? "leave blank to keep existing" : "enter password"}
                      disabled={!isAdmin}
                      className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50"
                    />
                  </div>
                </div>

                {isAdmin && (
                  <div className="flex items-center justify-between pt-1">
                    <div className="flex items-center gap-3">
                      <button
                        onClick={() => void savePihole()}
                        disabled={piholeSaveStatus === "saving"}
                        className="px-4 py-2 rounded text-sm font-medium bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-white"
                      >
                        {piholeSaveStatus === "saving" ? "Saving…" : "Save"}
                      </button>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-slate-400">
                        {piholeSettings?.enabled ? "Enabled" : "Disabled"}
                      </span>
                      <button
                        role="switch"
                        aria-checked={piholeSettings?.enabled ?? false}
                        aria-label="Pi-hole integration"
                        onClick={() => void togglePihole()}
                        disabled={!piholeSettings?.configured}
                        className={`relative inline-flex h-5 w-9 flex-shrink-0 rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 focus:ring-offset-slate-900 disabled:opacity-40 disabled:cursor-not-allowed ${
                          piholeSettings?.enabled && piholeSettings?.configured
                            ? "bg-indigo-600"
                            : "bg-slate-600"
                        }`}
                      >
                        <span
                          className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform mt-0.5 ${
                            piholeSettings?.enabled && piholeSettings?.configured
                              ? "translate-x-4"
                              : "translate-x-0.5"
                          }`}
                        />
                      </button>
                    </div>
                  </div>
                )}

                {piholeSaveMessage && (
                  <div
                    className={`rounded px-3 py-2 text-xs ${
                      piholeSaveStatus === "success"
                        ? "bg-emerald-900/50 text-emerald-300 border border-emerald-700"
                        : "bg-red-900/50 text-red-300 border border-red-700"
                    }`}
                  >
                    {piholeSaveMessage}
                  </div>
                )}
              </>
            )}
          </div>
        </section>

        {/* ── Tuning Suggestions ─────────────────────────────────────────── */}
        <TuningSuggestionsSection />

        {/* ── User Management (admin only) ───────────────────────────────── */}
        {isAdmin && <UserManagementSection currentUser={currentUser} />}

        {/* ── Change Password (all users) ────────────────────────────────── */}
        <ChangePasswordSection currentUser={currentUser} />

      </div>
    </div>
  );
}
