// One long-running `python -m tools.design designer --serve` process per repository root.
// Requests and responses are single JSON lines matched by request_id. A request that does not
// answer in time kills the process; a crashed process is restarted on the next request (at
// most a few times a minute), and nothing is ever written to disk by this side.
"use strict";
const { spawn } = require("child_process");

const PROTOCOL_VERSION = 1;

/** An error before the process ever answered: the interpreter itself is the likely cause (offer Change Interpreter). */
function startupError(message) { const e = new Error(message); e.startup = true; return e; }

class Bridge {
  /** @param {{python: string, root: string, log?: (s: string) => void, timeoutMs?: number}} opts */
  constructor(opts) {
    this.python = opts.python;
    this.root = opts.root;
    this.log = opts.log || (() => {});
    this.timeoutMs = opts.timeoutMs || 30000;
    this.proc = null;
    this.buffer = "";
    this.pending = new Map();
    this.nextId = 1;
    this.restarts = [];
    this.disposed = false;
  }

  get pid() { return this.proc ? this.proc.pid : null; }

  _start() {
    const now = Date.now();
    this.restarts = this.restarts.filter((t) => now - t < 60000);
    if (this.restarts.length >= 5) throw new Error("the design tooling keeps stopping; see Feature Designer: Show Log");
    this.restarts.push(now);
    // -E ignores PYTHON* environment variables (no PYTHONPATH/PYTHONSTARTUP injection); -B writes no .pyc files.
    const args = ["-B", "-E", "-m", "tools.design", "designer", "--serve", "--root", this.root];
    const proc = spawn(this.python, args, { cwd: this.root, windowsHide: true, stdio: ["pipe", "pipe", "pipe"], shell: false });
    this.proc = proc;
    this.buffer = "";
    proc.fdAnswered = false;                         // set by the first valid response: until then, problems are start-up problems
    proc.fdStderr = "";
    proc.stdout.setEncoding("utf8");
    proc.stdout.on("data", (chunk) => this._onData(chunk, proc));
    proc.stderr.setEncoding("utf8");
    proc.stderr.on("data", (chunk) => { proc.fdStderr = (proc.fdStderr + chunk).slice(-2000); this.log(`[python] ${chunk.trimEnd()}`); });
    // A write to a process that has just died fails asynchronously (EPIPE); the exit handler reports it.
    proc.stdin.on("error", (err) => this.log(`[bridge] could not write to the design tooling: ${err.code || err.message}`));
    const fail = (err) => {                         // only this process's requests: a replacement may already run
      if (this.proc === proc) this.proc = null;
      for (const [id, p] of this.pending)
        if (p.proc === proc) { clearTimeout(p.timer); this.pending.delete(id); p.reject(err); }
    };
    proc.on("spawn", () => this.log(`[bridge] started ${this.python} (pid ${proc.pid})`));   // only a real start is logged
    proc.on("error", (err) => {
      this.log(`[bridge] cannot start ${this.python}: ${err.message}`);
      fail(startupError(`cannot start the design tooling with ${this.python}: ${err.code || err.message}`));
    });
    proc.on("exit", (code, signal) => {
      this.log(`[bridge] python exited (${code ?? signal})`);
      if (proc.fdAnswered) { fail(new Error("the design tooling stopped unexpectedly")); return; }
      const last = proc.fdStderr.trim().split(/\r?\n/).pop() || "";
      fail(startupError(`${this.python} stopped while starting the design tooling (exit ${code ?? signal})` +
        (last ? `: ${last.slice(0, 300)}` : "") + ". Check that featureDesigner.pythonPath is the repository's Python interpreter"));
    });
  }

  _onData(chunk, proc) {
    this.buffer += chunk;
    let nl;
    while ((nl = this.buffer.indexOf("\n")) !== -1) {
      const line = this.buffer.slice(0, nl).replace(/\r$/, "");
      this.buffer = this.buffer.slice(nl + 1);
      if (!line.trim()) continue;
      let msg;
      try { msg = JSON.parse(line); } catch { this.log(`[bridge] ignored non-JSON output: ${line.slice(0, 200)}`); continue; }
      const p = this.pending.get(msg.request_id);
      if (!p) { this.log(`[bridge] response without a pending request: ${String(msg.request_id)}`); continue; }
      if (proc) proc.fdAnswered = true;
      this.pending.delete(msg.request_id);
      clearTimeout(p.timer);
      p.resolve(msg);
    }
  }

  /** Send one request; resolves with the response object (check `ok`). */
  request(op, fields = {}) {
    if (this.disposed) return Promise.reject(new Error("Feature Designer is shutting down"));
    if (!this.proc) {
      try { this._start(); } catch (err) { return Promise.reject(err); }
    }
    const id = this.nextId++;
    const line = JSON.stringify({ ...fields, version: PROTOCOL_VERSION, op, request_id: id }) + "\n";
    const proc = this.proc;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        const s = Math.round(this.timeoutMs / 1000);
        reject(proc.fdAnswered
          ? new Error(`the design tooling did not answer within ${s} s`)
          : startupError(`${this.python} did not start the design tooling within ${s} s. ` +
                         "Check that featureDesigner.pythonPath is the repository's Python interpreter"));
        this._kill();                                // a stuck process is replaced on the next request
      }, this.timeoutMs);
      this.pending.set(id, { resolve, reject, timer, proc });
      try { this.proc.stdin.write(line, "utf8"); } catch (err) { clearTimeout(timer); this.pending.delete(id); reject(err); }
    });
  }

  _kill() {
    const proc = this.proc;
    this.proc = null;
    if (!proc) return;
    try { proc.stdin.end(); } catch { /* already closed */ }
    try { proc.kill(); } catch { /* already gone */ }
  }

  dispose() {
    this.disposed = true;
    for (const [, p] of this.pending) { clearTimeout(p.timer); p.reject(new Error("Feature Designer is shutting down")); }
    this.pending.clear();
    this._kill();
  }
}

module.exports = { Bridge, PROTOCOL_VERSION };
