# Field Capture PWA

The app an Anganwadi worker or Ashram school staff member actually uses, every
day, on a basic Android phone, often with no signal.

```bash
cd apps/field-pwa && npm install && npm run dev
```

Needs the FastAPI backend on `:8000` (`cd backend && make serve`); Vite proxies
`/api` to it. Sign in with a seeded worker phone number — `9999900001` (Ghatol),
`9999900002` (Anandpuri, the Ashram school), `9999900003` (Sagwara).

---

## Deliberately not premium

Section 9.1 of the master prompt is explicit, and it is worth restating because
it runs against the grain of the rest of this project:

> This is the one app in your portfolio where the usual Motion v12 / GSAP /
> React Three Fiber treatment is the *wrong* choice.

So there is no animation library, no 3D, no UI framework, no CSS framework and
no icon package. Icons are inline SVG, styling is plain CSS over custom
properties, and navigation is component state rather than a router. The whole
bundle is **63 KB gzipped**, most of it React itself.

That is not minimalism as an aesthetic. Every dependency is bytes parsed on a
slow CPU before a worker can photograph a plate, and the premium treatment
belongs in Phase 5's State Admin view, which is the surface a reviewer actually
looks at.

What Section 9.1 *does* ask for is all here: large touch targets, a Hindi-first
bilingual interface, capture in two taps, dropdowns over text fields, and sync
status that is visible rather than silent.

---

## Offline-first

Section 7 governs the architecture. The rule is that no network call ever blocks
the worker, so the capture path has no code that could wait on one:

```
photograph  →  compress  →  IndexedDB  →  DONE, worker moves to the next plate
                                       ↓
                             background: upload when a connection appears
```

- **Everything is queued locally first.** A capture is durable the moment it is
  taken. The server is somewhere the queue eventually drains to.
- **The beneficiary list is cached** on first sign-in, so matching a photo to a
  child works with no signal — a dropdown over cached data, never a live search.
- **Sync has three triggers** (`online`, `visibilitychange`, a slow interval)
  because none is dependable on Android, plus the manual *अभी भेजें* button
  Section 7 asks for by name.
- **Backoff persists** across app launches, which on a low-memory phone happen
  constantly. Failed items stop auto-retrying after five attempts and wait for a
  person.
- **Sign-in is the only screen that needs internet**, and it says so.

## Photos

Compressed to ~1280px / JPEG 0.7 before queueing — a 4 MB camera file becomes
~200 KB. Fifty plates a day is then 12 MB rather than 250 MB, which is the
difference between a queue that drains overnight and one that never does.

The **original is kept until the server confirms receipt**, as insurance against
a compression bug silently degrading every photograph in a pilot that cannot be
re-run. That roughly doubles peak storage, so `src/db/storage.ts` sheds
originals oldest-first once the device passes 80% of quota, warns the worker at
70%, and never touches the compressed uploads — those are the evidence.

Two capture paths: an in-app viewfinder, and the phone's own camera app via
`<input capture="environment">`. **The file input is the default and the
viewfinder is the upgrade.** Every viewfinder failure — no permission, no secure
context, an old WebView, a dead stream — resolves *towards* the fallback rather
than towards an error screen, and the fallback gets equal test coverage because
it is what runs on the oldest phones in the pilot.

## Bilingual

Hindi is the source language and English is secondary, per Section 9.1 — not the
reverse. The app opens in Hindi regardless of the phone's locale; English is a
choice a worker makes, not a default they have to undo.

Both languages ship in the bundle and the toggle is local, because an
offline-first app cannot have a language switch that needs the network. A test
asserts every string has real Devanagari and is not a copy of the English.

Error messages come back from the backend already bilingual (Phase 1's
problem+json carries `title_hi` and `title_en`), so there is no client string
table to fall out of date.

## Four themes

Light, dark, system — and **sunlight**.

The fourth is not a cosmetic variant. This app is used outdoors in Rajasthan on
a budget LCD at a few hundred nits, where a normal light theme is genuinely
unreadable, and a worker who cannot read the screen cannot confirm which child
they just photographed. Sunlight mode is pure black on white (21:1), heavier
weights, 12% larger type, 2px borders and no shadows. Deliberately blunt: it is
meant to be switched on outside and off again indoors.

Contrast was checked per theme rather than inferred from light mode. Body text
meets 4.5:1 and secondary text 3:1 in all four.

## Accessibility

Section 9.1 expects a user who may not be confident with apps, so these are
requirements rather than polish:

- 48px minimum touch targets; 72px for the capture and record buttons
- Visible labels on every control — never placeholder-only
- Icon **and** text on every navigation item; no icon-only controls
- Status conveyed by icon and text, never colour alone
- Errors stated near the field, with a recovery path
- `prefers-reduced-motion` respected (there is little motion to reduce)
- A skip link, a polite live region, and `document.lang` kept in step with the
  language toggle so screen readers pick the right voice
- Zoom never disabled

---

## Layout

```
src/
├── styles/      tokens.css (4 themes) + base.css
├── i18n/        Hindi-first bilingual strings
├── theme/       light / dark / system / sunlight
├── db/          IndexedDB queue, cache, storage quota guard
├── api/         backend client
├── sync/        queue drain, backoff, auto-sync triggers
├── capture/     compression, camera detection, portable byte reading
├── components/  icons, hooks, child picker
└── screens/     SignIn, Home, Capture, Growth, Queue, Settings
```

## Tests

```bash
npm test
```

119 tests. The ones worth reading first are `tests/sync.test.ts` — every test
there is a variation on *after this failure, is the worker's evidence still on
the phone and still sendable?* — and `tests/camera.test.ts`, which asserts that
every camera failure mode lands the worker in the system camera rather than on
an error screen.

## Known limitations at this phase

- **Auth is Phase 1's dev token endpoint.** Any registered phone number signs in
  with no verification. Phase 6 replaces the identity source; nothing else here
  changes.
- **Growth classification requires connectivity to display.** The measurement is
  recorded offline, but the WHO status is computed server-side (Section 6.4
  forbids a second implementation that could drift from the audited one), so it
  appears when the entry syncs. The worker is told this rather than shown a
  blank.
- **No push notification** when a sync completes in the background — the badge
  updates when the app is open. Whether that matters is a question for the
  shadow pilot, not something to guess at now.
