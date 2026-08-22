# UI tests

Browser-free checks for the console. Two suites:

| File | What it covers |
| --- | --- |
| `css-cascade.mjs` | That elements toggled via the `hidden` attribute are actually hidden. Guards the bug where `.scrim { display: flex }` (an author rule) beat the browser's `[hidden] { display: none }`, leaving the sign-in dialog permanently on screen. |
| `ui-flows.mjs` | Drives the real frontend in jsdom against a stubbed API: sign-in, analysis, comparison, indexing, asking, follow-ups, citations, sessions, job match, errors. 82 assertions. |
| `design-system.mjs` | Accessibility and design-system integrity: labels, landmarks, focus management, ARIA state, token discipline, responsive breakpoints, component coverage. No server needed. |

## Running them

```bash
npm install jsdom          # the only dev dependency

node tests/ui/css-cascade.mjs      # instant, no server needed
node tests/ui/design-system.mjs   # instant, no server needed

# flows need the stub server (no GitHub, no OpenAI, no Redis — all faked)
python tests/ui/stub_server.py &   # serves on :8111
node tests/ui/ui-flows.mjs
kill %1
```

## A caveat worth knowing

jsdom does not model author-vs-UA stylesheet precedence, so
`getComputedStyle` there can disagree with a real browser. `css-cascade.mjs`
therefore resolves the cascade itself rather than trusting jsdom — an earlier
version of `ui-flows.mjs` asserted the `hidden` *property* and happily passed
on a screen that was unusable in Chrome.
