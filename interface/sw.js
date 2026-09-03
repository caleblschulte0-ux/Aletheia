/* Opens instantly, and says something honest when the Core is unreachable.
 *
 * Deliberately small: the SHELL is cached so tapping the home-screen icon
 * paints immediately instead of showing a white page while the tailnet
 * wakes up. API responses are NEVER cached — a phone showing yesterday's
 * approvals as though they were pending is worse than a phone showing
 * nothing, and this whole system is built on not doing that.
 */
const SHELL = "thea-shell-v2";
const FILES = [
  "/interface/phone.html",     // the front door
  "/interface/console.html",   // everything, one tap behind it
  "/interface/thea.js",
  "/interface/talk.js",
  "/interface/console.js",
  "/interface/icon.svg",
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
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(SHELL).then((c) => c.put(e.request, copy)).catch(() => {});
        return res;
      })
      .catch(() => caches.match(e.request).then((hit) => hit || caches.match("/interface/phone.html")))
  );
});
