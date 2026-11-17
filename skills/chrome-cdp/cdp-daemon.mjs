#!/usr/bin/env node
/**
 * chrome-cdp daemon — holds the ONE external Chrome DevTools Protocol connection that
 * Chrome allows, and serves commands from a directory queue.
 *
 * Why a daemon: Chrome grants remote debugging to a single external client per armed
 * session. A short-lived script that opens the websocket, does its work and closes it
 * spends that grant, and the next connection hangs until a person re-arms the box in
 * chrome://inspect. So one process owns the socket for as long as the machine runs, and
 * everything else talks to it through files.
 *
 * Why no dependencies: the queue protocol is JSON files, and Node 22+ has a global
 * WebSocket. Nothing to install, and the daemon can be started from any cwd.
 *
 * Protocol (both ends agree on the directory, see HOME below):
 *   <queue>/<id>.req.json  { "id": "x", "cmd": "eval", "args": { ... } }
 *   <queue>/<id>.res.json  { "id": "x", "ok": true, "result": ... }
 *                          { "id": "x", "ok": false, "error": "..." }
 *
 * Usage:  node cdp-daemon.mjs            # discover the port, attach, serve
 *         CDP_PORT=9333 node cdp-daemon.mjs
 *         node cdp-daemon.mjs --probe    # report what discovery finds, then exit
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const HOME = path.join(os.tmpdir(), 'chrome-cdp');
const QUEUE = path.join(HOME, 'queue');
const PIDFILE = path.join(HOME, 'daemon.pid');

// A websocket that will never open looks exactly like one that is slow to open, so every
// attempt is bounded. Refused (no server) comes back in milliseconds; a hang means the
// single client slot is taken.
const ATTACH_TIMEOUT_MS = 6000;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let ws = null;
let port = null;
let seq = 0;
const pending = new Map();

// ---------------------------------------------------------------------------
// Port discovery
// ---------------------------------------------------------------------------

/** Every TCP port a chrome process is listening on, newest Chrome first-class API. */
function chromeListenPorts() {
  try {
    if (process.platform === 'win32') {
      const out = execFileSync(
        'powershell.exe',
        [
          '-NoProfile',
          '-Command',
          'Get-NetTCPConnection -State Listen | ' +
            'Where-Object { $_.OwningProcess -in (Get-Process chrome -ErrorAction SilentlyContinue).Id } | ' +
            'Select-Object -ExpandProperty LocalPort -Unique',
        ],
        { encoding: 'utf8', timeout: 20000 },
      );
      return out.split(/\s+/).filter(Boolean).map(Number);
    }
    // macOS and Linux
    const out = execFileSync('lsof', ['-nP', '-iTCP', '-sTCP:LISTEN'], { encoding: 'utf8', timeout: 20000 });
    return [
      ...new Set(
        out
          .split('\n')
          .filter((line) => /[Cc]hrome/.test(line))
          .map((line) => line.split(/\s+/)[8] || '')
          .map((addr) => Number((addr.match(/:(\d+)$/) || [])[1]))
          .filter(Boolean),
      ),
    ];
  } catch {
    return [];
  }
}

/**
 * Open the browser websocket and answer Browser.getVersion, or explain why not.
 * The two failures are different and the difference is the whole diagnosis:
 *   refused -> that port is not a DevTools server (wrong port, or Chrome is gone)
 *   hung    -> the server is there, but it already has its one external client
 *
 * Two shapes of endpoint serve the same protocol:
 *   - a launched --remote-debugging-port answers HTTP /json/version with a websocket URL
 *     that carries a GUID; connect to exactly that URL.
 *   - the chrome://inspect box answers 404 to every HTTP path and only accepts the bare
 *     ws://host:port/devtools/browser. There is nothing to discover, so use it directly.
 */
async function browserWsUrl(p) {
  try {
    const r = await fetch(`http://127.0.0.1:${p}/json/version`, { signal: AbortSignal.timeout(2500) });
    if (r.ok) {
      const body = await r.json();
      if (body && typeof body.webSocketDebuggerUrl === 'string') return body.webSocketDebuggerUrl;
    }
  } catch {
    // no HTTP surface: the inspect endpoint, or not a DevTools server at all
  }
  return `ws://127.0.0.1:${p}/devtools/browser`;
}

async function probePort(p) {
  const url = await browserWsUrl(p);
  return new Promise((resolve) => {
    let sock;
    try {
      sock = new WebSocket(url);
    } catch (e) {
      return resolve({ port: p, state: 'refused', detail: e.message });
    }
    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      resolve(result);
    };
    sock.onopen = () => {
      const id = 1;
      sock.onmessage = (ev) => {
        let d;
        try {
          d = JSON.parse(ev.data);
        } catch {
          return;
        }
        if (d.id !== id) return;
        finish({ port: p, state: 'open', socket: sock, product: d.result?.product ?? '?' });
      };
      sock.send(JSON.stringify({ id, method: 'Browser.getVersion' }));
    };
    sock.onerror = () => finish({ port: p, state: 'refused' });
    sock.onclose = () => finish({ port: p, state: 'refused' });
    setTimeout(() => finish({ port: p, state: 'hung' }), ATTACH_TIMEOUT_MS);
  });
}

