/**
 * Client for the in-process ACIS agent (cst_acis_agent.dll).
 *
 * The agent listens on \\.\pipe\cst-acis-<pid> inside modeler_AMD64.exe and
 * answers one line per request on its UI thread. Protocol is deliberately
 * line-based: "OK ..." / "ERR ...".
 */
import net from "node:net";
import { execFile } from "node:child_process";

export function findModelerPid() {
  return new Promise((resolve, reject) => {
    execFile(
      "tasklist",
      ["/FI", "IMAGENAME eq modeler_AMD64.exe", "/FO", "CSV", "/NH"],
      { windowsHide: true },
      (err, stdout) => {
        if (err) return reject(err);
        const first = stdout.split(/\r?\n/).find((l) => l.trim().startsWith('"'));
        if (!first) return reject(new Error("modeler_AMD64.exe is not running (open a 3D project first)"));
        const pid = Number(first.split('","')[1]);
        Number.isFinite(pid) ? resolve(pid) : reject(new Error(`cannot parse tasklist output: ${first}`));
      },
    );
  });
}

export class AcisPipe {
  #socket = null;
  #buf = "";
  #waiters = [];
  #pid = null;

  get pid() {
    return this.#pid;
  }

  get connected() {
    return Boolean(this.#socket);
  }

  connect(pid) {
    return new Promise((resolve, reject) => {
      const sock = net.connect(`\\\\.\\pipe\\cst-acis-${pid}`);
      const onError = (err) => {
        sock.destroy();
        reject(new Error(`cannot reach cst-acis-${pid}: ${err.message}. Is cst_acis_agent.dll injected into that modeler?`));
      };
      sock.once("error", onError);
      sock.once("connect", () => {
        sock.off("error", onError);
        sock.on("data", (chunk) => this.#onData(chunk));
        sock.on("close", () => {
          this.#socket = null;
          for (const w of this.#waiters.splice(0)) w.reject(new Error("agent pipe closed"));
        });
        this.#socket = sock;
        this.#pid = pid;
        resolve(pid);
      });
      sock.setEncoding("utf8");
    });
  }

  #onData(chunk) {
    this.#buf += chunk;
    let nl;
    while ((nl = this.#buf.indexOf("\n")) >= 0) {
      const line = this.#buf.slice(0, nl).trim();
      this.#buf = this.#buf.slice(nl + 1);
      const waiter = this.#waiters.shift();
      if (!waiter) continue;
      if (line.startsWith("OK")) waiter.resolve(line.slice(2).trim());
      else waiter.reject(new Error(line.replace(/^ERR\s*/, "") || "agent error"));
    }
  }

  send(command) {
    if (!this.#socket) return Promise.reject(new Error("not connected to the ACIS agent"));
    return new Promise((resolve, reject) => {
      this.#waiters.push({ resolve, reject });
      this.#socket.write(command + "\n");
    });
  }

  close() {
    this.#socket?.end();
    this.#socket = null;
  }
}

export function satImportCode(filePath, itemId = "1") {
  return [
    "With SAT",
    "     .Reset",
    `     .FileName "${filePath}"`,
    `     .Id "${itemId}"`,
    '     .Version "9.0"',
    '     .ScaleToUnit "0"',
    '     .ImportToActiveCoordinateSystem "True"',
    '     .Curves "True"',
    "     .Read",
    "End With",
  ].join("\n");
}
