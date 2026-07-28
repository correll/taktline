import type { CapacitorConfig } from '@capacitor/cli'

/**
 * Taktline iOS shell.
 *
 * ── Why the WebView loads the live site rather than bundled assets ──────────
 * Taktline authenticates with an httpOnly session cookie plus a double-submit
 * CSRF cookie, both SameSite=Lax, and holds a WebSocket open for live board
 * updates. Bundling the web assets would put the WebView on
 * `capacitor://localhost`, making every API call cross-site: Lax cookies would
 * stop being sent, and WKWebView's tracking prevention blocks the third-party
 * cookies they would have to become. Fixing that properly means moving the
 * native app to token auth — a real backend change, not a config tweak.
 *
 * Pointing `server.url` at the deployed origin sidesteps all of it: the
 * WebView *is* taktline.com, so cookies, CSRF and the WebSocket behave exactly
 * as they do in Safari, and web releases reach the app without an App Store
 * review. The trade is that a cold launch needs the network — the service
 * worker only covers reloads after the first successful load.
 *
 * A deliberate v1 choice, not the end state. Bundling + token auth is the
 * right destination once there is a reason to pay for it.
 *
 * ── App Store review ────────────────────────────────────────────────────────
 * Guideline 4.2 rejects apps that are only a website in a shell. The defence
 * is that this one is not: barcode scanning drives the camera. Keep that
 * working and lead with it in the review notes.
 */
const config: CapacitorConfig = {
  appId: 'com.taktline.app',
  appName: 'Taktline',
  webDir: 'dist',
  server: {
    // Override with CAP_SERVER_URL to point a build at staging.
    url: process.env.CAP_SERVER_URL ?? 'https://taktline.com',
    cleartext: false,
  },
  ios: {
    // The board is a light surface; a dark scroll background flashes on bounce.
    backgroundColor: '#F7F6F2',
    // Let the web layer own the safe areas — global.css already handles them
    // with env(safe-area-inset-*), and doing it in both places double-pads.
    contentInset: 'never',
  },
}

export default config
