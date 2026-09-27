import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { performance } from "node:perf_hooks";
import test from "node:test";
import { createTransport, registerAwaitonal, resolveExecutable, runCommand } from "../extensions/pi.ts";

function harness(options = {}) {
  const handlers = new Map();
  const commands = new Map();
  const events = [];
  const notices = [];
  const calls = [];
  let session = "session-a";
  let closes = 0;
  const ctx = { sessionManager: { getSessionId: () => session },
                ui: { notify: (...args) => notices.push(args) } };
  registerAwaitonal({ on: (name, handler) => { handlers.set(name, handler); },
                     registerCommand: (name, command) => commands.set(name, command) }, {
    transport: { send: (event) => events.push(event), close: async () => { closes += 1; } },
    env: { AWAITONAL_EXECUTABLE: "/private/path with spaces/awaitonal" },
    command: async (...args) => { calls.push(args); return { ok: true, stdout: '{"status":"running","muted":true}' }; },
    ...options,
  });
  return { events, notices, calls, handlers, commands, ctx,
    fire: (name, fields = {}, context = ctx) => handlers.get(name)?.({ type: name, ...fields }, context),
    session: (id) => { session = id; }, closes: () => closes };
}

function assistant(text, stopReason = "stop", extra = []) {
  return { role: "assistant", stopReason, content: [{ type: "text", text }, ...extra] };
}

function settle(bridge, outcome = "completed") {
  bridge.fire("agent_before_settle", { outcome });
  bridge.fire("agent_settled");
}

test("loading registers only handlers/explicit commands and does no setup", async () => {
  const bridge = harness();
  assert.equal(bridge.events.length, 0);
  assert.equal(bridge.calls.length, 0);
  assert.equal(bridge.handlers.has("agent_end"), false);
  assert.deepEqual([...bridge.commands.keys()], ["awaitonal-setup", "awaitonal-mute", "awaitonal-unmute", "awaitonal-status"]);
  const pkg = JSON.parse(await readFile(new URL("../package.json", import.meta.url)));
  assert.deepEqual(pkg.pi, { extensions: ["./extensions/pi.ts"], skills: [], prompts: [], themes: [] });
  assert.equal(pkg.peerDependencies["@earendil-works/pi-coding-agent"], "*");
  assert.equal(pkg.dependencies, undefined);
});

test("only the current final assistant text leaves after agent_settled", () => {
  const bridge = harness();
  assert.equal(bridge.fire("agent_start"), undefined);
  bridge.fire("message_end", { message: assistant("Earlier progress.") });
  bridge.fire("message_end", { message: { role: "user", content: "PRIVATE USER" } });
  bridge.fire("message_end", { message: { role: "toolResult", content: "PRIVATE TOOL" } });
  bridge.fire("message_end", { message: assistant("Done.", "stop", [
    { type: "thinking", thinking: "PRIVATE THOUGHTS" },
    { type: "toolCall", arguments: "PRIVATE ARGS" },
    { type: "image", data: "PRIVATE IMAGE" },
    { type: "text", text: "All checks pass." },
  ]) });
  bridge.fire("agent_end", { messages: [assistant("PRIVATE HISTORICAL MESSAGE")] });
  assert.equal(bridge.events.length, 1);
  settle(bridge);
  assert.equal(bridge.events.length, 2);
  const [start, stop] = bridge.events;
  assert.equal(stop.last_assistant_message, "Done.\nAll checks pass.");
  assert.equal(stop.outcome, "completed");
  assert.equal(start.turn_id, stop.turn_id);
  assert.match(start.turn_id, /^[\da-f-]{36}$/);
  assert.equal(JSON.stringify(bridge.events).includes("PRIVATE"), false);
  bridge.fire("agent_settled");
  assert.equal(bridge.events.length, 2);
});

test("retry and queued continuation retain timing but discard interim errors/prose", () => {
  const bridge = harness();
  bridge.fire("agent_start");
  bridge.fire("message_end", { message: assistant("PRIVATE RATE LIMIT", "error") });
  bridge.fire("agent_end");
  bridge.fire("agent_start");
  bridge.fire("message_end", { message: assistant("Still working.") });
  bridge.fire("agent_before_settle", { outcome: "completed" });
  bridge.fire("agent_start");
  bridge.fire("message_end", { message: assistant("Fixed it.") });
  settle(bridge);
  assert.deepEqual(bridge.events.map((event) => event.hook_event_name), ["agent_start", "agent_settled"]);
  assert.equal(bridge.events[1].outcome, "completed");
  assert.equal(bridge.events[1].last_assistant_message, "Fixed it.");
  assert.equal(bridge.events[0].turn_id, bridge.events[1].turn_id);
});

