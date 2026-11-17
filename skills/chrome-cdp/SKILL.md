---
name: chrome-cdp
description: Drive the person's own Chrome — already signed in — over the DevTools protocol, and keep that one connection alive. Use when a task needs a page that only exists logged in in their browser, a tab they already have open, or a site that blocks a fresh automated browser.
version: 1.0.0
---

# chrome-cdp

Three files: this one, [`cdp-daemon.mjs`](cdp-daemon.mjs) and [`cdp.mjs`](cdp.mjs).
No dependencies; Node 22 or later for the global `WebSocket`. Nothing to install.

The person's Chrome is not a fresh browser. It is the one with their session, their
cookies and their tabs — so it can read the page that needs a login, and it is not
challenged the way a brand-new automated browser is. That is the whole value.

## The one rule

**Chrome grants remote debugging to one external client per armed session.** The grant
is spent by the connect, and closing the socket does not return it: the next attempt
hangs with no error at all until a person goes back to the checkbox. Therefore:

- One long-lived process owns the socket. Never open, work and close.
- Never reconnect in a loop. Each attempt against a spent grant is another silent hang.
- If the daemon dies, a person has to re-arm the box once (below). Say so plainly; do
  not present it as a bug they caused.

A Chrome launched with `--remote-debugging-port` on a throwaway profile behaves
differently and accepts several clients. That is the test profile, not the person's.

## Start

```bash
node skills/chrome-cdp/cdp.mjs start     # attach once; idempotent; safe to repeat
node skills/chrome-cdp/cdp.mjs ping
```

`start` spawns the daemon detached, waits for the attach and prints
`{ok, port, product, pages}`. If the attach cannot be made it exits non-zero and says
which of the two failures happened. Run everything else from the same tree.

## The two failures, and they are not the same

| Daemon says | Means | Do |
| --- | --- | --- |
| `refused` | No listener on those ports speaks DevTools. Chrome is closed, or the box is unchecked. | Ask them to open `chrome://inspect/#remote-debugging` and check **Allow remote debugging for this browser instance**, then `start` again. |
| `hung` | The server is there and answered nothing: the one client slot is taken, by a dead daemon or an already-spent grant. | **Uncheck, wait a second, re-check** the same box. Then `start` once. |

`refused` comes back in milliseconds. `hung` costs the full 6-second probe timeout. That
difference is the diagnosis, so never read a hang as "port wrong" and try another port.

`node cdp-daemon.mjs --probe` prints the ports discovered and what each one answers,
without attaching and without writing the pid file. Use it first when something is off.

## Why the obvious approaches do not work

| Attempt | What happens |
| --- | --- |
| `chrome --remote-debugging-port=9222` on the default profile | Current Chrome (seen on 157) does not offer a debugging port on the default profile. The `chrome://inspect` box is the supported way, and it picks a random port. |
| `chromium.connectOverCDP('http://127.0.0.1:<port>')` | It calls HTTP `/json/version` first. The inspect endpoint answers **404 to every HTTP path**, so Playwright reports "Unexpected status 404". |
| `connectOverCDP('ws://127.0.0.1:<port>/devtools/browser')` | Times out at 30 s. The socket is fine; Playwright still wants the HTTP endpoint for version and targets. |
| Copying the profile's `Cookies` while Chrome runs | The SQLite file is held with an exclusive lock. Even `robocopy /B` fails. This is why the person's *session* needs CDP, not the cookie jar. |

So: raw DevTools protocol over `WebSocket`, and nothing above it.

## What the endpoint looks like

The `chrome://inspect` server listens on `127.0.0.1:<random>`, and:

- answers `404` to `/json`, `/json/version`, `/json/list`, `/devtools/browser` over HTTP;
- accepts `ws://127.0.0.1:<port>/devtools/browser` and answers `Browser.getVersion`.

The port is random per Chrome start and survives a Chrome patch update, but not a
restart. Never hardcode it: the daemon discovers it (Windows: `Get-NetTCPConnection`
filtered by the chrome pids; macOS/Linux: `lsof -nP -iTCP -sTCP:LISTEN`). `CDP_PORT`
overrides discovery when you know the port.

A launched `--remote-debugging-port` is the other shape: HTTP works, `/json/version`
returns a websocket URL with a GUID, and that exact URL is what to connect to. The
daemon handles both, so the same code drives a test profile and the real browser.

## The daemon and the queue

The daemon holds the socket; everything else writes a request file and reads a reply.

