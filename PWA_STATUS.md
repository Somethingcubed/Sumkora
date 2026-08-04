# PWA status

Date: 4 August 2026

## Implemented

- Web app manifest with stable app identity, standalone display, theme colors,
  category metadata, and a maskable-capable SVG icon.
- Root-scoped service worker with a versioned static app-shell cache.
- Network-first navigation with a small offline explanation page. Private
  analyses are deliberately not cached.
- Install prompt controls on authentication and mobile navigation surfaces
  when the browser exposes `beforeinstallprompt`.
- Phone camera file input using the rear camera where the browser supports the
  `capture` hint.
- Responsive, touch-sized upload and page-management controls.

## Deliberate limits

- Paper upload, analysis, saved reports, and model calls require a connection.
- Student HTML and private files are never stored in the service-worker cache.
- iOS controls installation through Safari's Share > Add to Home Screen and
  does not expose the Chromium install prompt event.
- The existing SVG identity is reused; dedicated store-grade raster icons can
  be added later without changing the PWA architecture.

## Verification

- `/service-worker.js` is served with `Service-Worker-Allowed: /`.
- The manifest, service worker, offline page, and registration script are
  covered by route and markup tests.

