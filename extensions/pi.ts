/** Notification-only Pi bridge. No model, transcript, or service startup on hooks. */
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { accessSync, constants } from "node:fs";
import { homedir } from "node:os";
import { dirname, isAbsolute, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const MAX_INPUT = 65_536;
const MAX_PENDING = 16;
const HOOK_TIMEOUT_MS = 500;
const CLOSE_TIMEOUT_MS = 1_500;
const PACKAGE_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
type Outcome = "completed" | "error" | "aborted";

export interface Notification {
  hook_event_name: "agent_start" | "agent_settled" | "ui_prompt_start";
  session_id: string;
  turn_id: string;
  outcome?: Outcome;
  last_assistant_message?: string;
  request_id?: string;
}

export interface Transport {
  send(event: Notification): void;
  close(): Promise<void>;
}

/** A configured override is authoritative: never silently run another binary. */
export function resolveExecutable(env: NodeJS.ProcessEnv = process.env): string | undefined {
  if (env.AWAITONAL_EXECUTABLE !== undefined) {
    return isAbsolute(env.AWAITONAL_EXECUTABLE) ? env.AWAITONAL_EXECUTABLE : undefined;
  }
  const runtime = env.AWAITONAL_PLUGIN_RUNTIME ??
    join(env.XDG_DATA_HOME ?? join(env.HOME ?? homedir(), ".local", "share"), "awaitonal", "plugin");
  if (!isAbsolute(runtime)) return undefined;
  const executable = join(runtime, "bin", "awaitonal");
  try {
    accessSync(executable, constants.X_OK);
    return executable;
  } catch {
    return "awaitonal"; // Let spawn search PATH; there is no shell or installer.
  }
}

function encode(event: Notification): string | undefined {
  const data = JSON.stringify(event) + "\n";
  return Buffer.byteLength(data, "utf8") <= MAX_INPUT ? data : undefined;
}

/** Bound both queue memory and child lifetime; Pi hooks never wait for this queue. */
export function createTransport(env: NodeJS.ProcessEnv = process.env): Transport {
  const pending: string[] = [];
  let active: ReturnType<typeof spawn> | undefined;
  let closing = false;
  let closed = false;
  let onDrained: (() => void) | undefined;
  let closingPromise: Promise<void> | undefined;

  function next(): void {
    if (closed || active) return;
    const data = pending.shift();
    if (data === undefined) {
      onDrained?.();
      return;
    }
    const executable = resolveExecutable(env);
    if (!executable) {
      pending.length = 0;
      onDrained?.();
      return;
    }
    let child: ReturnType<typeof spawn>;
    try {
      child = spawn(executable, ["hook", "pi"], {
        env, shell: false, stdio: ["pipe", "ignore", "ignore"], windowsHide: true,
      });
    } catch {
      queueMicrotask(next);
      return;
    }
    active = child;
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      child.stdin?.destroy();
      if (active === child) active = undefined;
      next();
    };
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      finish();
    }, HOOK_TIMEOUT_MS);
    timer.unref();
    child.once("error", finish);
    child.once("close", finish);
    child.stdin?.on("error", () => {}); // Missing services and early child exits are quiet.
    child.stdin?.end(data);
    child.unref();
  }

  return {
    send(event) {
      if (closing || closed || pending.length + Number(Boolean(active)) >= MAX_PENDING) return;
      const data = encode(event);
      if (data !== undefined) {
        pending.push(data);
        next();
      }
    },
    close() {
      if (closingPromise) return closingPromise;
      closing = true;
      // Print mode may shut down immediately after settlement. Give its final
      // notification a bounded chance to leave stdin before disposing resources.
      closingPromise = new Promise<void>((resolve) => {
        const finish = () => {
          clearTimeout(timer);
          closed = true;
          pending.length = 0;
          active?.stdin?.destroy();
          active?.kill("SIGKILL");
          active = undefined;
          onDrained = undefined;
          resolve();
        };
        const timer = setTimeout(finish, CLOSE_TIMEOUT_MS);
        onDrained = finish;
        if (!active && pending.length === 0) finish();
      });
      return closingPromise;
    },
  };
}