test("a retry with no final reply cannot replay previous success or failure", () => {
  for (const reason of ["stop", "error"]) {
    const bridge = harness();
    bridge.fire("agent_start");
    bridge.fire("message_end", { message: assistant("PRIVATE PREVIOUS", reason) });
    bridge.fire("agent_before_settle", { outcome: reason === "error" ? "error" : "completed" });
    bridge.fire("agent_start");
    settle(bridge);
    assert.equal(bridge.events[1].outcome, "completed");
    assert.equal(bridge.events[1].last_assistant_message, "");
  }
});

test("authoritative final error or abort sends only structured outcome, never error details", () => {
  for (const reason of ["error", "aborted"]) {
    const bridge = harness();
    bridge.fire("agent_start");
    bridge.fire("message_end", { message: { ...assistant("PRIVATE ERROR", reason), errorMessage: "PRIVATE DETAILS" } });
    settle(bridge, reason);
    assert.equal(bridge.events[1].outcome, reason);
    assert.equal("last_assistant_message" in bridge.events[1], false);
    assert.equal(JSON.stringify(bridge.events).includes("PRIVATE"), false);
    bridge.fire("agent_start");
    assert.notEqual(bridge.events[0].turn_id, bridge.events[2].turn_id);
  }
});

test("missing final boundary after retry or compaction cancellation always settles quietly", () => {
  for (const message of [assistant("PRIVATE RETRY ERROR", "error"), assistant("PRIVATE OLD COMPLETION"), undefined]) {
    const bridge = harness();
    bridge.fire("agent_start");
    if (message) bridge.fire("message_end", { message });
    bridge.fire("agent_end");
    // Pi 0.87.1 skips agent_before_settle when retry/compaction is canceled.
    bridge.fire("agent_settled");
    assert.equal(bridge.events[1].outcome, "aborted");
    assert.equal("last_assistant_message" in bridge.events[1], false);
    assert.equal(JSON.stringify(bridge.events).includes("PRIVATE"), false);
  }
});

test("a new assistant request invalidates the prior boundary even without agent_start", () => {
  for (const emitStart of [true, false]) {
    const bridge = harness();
    bridge.fire("agent_start");
    bridge.fire("message_end", { message: assistant("PRIVATE PREVIOUS COMPLETION") });
    bridge.fire("agent_before_settle", { outcome: "completed" });
    if (emitStart) bridge.fire("message_start", { message: { role: "assistant", content: [] } });
    bridge.fire("message_end", { message: assistant("PRIVATE INTERIM ERROR", "error") });
    bridge.fire("agent_settled");
    assert.equal(bridge.events[1].outcome, "aborted");
    assert.equal("last_assistant_message" in bridge.events[1], false);
  }
});

test("the latest assistant message cannot veto an authoritative abort", () => {
  for (const reason of ["stop", "error"]) {
    const bridge = harness();
    bridge.fire("agent_start");
    bridge.fire("message_end", { message: assistant("PRIVATE OLD OUTCOME", reason) });
    settle(bridge, "aborted");
    assert.equal(bridge.events[1].outcome, "aborted");
    assert.equal("last_assistant_message" in bridge.events[1], false);
  }
});

test("final lifecycle outcome overrides earlier prose and captures compaction failure", () => {
  const bridge = harness();
  bridge.fire("agent_start");
  bridge.fire("message_end", { message: assistant("Earlier complete reply.") });
  settle(bridge, "error");
  assert.equal(bridge.events[1].outcome, "error");
  assert.equal("last_assistant_message" in bridge.events[1], false);
});

test("partial new assistant streams never replay a preceding assistant message", () => {
  const bridge = harness();
  bridge.fire("agent_start");
  bridge.fire("message_end", { message: assistant("Old progress.") });
  bridge.fire("message_start", { message: { role: "assistant", content: [] } });
  settle(bridge);
  assert.equal(bridge.events[1].last_assistant_message, "");
});

test("thinking-only, malformed, and oversize replies quietly close turn timing", () => {
  for (const message of [
    { role: "assistant", stopReason: "stop", content: [{ type: "thinking", thinking: "PRIVATE" }] },
    { role: "assistant", stopReason: "unknown", content: [] },
    assistant("é".repeat(40_000)),
    assistant("\u0001".repeat(20_000)), // JSON escaping, not just UTF-8 text bytes.
    assistant("\ud800"),
    assistant("x".repeat(40_000), "stop", [{ type: "text", text: "x".repeat(40_000) }]),
  ]) {
    const bridge = harness();
    bridge.fire("agent_start");
    bridge.fire("message_end", { message });
    settle(bridge);
    assert.equal(bridge.events[1].outcome, "completed");
    assert.equal(bridge.events[1].last_assistant_message, "");
    assert.ok(Buffer.byteLength(JSON.stringify(bridge.events[1]) + "\n") <= 65_536);
  }
});

