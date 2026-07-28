# Taktline on iPhone and iPad

Two shipping routes, both from the same React codebase. There is no separate
mobile app to maintain.

| | Install | Cost | Camera scanning | Push |
|---|---|---|---|---|
| **Home-screen app (PWA)** | Safari → Share → Add to Home Screen | free, live now | re-asks permission every session | iOS 16.4+, not in the EU |
| **App Store build (Capacitor)** | App Store | $99/yr Apple account | permission persists, like any app | full |

The PWA works today with no further steps. The Capacitor project is in
`frontend/ios/` and builds — everything below is what only you can do, because
it needs your Apple account.

---

## What is already done

- **Installable web app** — manifest, icons, `apple-mobile-web-app` tags,
  safe-area insets. Add to Home Screen gives a full-screen Taktline with the
  offline shell the service worker already provided.
- **Barcode scan-to-advance** — `Scan` in the Operator view reads the Code 128
  on a printed lot label (the same symbol `/cards/{id}/label` prints), resolves
  it to a lot, and offers to advance it. Works in Safari via ZXing, lazily
  loaded so it never costs the board anything.
- **iOS project** — `frontend/ios/`, bundle id `com.taktline.app`, app icon,
  and the camera usage string. Verified with a real `xcodebuild` run:
  **BUILD SUCCEEDED** against the iOS Simulator SDK.

## The one architectural decision

The WebView loads **`https://taktline.com` directly** rather than bundling the
web assets. This is set in `frontend/capacitor.config.ts` and the reasoning is
in the comment there, but briefly: Taktline authenticates with `SameSite=Lax`
cookies, and bundled assets would put the WebView on `capacitor://localhost`,
making every API call cross-site — the cookies would stop being sent and
WKWebView's tracking prevention would block them as third-party. Loading the
real origin means cookies, CSRF and the WebSocket behave exactly as in Safari.

Consequences worth knowing:

- **Web releases reach the app immediately**, with no App Store review. Only
  changes to the native shell need a resubmission.
- **A cold launch needs the network.** The service worker covers reloads after
  the first successful load, not a first launch offline.
- Moving to bundled assets later means moving the native app to **token auth**.
  That is a real backend change, and the reason to do it is offline-first
  launches, not App Store policy.

---

## Building and shipping (needs your Apple account)

Capacitor 8 uses Swift Package Manager, so **CocoaPods is not required**.

```bash
cd frontend            # the Capacitor CLI lives here, not at the repo root —
                       # `npx cap` from the root fails with "could not
                       # determine executable to run"
npm run ios            # build the web bundle, sync it, open Xcode
```

`npm run ios:sync` stops before opening Xcode, and `npm run ios:open` skips
straight to it when nothing web-side has changed.

In Xcode, once per app:

1. **Signing & Capabilities** → select your Team. Xcode registers the bundle id
   `com.taktline.app` automatically.
2. Run on a connected iPhone to test. **Test scanning on real hardware** — the
   Simulator has no camera, so the one feature that justifies the native build
   cannot be verified there.

To submit: **Product → Archive** → Distribute App → App Store Connect. Then in
App Store Connect create the listing (screenshots, description, privacy
answers, and a support URL).

### Two things that get apps rejected

**Guideline 4.2, "minimum functionality."** Apple rejects apps that are only a
website in a shell — which, given `server.url`, is a fair description of the
shell alone. The defence is the camera: scanning a lot label to advance work is
device functionality a website cannot do as well. Say so in the review notes,
and give the reviewer a **demo account with a line already built and a printed
label they can scan** (a PDF of one in the notes is enough).

**Privacy answers.** Taktline collects an email address and product usage tied
to an account. Answer the App Privacy questionnaire accordingly; a mismatch
between the questionnaire and the app's actual behaviour is a rejection, and a
slow one.

### Pointing a build somewhere else

```bash
CAP_SERVER_URL=https://staging.taktline.com npx cap sync ios
```

---

## Where the native build earns its keep next

The shell is deliberately thin. The things worth adding to it, in the order
they pay off:

1. **Native barcode scanning** (`@capacitor-mlkit/barcode-scanning`) — the web
   scanner already works, but the native one is faster in poor light and on
   damaged labels, which is the actual shop-floor condition. `ScanSheet` picks
   its decoder at runtime, so this slots in behind the same UI.
2. **Push notifications** — "work is waiting at your station." Needs the
   backend to store device tokens and send via APNs; there is no push
   infrastructure in Taktline today.
3. **Screen wake lock** — a station tablet should not sleep mid-shift. The web
   API covers this on iOS 16.4+, so try that before reaching for native.
