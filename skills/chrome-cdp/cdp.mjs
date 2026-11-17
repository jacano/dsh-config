#!/usr/bin/env node
/**
 * chrome-cdp client — the fast path to the person's own Chrome, already signed in.
 *
 * It never opens the DevTools websocket itself; it writes a request into the daemon's
 * queue and reads the reply. That is deliberate: Chrome arms remote debugging for one
 * external client, so the socket belongs to the daemon and to nothing else.
 *
 *   node cdp.mjs start                       # attach once (idempotent)
 *   node cdp.mjs ping
 *   node cdp.mjs targets
 *   node cdp.mjs eval "document.title"
 *   node cdp.mjs eval --url mail.google.com --wait "!!document.querySelector('tr.zA')"
 *   node cdp.mjs open https://example.com    # background tab, focus untouched
 *   node cdp.mjs shot page.png --url example.com
 *   node cdp.mjs stop
 *
 * Every command prints JSON on stdout and exits non-zero on failure.
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const HOME = path.join(os.tmpdir(), 'chrome-cdp');
const QUEUE = path.join(HOME, 'queue');
const PIDFILE = path.join(HOME, 'daemon.pid');
const LOG = path.join(HOME, 'daemon.log');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function alive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function daemonPid() {
  try {
    const pid = Number(fs.readFileSync(PIDFILE, 'utf8'));
    return pid && alive(pid) ? pid : null;
  } catch {
    return null;
  }
}

/** Ask the daemon to run one command. Resolves to {ok, result, error}. */
function call(cmd, args = {}, { waitMs = 180000 } = {}) {
  fs.mkdirSync(QUEUE, { recursive: true });
  const id = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  const reqFile = path.join(QUEUE, `${id}.req.json`);
  const resFile = path.join(QUEUE, `${id}.res.json`);
  fs.writeFileSync(reqFile, JSON.stringify({ id, cmd, args }));

  const deadline = Date.now() + waitMs;
  while (Date.now() < deadline) {
    if (fs.existsSync(resFile)) {
      const out = JSON.parse(fs.readFileSync(resFile, 'utf8'));
      try {
        fs.unlinkSync(resFile);
      } catch {}
      return out;
    }
    // Synchronous sleep keeps this usable as a one-liner with no async plumbing.
    execSleep(120);
  }
  try {
    fs.unlinkSync(reqFile);
  } catch {}
  return { ok: false, error: `the daemon did not answer "${cmd}" in ${waitMs} ms` };
}

function execSleep(ms) {
  const shared = new SharedArrayBuffer(4);
  Atomics.wait(new Int32Array(shared), 0, 0, ms);
}

function tailLog(lines = 12) {
  try {
    return fs.readFileSync(LOG, 'utf8').trimEnd().split('\n').slice(-lines).join('\n');
  } catch {
    return '';
  }
}

/** Start the daemon if it is not running, and wait until it answers. */
function start() {
  if (daemonPid()) {
    const p = call('ping', {}, { waitMs: 5000 });
    if (p.ok) return { ok: true, already: true, ...p.result };
  }

  fs.mkdirSync(HOME, { recursive: true });
  const fd = fs.openSync(LOG, 'a');
  const child = spawn(process.execPath, [path.join(HERE, 'cdp-daemon.mjs')], {
    detached: true,
    stdio: ['ignore', fd, fd],
    windowsHide: true,
  });
  child.unref();
  fs.closeSync(fd);

  const deadline = Date.now() + 25000;
  while (Date.now() < deadline) {
    execSleep(400);
    const p = call('ping', {}, { waitMs: 1500 });
    if (p.ok) return { ok: true, already: false, ...p.result };
    const pid = daemonPid();
    if (pid && !alive(pid)) break;
  }
  return { ok: false, error: 'the daemon did not attach', log: tailLog() };
}

// ---------------------------------------------------------------------------
// Argument parsing: flags anywhere, the rest positional.
// ---------------------------------------------------------------------------

function parse(argv) {
  const flags = {};
  const rest = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith('--')) {
      rest.push(a);
      continue;
    }
    const name = a.slice(2);
    if (['wait', 'foreground', 'json'].includes(name)) flags[name] = true;
    else flags[name] = argv[++i];
  }
  return { flags, rest };
}

const { flags, rest } = parse(process.argv.slice(2));
const cmd = rest[0];
let out;

switch (cmd) {
  case undefined:
  case 'help':
    out = {
      ok: true,
      usage: [
        'start                              attach once (idempotent), or say why not',
        'stop                               close the daemon deliberately',
        'ping                               {port, product, protocol, pages}',
        'targets                            every page target: {id, title, url}',
        'eval [--url substr] [--target id] [--wait] [--timeout ms] <expression>',
        'open <url> [--foreground]           background tab by default',
        'close <targetId>',
        'activate <targetId>                 brings a tab to the front',
        'shot <file> [--url substr] [--target id]',
      ],
    };
    break;

  case 'start':
    out = start();
    break;

  case 'stop': {
    const pid = daemonPid();
    if (!pid) out = { ok: true, stopped: false, note: 'no daemon running' };
    else {
      try {
        process.kill(pid);
      } catch {}
      execSleep(400);
      out = { ok: true, stopped: true, pid };
    }
    break;
  }

  case 'ping':
    out = call('ping', {}, { waitMs: 6000 });
    break;

  case 'targets':
    out = call('targets');
    break;

  case 'eval': {
    const expression = rest.slice(1).join(' ');
    if (!expression) {
      out = { ok: false, error: 'eval needs an expression' };
      break;
    }
    out = call('eval', {
      expression,
      url: flags.url,
      targetId: flags.target,
      wait: !!flags.wait,
      timeoutMs: Number(flags.timeout || 30000),
    });
    break;
  }

  case 'open':
    out = call('open', { url: rest[1], background: !flags.foreground });
    break;

  case 'close':
    out = call('close', { targetId: rest[1] });
    break;

  case 'activate':
    out = call('activate', { targetId: rest[1] });
    break;

  case 'shot':
    out = call('screenshot', { path: rest[1], url: flags.url, targetId: flags.target }, { waitMs: 120000 });
    break;

  default:
    out = { ok: false, error: `unknown command "${cmd}"` };
}

if (out && out.ok) {
  console.log(JSON.stringify(out, null, 2));
  process.exit(0);
}
console.log(JSON.stringify(out || { ok: false, error: 'no output' }, null, 2));
process.exit(1);
