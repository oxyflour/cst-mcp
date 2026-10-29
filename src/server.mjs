#!/usr/bin/env node
/**
 * cst-mcp 鈥?Model Context Protocol server for CST Studio Suite 2022.
 *
 * Transport : Streamable HTTP (JSON-RPC over POST /mcp), stateless mode.
 * Backend   : bridge/cst_bridge.py running on CST's bundled Python 3.6, which
 *             talks to the Design Environment through the shipped `cst` package.
 *
 * The MCP layer deliberately knows nothing about CST: every tool is a thin
 * wrapper around one bridge method, so the transport can be swapped (stdio for
 * a desktop host, HTTP for remote clients) without touching the CST adapter.
 */
import http from "node:http";
import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { z } from "zod";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { AcisPipe, findModelerPid, satImportCode } from "./acis.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");

const CONFIG = {
  host: process.env.CST_MCP_HOST ?? "127.0.0.1",
  port: Number(process.env.CST_MCP_PORT ?? 8765),
  token: process.env.CST_MCP_TOKEN ?? "",
  python: process.env.CST_PYTHON ?? "C:\\Programs\\CST Studio Suite 2022\\AMD64\\python\\python.exe",
  bridge: process.env.CST_BRIDGE ?? path.join(ROOT, "bridge", "cst_bridge.py"),
  callTimeoutMs: Number(process.env.CST_CALL_TIMEOUT_MS ?? 600_000),
};

/* ------------------------------------------------------------------ bridge */

class Bridge {
  #child = null;
  #pending = new Map();
  #chain = Promise.resolve();
  #stderrTail = [];

  start() {
    if (this.#child) return;
    this.#child = spawn(CONFIG.python, ["-u", CONFIG.bridge], {
      cwd: ROOT,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    let buf = "";
    this.#child.stdout.setEncoding("utf8");
    this.#child.stdout.on("data", (chunk) => {
      buf += chunk;
      let nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line) continue;
        this.#onLine(line);
      }
    });
    this.#child.stderr.setEncoding("utf8");
    this.#child.stderr.on("data", (chunk) => {
      this.#stderrTail.push(chunk);
      if (this.#stderrTail.length > 20) this.#stderrTail.shift();
    });
    this.#child.on("exit", (code, signal) => {
      const err = new Error(
        `CST bridge exited (code=${code}, signal=${signal}). ` +
          `stderr tail: ${this.#stderrTail.join("").slice(-1500)}`,
      );
      for (const { reject, timer } of this.#pending.values()) {
        clearTimeout(timer);
        reject(err);
      }
      this.#pending.clear();
      this.#child = null;
    });
  }

  #onLine(line) {
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      return;
    }
    if (msg.id == null || !this.#pending.has(msg.id)) return;
    const { resolve, reject, timer } = this.#pending.get(msg.id);
    clearTimeout(timer);
    this.#pending.delete(msg.id);
    if (msg.ok) resolve(msg.result);
    else reject(Object.assign(new Error(msg.error?.message ?? "bridge error"), { type: msg.error?.type }));
  }

  /** Serialised call: CST is single-session, concurrent calls must not interleave. */
  call(method, params = {}) {
    const run = () => this.#rawCall(method, params);
    const result = this.#chain.then(run, run);
    this.#chain = result.then(
      () => undefined,
      () => undefined,
    );
    return result;
  }

  #rawCall(method, params) {
    this.start();
    const id = randomUUID();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.#pending.delete(id);
        reject(new Error(`bridge call ${method} timed out after ${CONFIG.callTimeoutMs} ms`));
      }, CONFIG.callTimeoutMs);
      this.#pending.set(id, { resolve, reject, timer });
      this.#child.stdin.write(JSON.stringify({ id, method, params }) + "\n");
    });
  }

  stop() {
    try {
      this.#child?.stdin.write(JSON.stringify({ id: randomUUID(), method: "shutdown", params: {} }) + "\n");
      this.#child?.kill();
    } catch {
      /* ignore */
    }
    this.#child = null;
  }
}