async function attach() {
  const forced = Number(process.env.CDP_PORT || 0);
  const candidates = forced ? [forced] : chromeListenPorts();
  if (!candidates.length) {
    return { ok: false, reason: 'no-port', detail: 'No chrome process is listening on any TCP port.' };
  }

  const outcomes = [];
  for (const p of candidates) {
    const r = await probePort(p);
    outcomes.push(r.state);
    if (r.state === 'open') {
      port = p;
      ws = r.socket;
      wireSocket();
      return { ok: true, product: r.product };
    }
  }

  if (outcomes.includes('hung')) {
    return {
      ok: false,
      reason: 'hung',
      detail:
        'The DevTools server answered nothing. Chrome already has its one external client, ' +
        'or the permission was never granted.',
    };
  }
  return { ok: false, reason: 'refused', detail: 'No listener on these ports speaks the DevTools protocol.' };
}

function wireSocket() {
  ws.onmessage = (ev) => {
    let d;
    try {
      d = JSON.parse(ev.data);
    } catch {
      return;
    }
    if (!d.id || !pending.has(d.id)) return;
    const p = pending.get(d.id);
    clearTimeout(p.timer);
    pending.delete(d.id);
    if (d.error) p.reject(new Error(JSON.stringify(d.error)));
    else p.resolve(d.result);
  };

  // Do NOT reconnect. Reconnecting burns attempts against a grant that is already spent,
  // and every failed attempt looks like another stuck attach. Say what to do and stop.
  ws.onclose = () => {
    console.error(
      '\n[chrome-cdp] The connection to Chrome closed. Chrome allows one external client per armed\n' +
        'session, and closing it consumes the grant. To restore it: in the browser open\n' +
        'chrome://inspect/#remote-debugging, uncheck "Allow remote debugging for this browser\n' +
        'instance", wait a second, check it again. Then start this daemon once more.\n',
    );
    ws = null;
    cleanupPid();
    process.exit(3);
  };
}

// ---------------------------------------------------------------------------
// Transport
// ---------------------------------------------------------------------------

function send(method, params = {}, sessionId, timeoutMs = 30000) {
  if (!ws) return Promise.reject(new Error('not attached'));
  const id = ++seq;
  const msg = { id, method, params };
  if (sessionId) msg.sessionId = sessionId;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`timeout: ${method}`));
    }, timeoutMs);
    pending.set(id, { resolve, reject, timer });
    ws.send(JSON.stringify(msg));
  });
}

/** Page targets, in the order Chrome lists them (most recently used first). */
async function pages() {
  const { targetInfos } = await send('Target.getTargets');
  return targetInfos.filter((t) => t.type === 'page');
}

/** A target id from an explicit id, a url substring, or the first page. */
async function pickTarget({ targetId, url } = {}) {
  if (targetId) return targetId;
  const list = await pages();
  if (!list.length) throw new Error('no page targets');
  if (url) {
    const hit = list.find((t) => (t.url || '').includes(url) || (t.title || '').includes(url));
    if (!hit) throw new Error(`no page matching "${url}"; open: ${list.map((t) => t.url).join(', ')}`);
    return hit.targetId;
  }
  return list[0].targetId;
}

/** Attach to a page, run fn with its session, detach. Attaching is cheap and idempotent. */
async function withSession(targetId, fn) {
  const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });
  try {
    return await fn(sessionId);
  } finally {
    await send('Target.detachFromTarget', { sessionId }).catch(() => {});
  }
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