function validId(value: unknown): value is string {
  return typeof value === "string" && Boolean(value.trim()) && validUnicode(value)
    && Buffer.byteLength(value, "utf8") <= 256;
}

function validUnicode(value: string): boolean {
  return Buffer.from(value, "utf8").toString("utf8") === value;
}

function sessionId(ctx: ExtensionContext): string | undefined {
  try {
    const id = ctx.sessionManager.getSessionId();
    return validId(id) ? id : undefined;
  } catch {
    return undefined;
  }
}

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object";
}

interface AssistantSnapshot { outcome: Outcome; text: string }

function assistantSnapshot(message: unknown): AssistantSnapshot | undefined {
  if (!object(message) || message.role !== "assistant") return undefined;
  if (message.stopReason === "error" || message.stopReason === "aborted") {
    return { outcome: message.stopReason, text: "" };
  }
  if (!["stop", "length", "toolUse"].includes(String(message.stopReason)) || !Array.isArray(message.content)) {
    return undefined;
  }
  const chunks: string[] = [];
  let bytes = 0;
  for (const block of message.content) {
    if (!object(block) || block.type !== "text" || typeof block.text !== "string") continue;
    if (!validUnicode(block.text)) return { outcome: "completed", text: "" };
    bytes += Buffer.byteLength(block.text, "utf8") + 1;
    if (bytes > MAX_INPUT) return { outcome: "completed", text: "" };
    chunks.push(block.text);
  }
  return { outcome: "completed", text: chunks.join("\n") };
}

interface Activity {
  session: string;
  turn: string;
  latest?: AssistantSnapshot;
  outcome?: Outcome;
}

export interface CommandResult { ok: boolean; stdout: string }

/** Explicit slash commands may wait; captured output and total runtime are bounded. */
export function runCommand(executable: string, args: string[], timeout: number,
                           env: NodeJS.ProcessEnv = process.env): Promise<CommandResult> {
  return new Promise((resolve) => {
    let stdout = "";
    let bytes = 0;
    let child: ReturnType<typeof spawn>;
    try {
      child = spawn(executable, args, { env, shell: false, stdio: ["ignore", "pipe", "ignore"],
                                        windowsHide: true, detached: process.platform !== "win32" });
    } catch {
      resolve({ ok: false, stdout: "" });
      return;
    }
    let finished = false;
    const finish = (ok: boolean) => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      resolve({ ok, stdout });
    };
    const timer = setTimeout(() => {
      // Setup can spawn uv/pip children. Terminate only this command's own group.
      try {
        if (process.platform !== "win32" && child.pid) process.kill(-child.pid, "SIGKILL");
        else child.kill("SIGKILL");
      } catch { child.kill("SIGKILL"); }
      finish(false);
    }, timeout);
    child.once("error", () => finish(false));
    child.once("close", (code) => finish(code === 0));
    child.stdout?.on("data", (data: Buffer) => {
      bytes += data.length;
      if (bytes <= 16_384) stdout += data.toString("utf8");
    });
  });
}

interface BridgeOptions {
  transport?: Transport;
  env?: NodeJS.ProcessEnv;
  command?: typeof runCommand;
}

