/** Notification-only OpenCode V1 bridge. No transcript reads, model calls or startup. */
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { accessSync, constants } from "node:fs";
import { homedir } from "node:os";
import { isAbsolute, join } from "node:path";

const MAX_INPUT = 65_536;
const MAX_SESSIONS = 128;
const MAX_PARTS = 32;
const MAX_REQUESTS = 64;
const MAX_PENDING = 16;
const HOOK_TIMEOUT_MS = 500;
const LOOKUP_TIMEOUT_MS = 300;
const CLOSE_TIMEOUT_MS = 1_500;
const SESSION_TTL_MS = 3_600_000;
type Outcome = "completed" | "error" | "aborted";

export interface Notification {
  hook_event_name: "agent_start" | "agent_settled" | "permission_asked" | "question_asked";
  session_id: string;
  turn_id: string;
  outcome?: Outcome;
  last_assistant_message?: string;
  request_id?: string;
}

export interface Transport {
  send(event: Notification): boolean;
  cancelAttention?(session: string, turn: string, request: string): void;
  close(): Promise<void>;
}

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function validString(value: unknown, bytes = 256): value is string {
  return typeof value === "string" && value.length <= bytes && Boolean(value.trim())
    && Buffer.byteLength(value, "utf8") <= bytes && Buffer.from(value, "utf8").toString("utf8") === value;
}

function encode(event: Notification): string | undefined {
  const data = JSON.stringify(event) + "\n";
  return Buffer.byteLength(data, "utf8") <= MAX_INPUT ? data : undefined;
}

/** Explicit overrides are authoritative; missing services never launch installers. */
export function resolveExecutable(env: NodeJS.ProcessEnv = process.env): string | undefined {
  if (env.AWAITONAL_EXECUTABLE !== undefined) {
    return isAbsolute(env.AWAITONAL_EXECUTABLE) ? env.AWAITONAL_EXECUTABLE : undefined;
  }
  const runtime = env.AWAITONAL_PLUGIN_RUNTIME ??
    join(env.XDG_DATA_HOME ?? join(env.HOME ?? homedir(), ".local", "share"), "awaitonal", "plugin");
  if (!isAbsolute(runtime)) return undefined;
  const executable = join(runtime, "bin", "awaitonal");
  try { accessSync(executable, constants.X_OK); return executable; }
  catch { return "awaitonal"; }
}

/** Serialize stdin delivery without making any OpenCode hook wait for playback. */
export function createTransport(env: NodeJS.ProcessEnv = process.env): Transport {
  const pending: { event: Notification; data: string }[] = [];
  const settlements = new Set<string>();
  let active: ReturnType<typeof spawn> | undefined;
  let closing = false;
  let closed = false;
  let closePromise: Promise<void> | undefined;
  let drained: (() => void) | undefined;
  function next(): void {
    if (closed || active) return;
    const item = pending.shift();
    if (!item) { drained?.(); return; }
    const executable = resolveExecutable(env);
    if (!executable) { pending.length = 0; drained?.(); return; }
    let child: ReturnType<typeof spawn>;
    try {
      child = spawn(executable, ["hook", "opencode"], {
        env, shell: false, stdio: ["pipe", "ignore", "ignore"], windowsHide: true,
      });
    } catch { queueMicrotask(next); return; }
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
    const timer = setTimeout(() => { child.kill("SIGKILL"); finish(); }, HOOK_TIMEOUT_MS);
    timer.unref();
    child.once("error", finish);
    child.once("close", finish);
    child.stdin?.on("error", () => {});
    child.stdin?.end(item.data);
    child.unref();
  }
  return {
    send(event) {
      if (closing || closed) return false;
      const data = encode(event);
      if (data === undefined) return false;
      const turn = `${event.session_id}\0${event.turn_id}`;
      // Settlement cancels unsent attention for this activity and must have a
      // reserved slot after every admitted start, even under a noisy event burst.
      if (event.hook_event_name === "agent_settled") {
        settlements.delete(turn);
        for (let i = pending.length - 1; i >= 0; i--) {
          const previous = pending[i].event;
          if (previous.session_id === event.session_id && previous.turn_id === event.turn_id
              && previous.hook_event_name !== "agent_start") pending.splice(i, 1);
        }
      }
      const budget = pending.length + Number(Boolean(active)) + settlements.size;
      if (event.hook_event_name === "agent_start") {
        if (settlements.has(turn) || budget + 2 > MAX_PENDING) return false;
        settlements.add(turn);
      } else if (budget + 1 > MAX_PENDING) return false;
      pending.push({ event, data }); next(); return true;
    },
    cancelAttention(session, turn, request) {
      for (let i = pending.length - 1; i >= 0; i--) {
        const event = pending[i].event;
        if (event.session_id === session && event.turn_id === turn && event.request_id === request) pending.splice(i, 1);
      }
    },
    close() {
      if (closePromise) return closePromise;
      closing = true;
      closePromise = new Promise<void>((resolve) => {
        const finish = () => {
          clearTimeout(timer); closed = true; pending.length = 0; settlements.clear();
          active?.stdin?.destroy(); active?.kill("SIGKILL"); active = undefined;
          drained = undefined; resolve();
        };
        const timer = setTimeout(finish, CLOSE_TIMEOUT_MS);
        drained = finish;
        if (!active && !pending.length) finish();
      });
      return closePromise;
    },
  };
}