test("only active-run user dialogs request attention, with no titles or content", () => {
  const bridge = harness();
  bridge.fire("ui_prompt_start", { kind: "select", title: "PRIVATE IDLE PICKER" });
  assert.equal(bridge.events.length, 0);
  bridge.fire("agent_start");
  for (const kind of ["select", "confirm", "input", "editor", "custom"]) {
    bridge.fire("ui_prompt_start", { kind, title: "PRIVATE PROMPT" });
  }
  bridge.fire("ui_prompt_start", { kind: "unknown" });
  const prompts = bridge.events.slice(1);
  assert.equal(prompts.length, 5);
  assert.equal(new Set(prompts.map((event) => event.request_id)).size, 5);
  assert.ok(prompts.every((event) => event.turn_id === bridge.events[0].turn_id));
  assert.equal(JSON.stringify(prompts).includes("PRIVATE"), false);
});

test("session replacement cancels old activity and does not leak old text", () => {
  const bridge = harness();
  bridge.fire("agent_start");
  bridge.fire("message_end", { message: assistant("PRIVATE OLD SESSION") });
  bridge.session("session-b");
  bridge.fire("session_start");
  assert.equal(bridge.events[1].session_id, "session-a");
  assert.equal(bridge.events[1].outcome, "aborted");
  bridge.fire("agent_settled");
  assert.equal(bridge.events.length, 2);
  bridge.fire("agent_start");
  const oldContext = { sessionManager: { getSessionId: () => "session-a" } };
  bridge.fire("message_end", { message: assistant("PRIVATE LATE OLD SESSION") }, oldContext);
  bridge.fire("agent_settled", {}, oldContext);
  settle(bridge);
  assert.equal(bridge.events[3].session_id, "session-b");
  assert.equal(bridge.events[3].last_assistant_message, "");
  assert.equal(JSON.stringify(bridge.events).includes("PRIVATE"), false);
});

test("shutdown cancels an open turn and awaits bounded transport disposal", async () => {
  const bridge = harness();
  bridge.fire("agent_start");
  await bridge.fire("session_shutdown");
  assert.equal(bridge.events[1].outcome, "aborted");
  assert.equal(bridge.closes(), 1);
  bridge.fire("agent_start");
  bridge.fire("message_end", { message: assistant("After disposal") });
  bridge.fire("ui_prompt_start", { kind: "select" });
  assert.equal(bridge.events.length, 2);
});

test("invalid session identities never send notifications", () => {
  for (const id of [undefined, "", " ", "x".repeat(257), "é".repeat(129), "\ud800"]) {
    const bridge = harness();
    bridge.session(id);
    bridge.fire("agent_start");
    bridge.fire("message_end", { message: assistant("Done.") });
    settle(bridge);
    assert.deepEqual(bridge.events, []);
  }
});

test("resolver respects exact override, plugin runtime, and PATH fallback", async (t) => {
  const dir = await mkdtemp(join(tmpdir(), "awaitonal-pi-"));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const runtime = join(dir, "path with spaces ; $(not-a-command)");
  await mkdir(join(runtime, "bin"), { recursive: true });
  const executable = join(runtime, "bin", "awaitonal");
  await writeFile(executable, "", { mode: 0o700 });
  assert.equal(resolveExecutable({ AWAITONAL_EXECUTABLE: executable }), executable);
  assert.equal(resolveExecutable({ AWAITONAL_EXECUTABLE: "relative/awaitonal", AWAITONAL_PLUGIN_RUNTIME: runtime }), undefined);
  assert.equal(resolveExecutable({ AWAITONAL_PLUGIN_RUNTIME: runtime }), executable);
  assert.equal(resolveExecutable({ AWAITONAL_PLUGIN_RUNTIME: "relative" }), undefined);
  assert.equal(resolveExecutable({ HOME: dir }), "awaitonal");
  const standard = join(dir, ".local", "share", "awaitonal", "plugin", "bin");
  await mkdir(standard, { recursive: true });
  await writeFile(join(standard, "awaitonal"), "", { mode: 0o700 });
  assert.equal(resolveExecutable({ HOME: dir }), join(standard, "awaitonal"));
});

function notification(name, turn = "one") {
  return { hook_event_name: name, session_id: "test-session", turn_id: turn,
           ...(name === "agent_settled" ? { outcome: "completed", last_assistant_message: "Done." } : {}) };
}

