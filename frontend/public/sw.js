/* Service worker of the driver app (scope /fahrer): the app and the day plan work offline.
   - app files (/assets/…, start page): cache first, updated in the background
   - photos (/api/files/…): cache first
   - day plan and identity (/api/driver/day, /api/driver/me): network first, cached copy offline
   POST requests (events, photos, reports) are never cached: the app keeps them in IndexedDB. */
const CACHE = "kp-fahrer-v1";
const SHELL = ["/fahrer", "/fahrer.webmanifest", "/icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("kp-fahrer-") && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

async function cacheFirst(request) {
  const cache = await caches.open(CACHE);
  const hit = await cache.match(request);
  const fetching = fetch(request)
    .then((res) => {
      if (res.ok) cache.put(request, res.clone());
      return res;
    })
    .catch(() => undefined);
  return hit || (await fetching) || new Response("", { status: 504 });
}

async function networkFirst(request, fallbackUrl) {
  const cache = await caches.open(CACHE);
  try {
    const res = await fetch(request);
    if (res.ok) cache.put(fallbackUrl || request, res.clone());
    return res;
  } catch {
    const hit = await cache.match(fallbackUrl || request);
    return hit || new Response(JSON.stringify({ error: { code: "errors.offline", message: "offline" } }), { status: 503, headers: { "Content-Type": "application/json" } });
  }
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (req.mode === "navigate" && url.pathname.startsWith("/fahrer")) {
    event.respondWith(networkFirst(req, "/fahrer"));
  } else if (url.pathname.startsWith("/assets/") || url.pathname === "/icon.svg" || url.pathname === "/fahrer.webmanifest") {
    event.respondWith(cacheFirst(req));
  } else if (url.pathname.startsWith("/api/files/")) {
    event.respondWith(cacheFirst(req));
  } else if (url.pathname === "/api/driver/day" || url.pathname === "/api/driver/me") {
    event.respondWith(networkFirst(req));
  }
});
