/// <reference no-default-lib="true"/>
/// <reference lib="esnext" />
/// <reference lib="webworker" />

import { clientsClaim } from "workbox-core";
import { precacheAndRoute } from "workbox-precaching";

declare const self: ServiceWorkerGlobalScope;

// vite-plugin-pwa injects the precache manifest here at build time.
precacheAndRoute(self.__WB_MANIFEST);
clientsClaim();

// ── Push event ────────────────────────────────────────────────────────────────

self.addEventListener("push", (event) => {
  if (!event.data) return;

  let data: {
    title?: string;
    body?: string;
    icon?: string;
    badge?: string;
    tag?: string;
    data?: { url?: string };
  };

  try {
    data = event.data.json() as typeof data;
  } catch {
    data = { body: event.data.text() };
  }

  event.waitUntil(
    self.registration.showNotification(data.title ?? "raid_guard alert", {
      body: data.body ?? "",
      icon: data.icon ?? "/icons/icon-192.png",
      badge: data.badge ?? "/icons/icon-192.png",
      tag: data.tag,
      data: data.data,
    })
  );
});

// ── Notification click ────────────────────────────────────────────────────────

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data as { url?: string } | undefined)?.url;
  if (url) {
    event.waitUntil(
      self.clients
        .matchAll({ type: "window", includeUncontrolled: true })
        .then((clientList) => {
          for (const client of clientList) {
            if ("focus" in client) {
              void client.focus();
              if ("navigate" in client) {
                void (client as WindowClient).navigate(url);
              }
              return;
            }
          }
          return self.clients.openWindow(url);
        })
    );
  }
});
