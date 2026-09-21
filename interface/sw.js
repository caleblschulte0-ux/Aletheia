/* Opens instantly, and says something honest when the Core is unreachable.
 *
 * Deliberately small: the SHELL is cached so tapping the home-screen icon
 * paints immediately instead of showing a white page while the tailnet
 * wakes up. API responses are NEVER cached — a phone showing yesterday's
 * approvals as though they were pending is worse than a phone showing
 * nothing, and this whole system is built on not doing that.
 */
const SHELL = "thea-shell-v5";   // bumped: five surfaces became one page
const FILES = [
  "/interface/thea.html",      // the page, and the whole product
  "/interface/thea.js",
  "/interface/thea-app.js",
  "/interface/qr.js",
  "/interface/icon.svg",
  "/interface/mark.svg",
  "/interface/manifest.webmanifest",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(FILES)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api/")) return;      // never cached, never stale
  if (e.request.method !== "GET") return;
  // Network first so a deployed change is picked up, cache as the fallback
  // that makes the icon open instantly on a cold tailnet.
  //
  // The fallback to the app shell is for NAVIGATIONS ONLY. It used to answer
  // any failed GET with the page's HTML, which meant the page's own
  // "can I reach her machine at all?" probe got a cheerful 200 full of HTML
  // from yesterday and concluded the tailnet was fine. A diagnosis that
  // cannot fail is not a diagnosis.
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(SHELL).then((c) => c.put(e.request, copy)).catch(() => {});
        return res;
      })
      .catch(() => caches.match(e.request).then((hit) => {
        if (hit) return hit;
        if (e.request.mode === "navigate") return caches.match("/interface/thea.html");
        return Promise.reject(new Error("offline"));
      }))
  );
});