interface Assistant {
  id: string;
  parent: string;
  completed: boolean;
  finish: string;
  parts: Map<string, string>;
  bytes: number;
  invalid: boolean;
  tools: boolean;
  outcome?: Outcome;
}
interface Activity {
  turn: string;
  sent: boolean;
  attempted: boolean;
  timed: boolean;
  assistant?: Assistant;
  error?: Outcome;
  requests: Map<string, string>;
}
interface Session {
  root?: boolean;
  lookup?: AbortController;
  touched: number;
  user?: string;
  activity?: Activity;
}
interface Options {
  getSession(id: string, signal: AbortSignal): Promise<unknown>;
  transport?: Transport;
  env?: NodeJS.ProcessEnv;
  now?: () => number;
}

function errorOutcome(error: unknown): Outcome | undefined {
  if (!object(error) || !validString(error.name, 128)) return undefined;
  return error.name === "MessageAbortedError" ? "aborted" : "error";
}

/** State changes are synchronous: V1 dispatches event callbacks without awaiting them. */
export function createOpenCodeBridge(options: Options) {
  const transport = options.transport ?? createTransport(options.env);
  const now = options.now ?? Date.now;
  const sessions = new Map<string, Session>();
  let disposed = false;

  function sendStart(id: string, session: Session): void {
    const activity = session.activity;
    if (session.root === true && activity && !activity.attempted) {
      activity.attempted = true;
      // A resumed session verified after busy has already spent time running.
      // Keep its cues but omit a late start: the service then uses unknown timing.
      activity.sent = !activity.timed || transport.send({ hook_event_name: "agent_start", session_id: id, turn_id: activity.turn });
    }
  }
  function settle(id: string, session: Session, forced?: Outcome): void {
    const activity = session.activity;
    session.activity = undefined;
    if (!activity?.sent || session.root !== true) return;
    const assistant = activity.assistant;
    const completed = assistant?.completed && !assistant.invalid && !assistant.tools
      && (!session.user || assistant.parent === session.user)
      && ["stop", "length"].includes(assistant.finish);
    const outcome = forced ?? activity.error ?? assistant?.outcome ?? (completed ? "completed" : "aborted");
    const event: Notification = {
      hook_event_name: "agent_settled", session_id: id, turn_id: activity.turn, outcome,
    };
    if (outcome === "completed") {
      event.last_assistant_message = [...assistant!.parts.values()].join("\n");
      if (encode(event) === undefined) { event.outcome = "aborted"; delete event.last_assistant_message; }
    }
    transport.send(event);
  }
  function forget(id: string, session: Session): void {
    settle(id, session, "aborted"); session.lookup?.abort(); sessions.delete(id);
  }
  function get(id: string): Session {
    const time = now();
    for (const [key, session] of sessions) {
      if (time - session.touched >= SESSION_TTL_MS) forget(key, session);
    }
    let session = sessions.get(id);
    if (!session) {
      while (sessions.size >= MAX_SESSIONS) {
        const [key, oldest] = sessions.entries().next().value!;
        forget(key, oldest);
      }
      session = { touched: time }; sessions.set(id, session);
    }
    session.touched = time;
    sessions.delete(id); sessions.set(id, session);
    return session;
  }
  function verify(id: string, session: Session): void {
    if (session.root !== undefined || session.lookup) return;
    const controller = new AbortController(); session.lookup = controller;
    const timer = setTimeout(() => controller.abort(), LOOKUP_TIMEOUT_MS); timer.unref();
    // Abort plus identity checks also contain clients that ignore AbortSignal.
    void Promise.resolve().then(() => options.getSession(id, controller.signal)).then((info) => {
      if (disposed || controller.signal.aborted || sessions.get(id) !== session || session.root !== undefined) return;
      if (object(info) && info.id === id) {
        session.root = info.parentID === undefined;
        if (session.root) sendStart(id, session);
        else session.activity = undefined;
      }
    }).catch(() => {}).finally(() => {
      clearTimeout(timer);
      if (session.lookup === controller) session.lookup = undefined;
    });
  }
  function updateInfo(info: Record<string, unknown>): void {
    if (!validString(info.id)) return;
    const session = get(info.id);
    const root = info.parentID === undefined;
    if (!root && session.activity?.sent) settle(info.id, session, "aborted");
    session.root = root; session.lookup?.abort();
    if (root) sendStart(info.id, session);
    else session.activity = undefined;
  }
  function attention(type: "permission_asked" | "question_asked", p: Record<string, unknown>, session: Session): void {
    const activity = session.activity;
    if (!activity?.sent || session.root !== true || !validString(p.id)) return;
    if (p.tool !== undefined && (!object(p.tool) || p.tool.messageID !== activity.assistant?.id)) return;
    if (type === "permission_asked" && !validString(p.permission, 128)) return;
    if (type === "question_asked" && (!Array.isArray(p.questions) || !p.questions.length
        || p.questions.length > 32 || !p.questions.every((q) => object(q) && validString(q.question, 8192)))) return;
    const key = `${type}:${p.id}`;
    if (activity.requests.has(key) || activity.requests.size >= MAX_REQUESTS) return;
    const request = randomUUID(); activity.requests.set(key, request);
    transport.send({ hook_event_name: type, session_id: p.sessionID as string,
                     turn_id: activity.turn, request_id: request });
  }
  function receive(event: unknown): void {
    if (disposed || !object(event) || !object(event.properties)) return;
    const p = event.properties;
    if ((event.type === "session.created" || event.type === "session.updated") && object(p.info)) {
      updateInfo(p.info); return;
    }
    if (event.type === "session.deleted" && object(p.info) && validString(p.info.id)) {
      const session = sessions.get(p.info.id); if (session) forget(p.info.id, session); return;
    }
    const info = event.type === "message.updated" && object(p.info) ? p.info : undefined;
    const part = event.type === "message.part.updated" && object(p.part) ? p.part : undefined;
    const id = p.sessionID ?? info?.sessionID ?? part?.sessionID;
    if (!validString(id)) return;
    // Unrelated stream events cannot allocate session state or trigger lookups.
    if (!sessions.has(id) && !["session.status", "message.updated"].includes(String(event.type))) return;
    const session = get(id);
    if (info?.role === "user" && validString(info.id)) {
      if (session.user !== info.id && session.activity) {
        session.activity.assistant = undefined; session.activity.error = undefined;
      }
      session.user = info.id; return;
    }
    if (event.type === "session.status" && object(p.status)) {
      if (p.status.type === "idle") { settle(id, session); return; }
      if (p.status.type !== "busy" && p.status.type !== "retry") return;
      if (session.root === false) return;
      session.activity ??= { turn: randomUUID(), sent: false, attempted: false,
        timed: session.root === true, requests: new Map() };
      if (p.status.type === "retry") {
        const assistant = session.activity.assistant;
        if (assistant) {
          assistant.parts.clear(); assistant.bytes = 0; assistant.finish = "";
          assistant.completed = false; assistant.outcome = undefined;
          assistant.tools = false; assistant.invalid = false;
        }
        session.activity.error = undefined;
      }
      verify(id, session); sendStart(id, session); return;
    }
    const activity = session.activity;
    if (!activity || session.root === false) return;
    if (event.type === "session.error") {
      activity.error = errorOutcome(p.error); return;
    }
    if (event.type === "session.compacted") { activity.assistant = undefined; activity.error = undefined; return; }
    if (event.type === "permission.asked" || event.type === "question.asked") {
      attention(event.type === "permission.asked" ? "permission_asked" : "question_asked", p, session); return;
    }
    if (["permission.replied", "question.replied", "question.rejected"].includes(String(event.type)) && validString(p.requestID)) {
      const kind = event.type === "permission.replied" ? "permission_asked" : "question_asked";
      const request = activity.requests.get(`${kind}:${p.requestID}`);
      if (request) transport.cancelAttention?.(id, activity.turn, request);
      return;
    }
    if (info?.role === "assistant" && validString(info.id) && validString(info.parentID) && object(info.time)) {
      if (info.summary === true) {
        activity.assistant = undefined;
        // A failed compaction can stop with an error on summary metadata only.
        // Keep the generic outcome until idle or a later fresh model step.
        activity.error = errorOutcome(info.error); return;
      }
      if (session.user && info.parentID !== session.user) return;
      if (activity.assistant?.id !== info.id) {
        // Historical updates, compaction/pruning, and a missed live start do
        // not establish a fresh completion. Only follow a new running message.
        if (info.time.completed !== undefined) return;
        activity.assistant = { id: info.id, parent: info.parentID, completed: false,
          finish: "", parts: new Map(), bytes: 0, invalid: false, tools: false };
        activity.error = undefined;
      }
      const assistant = activity.assistant;
      assistant.completed = typeof info.time.completed === "number" && Number.isFinite(info.time.completed);
      assistant.outcome = errorOutcome(info.error);
      return;
    }
    const assistant = activity.assistant;
    if (event.type === "message.removed" && p.messageID === assistant?.id) { activity.assistant = undefined; return; }
    if (event.type === "message.part.removed" && p.messageID === assistant?.id) { assistant!.invalid = true; return; }
    if (!part || !assistant || part.messageID !== assistant.id) return;
    // Full-value updates can retract or exclude previously completed text.
    // Never retain the earlier value after its part stops being usable text.
    if (validString(part.id) && assistant.parts.has(part.id)
        && (part.type !== "text" || part.synthetic === true || part.ignored === true
          || !object(part.time) || typeof part.time.end !== "number" || !Number.isFinite(part.time.end))) {
      assistant.invalid = true; assistant.parts.clear(); assistant.bytes = 0; return;
    }
    if (part.type === "step-start") {
      assistant.parts.clear(); assistant.bytes = 0; assistant.finish = "";
      assistant.completed = false; assistant.outcome = undefined;
      assistant.tools = false; assistant.invalid = false; activity.error = undefined; return;
    }
    if (part.type === "step-finish") {
      assistant.finish = validString(part.reason, 128) ? part.reason : ""; return;
    }
    if (part.type === "tool" && !(object(part.metadata) && part.metadata.providerExecuted === true)) {
      assistant.tools = true; return;
    }
    if (part.type !== "text" || part.synthetic === true || part.ignored === true || !validString(part.id)) return;
    // Streaming deltas, reasoning and tool output are never buffered. A text
    // part's full-value completion is published after text-complete transforms.
    if (!object(part.time) || typeof part.time.end !== "number" || !Number.isFinite(part.time.end)) return;
    if (typeof part.text !== "string" || part.text.length > MAX_INPUT
        || Buffer.from(part.text, "utf8").toString("utf8") !== part.text) { assistant.invalid = true; return; }
    const bytes = assistant.bytes - Buffer.byteLength(assistant.parts.get(part.id) ?? "", "utf8")
      + Buffer.byteLength(part.text, "utf8");
    if (bytes > MAX_INPUT || !assistant.parts.has(part.id) && assistant.parts.size >= MAX_PARTS) {
      assistant.invalid = true; assistant.parts.clear(); assistant.bytes = 0; return;
    }
    assistant.parts.set(part.id, part.text); assistant.bytes = bytes;
  }
  return {
    event: async ({ event }: { event: unknown }): Promise<void> => { receive(event); },
    "experimental.session.compacting": async ({ sessionID }: { sessionID: string }): Promise<void> => {
      const activity = sessions.get(sessionID)?.activity;
      if (activity) { activity.assistant = undefined; activity.error = undefined; }
    },
    dispose: async (): Promise<void> => {
      if (disposed) return;
      disposed = true;
      for (const [id, session] of sessions) forget(id, session);
      await transport.close();
    },
  };
}