test("real notification child receives serialized stdin in order without shell expansion", async (t) => {
  const dir = await mkdtemp(join(tmpdir(), "awaitonal-pi-"));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const executable = join(dir, "awaitonal with spaces ; $(touch NEVER)");
  const log = join(dir, "received.jsonl");
  await writeFile(executable, `#!${process.execPath}\nconst fs = require('node:fs');
let data=''; process.stdin.on('data', x=>data+=x); process.stdin.on('end',()=> {
fs.appendFileSync(process.env.PI_TEST_LOG, JSON.stringify({args:process.argv.slice(2), event:JSON.parse(data)})+'\\n');
process.stdout.write('PRIVATE OUTPUT'); process.stderr.write('PRIVATE ERROR'); setTimeout(()=>process.exit(0),20); });\n`, { mode: 0o700 });
  const transport = createTransport({ ...process.env, AWAITONAL_EXECUTABLE: executable, PI_TEST_LOG: log });
  const events = [notification("agent_start"), notification("ui_prompt_start"), notification("agent_settled")];
  for (const event of events) assert.equal(transport.send(event), undefined);
  await transport.close();
  const rows = (await readFile(log, "utf8")).trim().split("\n").map(JSON.parse);
  assert.deepEqual(rows.map((row) => row.event), events);
  assert.ok(rows.every((row) => JSON.stringify(row.args) === '["hook","pi"]'));
});

test("missing executable and oversized payloads are silent and bounded", async () => {
  const transport = createTransport({ AWAITONAL_EXECUTABLE: "/missing-awaitonal-bin" });
  const started = performance.now();
  transport.send(notification("agent_start"));
  transport.send({ ...notification("agent_settled"), last_assistant_message: "x".repeat(70_000) });
  await transport.close();
  assert.ok(performance.now() - started < 2_000);
  await transport.close();
});

test("hung child is terminated within the bounded hook/shutdown deadlines", async (t) => {
  const dir = await mkdtemp(join(tmpdir(), "awaitonal-pi-"));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const executable = join(dir, "hung-awaitonal");
  await writeFile(executable, `#!${process.execPath}\nprocess.stdin.resume();setInterval(()=>{},1000);\n`, { mode: 0o700 });
  const transport = createTransport({ ...process.env, AWAITONAL_EXECUTABLE: executable });
  const started = performance.now();
  for (let i = 0; i < 100; i++) transport.send(notification("agent_start", String(i)));
  await transport.close();
  assert.ok(performance.now() - started < 2_000);
});

test("slash controls use an argv array and explain shared mute", async () => {
  const bridge = harness();
  await bridge.commands.get("awaitonal-mute").handler("", bridge.ctx);
  await bridge.commands.get("awaitonal-unmute").handler("", bridge.ctx);
  await bridge.commands.get("awaitonal-status").handler("", bridge.ctx);
  assert.deepEqual(bridge.calls.map((call) => call.slice(0, 3)), [
    ["/private/path with spaces/awaitonal", ["service", "mute"], 2_000],
    ["/private/path with spaces/awaitonal", ["service", "unmute"], 2_000],
    ["/private/path with spaces/awaitonal", ["service", "status"], 2_000],
  ]);
  assert.match(bridge.notices[0][0], /all sessions/);
  assert.match(bridge.notices[2][0], /running \(muted\)/);
  await bridge.commands.get("awaitonal-mute").handler("--something", bridge.ctx);
  assert.equal(bridge.calls.length, 3);
});

test("setup runs only its explicit slash command with bounded timeout", async () => {
  const bridge = harness();
  await bridge.commands.get("awaitonal-setup").handler("", bridge.ctx);
  const [executable, args, timeout] = bridge.calls[0];
  assert.equal(executable, "sh");
  assert.ok(args[0].endsWith("/scripts/plugin-runtime.sh"));
  assert.deepEqual(args.slice(1), ["setup", "--adapter", "pi"]);
  assert.equal(timeout, 180_000);
  assert.match(bridge.notices.at(-1)[0], /ready/);
});

test("unavailable controls report locally without leaking process output", async () => {
  const bridge = harness({ command: async () => ({ ok: false, stdout: "PRIVATE OUTPUT" }) });
  await bridge.commands.get("awaitonal-status").handler("", bridge.ctx);
  assert.match(bridge.notices[0][0], /could not reach/);
  assert.equal(JSON.stringify(bridge.notices).includes("PRIVATE"), false);
});

test("command runner bounds captured output and missing executables", async () => {
  const result = await runCommand(process.execPath, ["-e", "process.stdout.write('x'.repeat(100000))"], 2_000);
  assert.equal(result.ok, true);
  assert.ok(Buffer.byteLength(result.stdout) <= 16_384);
  assert.deepEqual(await runCommand("/missing-awaitonal-bin", [], 300), { ok: false, stdout: "" });
});