const commands = {
  async ping() {
    const v = await send('Browser.getVersion');
    const list = await pages();
    return { port, product: v.product, protocol: v.protocolVersion, pages: list.length };
  },

  async targets() {
    return (await pages()).map((t) => ({ id: t.targetId, title: t.title, url: t.url }));
  },

  /**
   * Open a tab. background: true keeps focus where the person left it — always use it
   * unless the person has to look at the page.
   */
  async open({ url, background = true }) {
    if (!url) throw new Error('open needs a url');
    const { targetId } = await send('Target.createTarget', { url, background });
    return { targetId, url };
  },

  async close({ targetId }) {
    if (!targetId) throw new Error('close needs a targetId');
    await send('Target.closeTarget', { targetId });
    return { closed: targetId };
  },

  async activate({ targetId }) {
    if (!targetId) throw new Error('activate needs a targetId');
    await send('Target.activateTarget', { targetId });
    return { activated: targetId };
  },

  /**
   * Evaluate an expression in a page and return its value.
   * wait: true polls until the value is truthy — the way to wait for a page to settle.
   */
  async eval({ expression, targetId, url, wait = false, timeoutMs = 30000 }) {
    if (!expression) throw new Error('eval needs an expression');
    const id = await pickTarget({ targetId, url });
    return withSession(id, async (sessionId) => {
      const deadline = Date.now() + timeoutMs;
      for (;;) {
        const r = await send(
          'Runtime.evaluate',
          { expression, returnByValue: true, awaitPromise: true, userGesture: true },
          sessionId,
        );
        if (r.exceptionDetails) {
          const d = r.exceptionDetails;
          throw new Error(d.exception?.description || d.text || 'evaluation failed');
        }
        const value = r.result?.value;
        if (!wait || value) return value;
        if (Date.now() > deadline) return value ?? null;
        await sleep(300);
      }
    });
  },

  /** Screenshot a page to a file. Returns the path and its size. */
  async screenshot({ targetId, url, path: file, format = 'png' }) {
    if (!file) throw new Error('screenshot needs a path');
    const id = await pickTarget({ targetId, url });
    return withSession(id, async (sessionId) => {
      // A background tab is not being rasterised, so the capture never completes. Bringing
      // the tab to the front is the fix; say so, because it takes the person's focus.
      await send('Target.activateTarget', { targetId: id }).catch(() => {});
      await send('Page.enable', {}, sessionId).catch(() => {});
      await send('Page.bringToFront', {}, sessionId).catch(() => {});
      await sleep(400);
      let data;
      try {
        ({ data } = await send('Page.captureScreenshot', { format }, sessionId, 15000));
      } catch (first) {
        await sleep(1000);
        ({ data } = await send('Page.captureScreenshot', { format }, sessionId, 15000));
      }
      fs.mkdirSync(path.dirname(path.resolve(file)), { recursive: true });
      fs.writeFileSync(file, Buffer.from(data, 'base64'));
      return { path: path.resolve(file), bytes: fs.statSync(file).size, broughtToFront: true };
    });
  },
};

// ---------------------------------------------------------------------------
// Queue
// ---------------------------------------------------------------------------

function cleanupPid() {
  try {
    if (fs.existsSync(PIDFILE) && Number(fs.readFileSync(PIDFILE, 'utf8')) === process.pid) fs.unlinkSync(PIDFILE);
  } catch {}
}

async function serve() {
  for (;;) {
    let files = [];
    try {
      files = fs.readdirSync(QUEUE).filter((f) => f.endsWith('.req.json')).sort();
    } catch {}

    for (const name of files) {
      const reqFile = path.join(QUEUE, name);
      let req;
      try {
        req = JSON.parse(fs.readFileSync(reqFile, 'utf8'));
      } catch {
        continue; // half-written; the client will not be waiting on it yet
      }
      try {
        fs.unlinkSync(reqFile);
      } catch {}

      const reply = { id: req.id, ok: false };
      try {
        const fn = commands[req.cmd];
        if (!fn) throw new Error(`unknown command "${req.cmd}"; known: ${Object.keys(commands).join(', ')}`);
        reply.result = await fn(req.args || {});
        reply.ok = true;
      } catch (e) {
        reply.error = e.message;
      }
      fs.writeFileSync(path.join(QUEUE, `${req.id}.res.json`), JSON.stringify(reply, null, 2));
    }

    await sleep(250);
  }
}

// ---------------------------------------------------------------------------

async function main() {
  const probeOnly = process.argv.includes('--probe');
  const ports = process.env.CDP_PORT ? [Number(process.env.CDP_PORT)] : chromeListenPorts();

  if (probeOnly) {
    console.log(JSON.stringify({ ports }, null, 2));
    for (const p of ports) {
      const r = await probePort(p);
      console.log(`  ${p}: ${r.state}${r.product ? ' ' + r.product : ''}`);
      if (r.socket) try { r.socket.close(); } catch {}
    }
    return;
  }

  fs.mkdirSync(QUEUE, { recursive: true });

  // One daemon per machine.
  if (fs.existsSync(PIDFILE)) {
    const other = Number(fs.readFileSync(PIDFILE, 'utf8'));
    let alive = false;
    try {
      process.kill(other, 0);
      alive = true;
    } catch {}
    if (alive && other !== process.pid) {
      console.log(`[chrome-cdp] already running as pid ${other}; not starting a second one`);
      return;
    }
  }

  const r = await attach();
  if (!r.ok) {
    console.error(`[chrome-cdp] attach failed (${r.reason}): ${r.detail}`);
    if (r.reason === 'hung') {
      console.error(
        '[chrome-cdp] Fix, once, in the browser: chrome://inspect/#remote-debugging, uncheck\n' +
          '"Allow remote debugging for this browser instance", wait a second, check it again.\n' +
          'Then run this daemon once. It holds the connection from then on; nothing to re-accept.',
      );
    }
    process.exit(2);
  }

  fs.writeFileSync(PIDFILE, String(process.pid));
  console.log(`[chrome-cdp] attached on port ${port}: ${r.product}`);
  console.log(`[chrome-cdp] queue: ${QUEUE}`);

  const bye = () => {
    cleanupPid();
    process.exit(0);
  };
  process.on('SIGINT', bye);
  process.on('SIGTERM', bye);

  await serve();
}

main().catch((e) => {
  console.error('[chrome-cdp] fatal: ' + (e?.stack || e?.message || e));
  process.exit(1);
});