```
$TMP/chrome-cdp/queue/<id>.req.json   {"id","cmd","args"}
$TMP/chrome-cdp/queue/<id>.res.json   {"id","ok":true,"result":...}
$TMP/chrome-cdp/daemon.pid
$TMP/chrome-cdp/daemon.log
```

Files rather than a socket of our own, so a one-line shell command, a Python script and
an agent all use it without a client library, and the daemon can start from any cwd
(`$TMP` is shared, not the repo). `cdp.mjs` is only a thin wrapper over that queue.

## Commands

| Command | Returns |
| --- | --- |
| `start` / `stop` | attach (idempotent) / close the daemon |
| `ping` | `{port, product, protocol, pages}` |
| `targets` | every page target: `{id, title, url}` |
| `open <url> [--foreground]` | `{targetId}`; **background by default**, so focus stays where they left it |
| `eval [--url substr] [--target id] [--wait] [--timeout ms] <expr>` | the expression's value |
| `close <targetId>` | `{closed}` |
| `activate <targetId>` | bring a tab to the front (this is the person's screen) |
| `shot <file> [--url substr] [--target id]` | `{path, bytes}` — brings the tab to the front to render it |

`eval` is the whole DOM API: select, click, type, scroll, read. No brittle helper layer.
A returned object or array is passed through as JSON. `--wait` polls every 300 ms until
the value is truthy, which is how a page is allowed to settle:

```bash
node cdp.mjs eval --url example.com --wait "document.readyState === 'complete'"
node cdp.mjs eval --url example.com "document.querySelectorAll('tr').length"
```

## Recipes

**Read a page they are already signed in to.** Open it in the background if it is not
open, wait for the content, read the text:

```bash
node cdp.mjs open "https://example.com/dashboard"
node cdp.mjs eval --url example.com --wait "document.querySelector('.row')?.innerText"
node cdp.mjs eval --url example.com "document.body.innerText.slice(0, 4000)"
```

**Fill and submit a form.** Set values the way a framework notices — assign, then
dispatch `input` and `change`:

```bash
node cdp.mjs --url example.com eval "(el => {
  el.value = 'Juan';
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
})(document.querySelector('#name'))"
```

**Click.** A real `click()` on a detached node does nothing; click the node that is in
the document, and scroll it into view first:

```bash
node cdp.mjs eval --url example.com "(el => { el.scrollIntoView(); el.click(); })(document.querySelector('button[type=submit]'))"
```

Then wait for what the click produces, not for a duration:

```bash
node cdp.mjs eval --url example.com --wait --timeout 60000 "!!document.querySelector('.confirmation')"
```

**Close a tab you opened.** Do not leave tabs behind in their browser:

```bash
node cdp.mjs close <targetId>
```

## Rules of engagement

- **Do not tidy up the socket.** A `stop` is only for a deliberate restart; leaving the
  daemon running costs nothing and re-attaching costs a person's click.
- **Do not kill chrome processes** and do not launch a second Chrome on their profile.
  Closing their browser to "start clean" destroys the session you came for.
- **Background by default.** `open` without `--foreground`, and no `activate` unless the
  person has to look at the page. `shot` does bring a tab to the front; say so.
- **The banner is expected.** While the daemon is attached, Chrome shows "Chrome is
  being controlled by automated test software". Nothing needs turning off.
- **Their session is their identity.** Reading a page is one thing; pressing a button
  that spends money, sends a message or deletes something is another. Confirm first.
- **Close what you open, keep what was theirs.** Tabs you created are yours to close.
  A tab that was already there stays.

## What was verified, and how

On 2026-11-17, on Windows, Chrome 157.0.8103.78/.79:

- the inspect endpoint answered `404` to `/json`, `/json/version`, `/json/list` and
  `/devtools/browser`, and `Browser.getVersion` over `ws://…/devtools/browser`;
- `Target.getTargets`, `Target.createTarget` (background), `Target.attachToTarget`
  with `flatten: true`, `Runtime.evaluate` with `returnByValue` and the single-client
  behaviour were exercised against the person's live profile — reading a signed-in page
  in a background tab and closing it;
- `chromium.connectOverCDP` failed both ways described in the table above;
- `start`, `ping`, `targets`, `open`, `eval`, `eval --wait`, `shot` and the two error
  paths (`no page matching`, an exception inside the evaluated code) were exercised
  against a throwaway `--remote-debugging-port` Chrome on this same code;
- a second client against a launched debug port is accepted, which is why the one-client
  rule above is stated for the inspect endpoint and not in general.

Not exercised: `Page.captureScreenshot` in the person's own Windows, and any non-Windows
port discovery.