const bridge = new Bridge();
const acis = new AcisPipe();

/* -------------------------------------------------------------------- tools */

const text = (value) => ({
  content: [{ type: "text", text: typeof value === "string" ? value : JSON.stringify(value, null, 2) }],
});

const fail = (err) => ({
  isError: true,
  content: [{ type: "text", text: `${err.type ? `[${err.type}] ` : ""}${err.message}` }],
});

function buildServer() {
  const server = new McpServer(
    { name: "cst-mcp", version: "0.1.0" },
    {
      instructions:
        "Drives CST Studio Suite 2022 through its official automation API. " +
        "Always call cst_status first: it reports whether a Design Environment is " +
        "attached and which project is active. cst_vba executes arbitrary VBA and " +
        "changes the model irreversibly - prefer the dedicated tools and read the " +
        "history before rewriting it.",
    },
  );

  server.registerTool(
    "cst_status",
    {
      title: "CST status",
      description:
        "List running CST Design Environments (PIDs), report connection state and the active project.",
      inputSchema: {},
      annotations: { readOnlyHint: true },
    },
    async () => {
      try {
        return text(await bridge.call("de.status"));
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "cst_connect",
    {
      title: "Attach to CST",
      description:
        "Attach to a running Design Environment without starting a new one (no extra licence). " +
        "mode=any attaches to whichever DE is open; mode=pid targets a PID from cst_status.",
      inputSchema: {
        mode: z.enum(["any", "pid"]).default("any"),
        pid: z.number().int().optional().describe("Required when mode=pid"),
      },
    },
    async ({ mode, pid }) => {
      try {
        return text(await bridge.call("de.connect", { mode, pid }));
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "cst_open_project",
    {
      title: "Open project",
      description: "Open a .cst project file in the attached Design Environment and return its path.",
      inputSchema: { path: z.string().describe("Absolute path to a .cst file") },
    },
    async ({ path }) => {
      try {
        return text(await bridge.call("project.open", { path }));
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "cst_vba",
    {
      title: "Run VBA",
      description:
        "Execute a VBA snippet as one new history block in the active 3D project (or schematic). " +
        "This is the universal escape hatch over the documented macro language: creating " +
        "solids, materials, ports, monitors, solver settings and result templates all go " +
        "through it. Keep snippets idempotent and let CST name objects explicitly.",
      inputSchema: {
        code: z.string().describe("VBA source, e.g. 'With Brick ... End With'"),
        header: z.string().default("mcp").describe("History block label shown in the model tree"),
        timeout: z.number().int().optional().describe("Seconds to wait for the call"),
      },
    },
    async ({ code, header, timeout }) => {
      try {
        return text(await bridge.call("vba.run", { code, header, timeout }));
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "cst_solve",
    {
      title: "Start solver",
      description:
        "Start the currently selected solver asynchronously and return immediately. " +
        "Poll cst_solver_state for progress; call cst_abort_solver to stop it.",
      inputSchema: {},
    },
    async () => {
      try {
        return text(await bridge.call("solver.start"));
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "cst_solver_state",
    {
      title: "Solver state",
      description: "Report whether a solver is running and which one.",
      inputSchema: {},
      annotations: { readOnlyHint: true },
    },
    async () => {
      try {
        return text(await bridge.call("solver.state"));
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "cst_abort_solver",
    {
      title: "Abort solver",
      description: "Abort the running or paused solver.",
      inputSchema: {},
      annotations: { idempotentHint: true },
    },
    async () => {
      try {
        return text(await bridge.call("solver.abort"));
      } catch (err) {
        return fail(err);
      }
    },
  );

  /* ---------------------------------------------------------------- ACIS --
   * These talk to cst_acis_agent.dll living inside modeler_AMD64.exe, not to
   * the Design Environment. Everything they create is real ACIS geometry built
   * with CST's own kernel and licence; `acis_import_sat` then hands the result
   * back to CST through the SAT reader.
   */

  server.registerTool(
    "cst_import_step",
    {
      title: "Import STEP",
      description:
        "Read a STEP (.stp/.step) file into the active CST project. Uses CST's own CAD translator, " +
        "so the geometry becomes a normal CST solid. Needs cst_connect first.",
      inputSchema: {
        path: z.string().describe("Absolute path to a .stp/.step file"),
        toActiveCs: z.boolean().default(true),
      },
    },
    async ({ path, toActiveCs }) => {
      try {
        const code = [
          "With STEP",
          "     .Reset",
          `     .FileName "${path}"`,
          `     .ImportToActiveCoordinateSystem "${toActiveCs ? "True" : "False"}"`,
          "     .Read",
          "End With",
        ].join("\n");
        return text(await bridge.call("vba.run", { header: "step_import", code }));
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "cst_local_modify",
    {
      title: "Push/pull a face",
      description:
        "Direct modelling on an existing solid: pick one face by id and push/pull it. " +
        "op=offset moves the face along its normal (the usual push/pull); op=move translates it. " +
        "CST adjusts adjacent faces so the solid stays closed, and can detach/reapply surrounding " +
        "blends. Face ids can change after an edit, re-query before chaining operations.",
      inputSchema: {
        shape: z.string().describe('Solid reference, e.g. "component1:solid1"'),
        faceId: z.number().int().min(0),
        op: z.enum(["offset", "move"]).default("offset"),
        amount: z.number().default(1).describe("Offset distance along the face normal (op=offset)"),
        dx: z.number().default(0),
        dy: z.number().default(0),
        dz: z.number().default(0),
        considerBlends: z.boolean().default(false).describe("Detach and reapply adjacent blends"),
        removeInverted: z.boolean().default(true),
      },
    },
    async ({ shape, faceId, op, amount, dx, dy, dz, considerBlends, removeInverted }) => {
      try {
        const action =
          op === "offset"
            ? `     .OffsetSelectedFaces "${amount}"`
            : `     .MoveSelectedFaces "${dx}", "${dy}", "${dz}"`;
        const code = [
          `Pick.PickFaceFromId "${shape}", "${faceId}"`,
          "With LocalModification",
          "     .Reset",
          `     .Name "${shape}"`,
          `     .EnableInvertedFaceRemoval "${removeInverted ? "True" : "False"}"`,
          `     .SetConsiderBlends "${considerBlends ? "True" : "False"}"`,
          action,
          "End With",
        ].join("\n");
        return text(await bridge.call("vba.run", { header: "local_modify", code }));
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "cst_export_sat",
    {
      title: "Export SAT",
      description:
        "Write the whole CST model to a SAT file via CST's own writer (SAT.WriteAll). " +
        "Needs cst_connect first.",
      inputSchema: {
        path: z.string().describe("Absolute path ending in .sat"),
        fromActiveCs: z.boolean().default(false),
      },
    },
    async ({ path, fromActiveCs }) => {
      try {
        const code = [
          "With SAT",
          "     .Reset",
          `     .FileName "${path}"`,
          `     .ExportFromActiveCoordinateSystem (${fromActiveCs ? "True" : "False"})`,
          "     .WriteAll",
          "End With",
        ].join("\n");
        return text(await bridge.call("vba.run", { header: "sat_export", code }));
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "acis_connect",
    {
      title: "Attach to the ACIS agent",
      description:
        "Connect to the in-process ACIS agent inside modeler_AMD64.exe. The agent must have been injected " +
        "beforehand (native/inject.ps1 -Dll cst_acis_agent.dll). Omit pid to pick the running modeler.",
      inputSchema: { pid: z.number().int().optional() },
    },
    async ({ pid }) => {
      try {
        const target = pid ?? (await findModelerPid());
        await acis.connect(target);
        return text(await acis.send("ping").then((r) => ({ pid: target, reply: r })));
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "acis_block",
    {
      title: "Create a box with ACIS",
      description:
        "Build a solid box from the origin using the ACIS kernel inside CST. Returns the face count.",
      inputSchema: {
        lx: z.number().positive().default(10),
        ly: z.number().positive().default(10),
        lz: z.number().positive().default(10),
      },
    },
    async ({ lx, ly, lz }) => {
      try {
        return text(await acis.send(`block ${lx} ${ly} ${lz}`));
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "acis_offset_face",
    {
      title: "Offset a face",
      description:
        "Offset face <index> of the current body by <distance> and return the new body's face count. " +
        "This is the push/pull operation VBA cannot express directly. Call acis_block first.",
      inputSchema: {
        index: z.number().int().min(0).default(0),
        distance: z.number().default(2),
      },
    },
    async ({ index, distance }) => {
      try {
        return text(await acis.send(`offset ${index} ${distance}`));
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "acis_export_sat",
    {
      title: "Write SAT",
      description:
        "Write the current body (the offset result if there is one) to a SAT file. " +
        "Use acis_import_sat to bring it into the CST project.",
      inputSchema: {
        path: z.string().describe("Absolute path ending in .sat"),
        which: z.enum(["main", "last"]).default("last").describe("main = the body from acis_block, last = the offset result"),
      },
    },
    async ({ path, which }) => {
      try {
        return text(await acis.send(`save ${which === "main" ? "main " : ""}${path}`));
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "acis_import_sat",
    {
      title: "Import SAT into CST",
      description:
        "Run CST's SAT reader on the given file so the geometry appears in the project tree. " +
        "Needs a Design Environment connection (cst_connect) for the VBA channel.",
      inputSchema: {
        path: z.string().describe("Absolute path of a .sat file"),
        id: z.string().default("1"),
      },
    },
    async ({ path, id }) => {
      try {
        return text(
          await bridge.call("vba.run", {
            header: "sat_import",
            code: satImportCode(path, id),
          }),
        );
      } catch (err) {
        return fail(err);
      }
    },
  );

  return server;
}

/* ----------------------------------------------------------------- transport */

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      const raw = Buffer.concat(chunks).toString("utf8");
      if (!raw) return resolve(undefined);
      try {
        resolve(JSON.parse(raw));
      } catch (err) {
        reject(err);
      }
    });
    req.on("error", reject);
  });
}

function sendJson(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, { "content-type": "application/json", "content-length": Buffer.byteLength(body) });
  res.end(body);
}

const httpServer = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host ?? "localhost"}`);

  if (url.pathname === "/health") {
    return sendJson(res, 200, { ok: true, tools: 12 });
  }

  if (url.pathname !== "/mcp") {
    return sendJson(res, 404, { error: "not found" });
  }

  if (CONFIG.token) {
    const auth = req.headers.authorization ?? "";
    if (auth !== `Bearer ${CONFIG.token}`) {
      return sendJson(res, 401, { error: "unauthorized" });
    }
  }

  if (req.method !== "POST") {
    // Stateless server: no SSE stream to resume, no session to delete.
    res.writeHead(405, { allow: "POST" });
    return res.end();
  }

  let body;
  try {
    body = await readBody(req);
  } catch {
    return sendJson(res, 400, { jsonrpc: "2.0", error: { code: -32700, message: "parse error" }, id: null });
  }

  const server = buildServer();
  const transport = new StreamableHTTPServerTransport({
    sessionIdGenerator: undefined,
    enableJsonResponse: true,
  });
  res.on("close", () => {
    transport.close().catch(() => {});
    server.close().catch(() => {});
  });

  try {
    await server.connect(transport);
    await transport.handleRequest(req, res, body);
  } catch (err) {
    console.error("[cst-mcp] request failed:", err);
    if (!res.headersSent) sendJson(res, 500, { jsonrpc: "2.0", error: { code: -32603, message: String(err) }, id: null });
  }
});

httpServer.listen(CONFIG.port, CONFIG.host, () => {
  console.log(`[cst-mcp] listening on http://${CONFIG.host}:${CONFIG.port}/mcp`);
  console.log(`[cst-mcp] bridge python: ${CONFIG.python}`);
});

const shutdown = () => {
  bridge.stop();
  httpServer.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 1500).unref();
};
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