export function registerAwaitonal(pi: ExtensionAPI, options: BridgeOptions = {}): void {
  const env = options.env ?? process.env;
  const transport = options.transport ?? createTransport(env);
  const command = options.command ?? runCommand;
  let activity: Activity | undefined;
  let disposed = false;
  let setupRunning = false;

  function settle(forced?: Outcome): void {
    if (!activity) return;
    const current = activity;
    activity = undefined;
    // Pi can skip agent_before_settle when canceled during retry backoff or
    // compaction. A previous assistant message is not an authoritative outcome
    // for that activity: close its timing quietly rather than replaying it.
    const outcome = forced ?? current.outcome ?? "aborted";
    const event: Notification = {
      hook_event_name: "agent_settled", session_id: current.session, turn_id: current.turn, outcome,
    };
    if (outcome === "completed") {
      event.last_assistant_message = current.latest?.outcome === "completed" ? current.latest.text : "";
      // JSON escaping and envelope overhead also count toward the stdin limit.
      if (encode(event) === undefined) event.last_assistant_message = "";
    }
    transport.send(event);
  }

  function current(ctx: ExtensionContext): Activity | undefined {
    return !disposed && activity?.session === sessionId(ctx) ? activity : undefined;
  }

  pi.on("session_start", () => { settle("aborted"); });
  pi.on("session_shutdown", async () => {
    settle("aborted");
    disposed = true;
    await transport.close();
  });
  pi.on("agent_start", (_event, ctx) => {
    if (disposed) return;
    const session = sessionId(ctx);
    if (!session) return;
    if (activity && activity.session !== session) settle("aborted");
    if (!activity) {
      activity = { session, turn: randomUUID() };
      transport.send({ hook_event_name: "agent_start", session_id: session, turn_id: activity.turn });
    } else {
      // Retry/compaction/continuation retains timing but cannot reuse earlier prose.
      activity.latest = undefined;
      activity.outcome = undefined;
    }
  });
  pi.on("message_start", (event, ctx) => {
    const active = current(ctx);
    if (active && event.message?.role === "assistant") {
      active.latest = undefined;
      active.outcome = undefined;
    }
  });
  pi.on("message_end", (event, ctx) => {
    const active = current(ctx);
    if (active && event.message?.role === "assistant") {
      active.latest = assistantSnapshot(event.message);
      active.outcome = undefined;
    }
  });
  pi.on("agent_before_settle", (event, ctx) => {
    const active = current(ctx);
    if (active) active.outcome = ["completed", "aborted", "error"].includes(event.outcome) ? event.outcome : undefined;
  });
  pi.on("agent_settled", (_event, ctx) => { if (current(ctx)) settle(); });
  pi.on("ui_prompt_start", (event, ctx) => {
    const active = current(ctx);
    if (!active || !["select", "confirm", "input", "editor", "custom"].includes(event.kind)) return;
    transport.send({ hook_event_name: "ui_prompt_start", session_id: active.session,
                     turn_id: active.turn, request_id: randomUUID() });
  });

  for (const action of ["setup", "mute", "unmute", "status"] as const) {
    pi.registerCommand(`awaitonal-${action}`, {
      description: action === "setup" ? "Install Awaitonal's local runtime and start its shared service" :
        `${action === "status" ? "Check" : action === "mute" ? "Mute" : "Unmute"} the shared Awaitonal service`,
      handler: async (args, ctx) => {
        if (args.trim()) { ctx.ui.notify(`/awaitonal-${action} takes no arguments.`, "warning"); return; }
        if (disposed) return;
        if (action === "setup") {
          if (setupRunning) { ctx.ui.notify("Awaitonal setup is already running.", "info"); return; }
          setupRunning = true;
          ctx.ui.notify("Installing Awaitonal's local runtime and starting the shared service…", "info");
          try {
            const result = await command("sh", [join(PACKAGE_ROOT, "scripts", "plugin-runtime.sh"),
                                                 "setup", "--adapter", "pi"], 180_000, env);
            if (!disposed) ctx.ui.notify(result.ok ? "Awaitonal is ready. Notifications remain local." :
              "Awaitonal setup failed or timed out. Run scripts/plugin-runtime.sh setup --adapter pi to inspect setup output.",
              result.ok ? "info" : "warning");
          } finally { setupRunning = false; }
          return;
        }
        const executable = resolveExecutable(env);
        if (!executable) { ctx.ui.notify("AWAITONAL_EXECUTABLE must be an absolute path.", "warning"); return; }
        const result = await command(executable, ["service", action], 2_000, env);
        if (disposed) return;
        if (!result.ok) {
          ctx.ui.notify("Awaitonal could not reach its service. Run /awaitonal-setup to set it up.", "warning");
        } else if (action === "status") {
          try {
            const status = JSON.parse(result.stdout);
            ctx.ui.notify(status.status === "running" ?
              `Awaitonal is running${status.muted === true ? " (muted)" : ""}.` : "Awaitonal is stopped.", "info");
          } catch { ctx.ui.notify("Awaitonal returned an unreadable status.", "warning"); }
        } else {
          ctx.ui.notify(`Awaitonal ${action === "mute" ? "muted" : "unmuted"} for all sessions sharing this service.`, "info");
        }
      },
    });
  }
}

export default function awaitonal(pi: ExtensionAPI): void { registerAwaitonal(pi); }
