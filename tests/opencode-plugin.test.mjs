import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { performance } from "node:perf_hooks";
import test from "node:test";
import plugin from "../extensions/opencode.ts";
import { createOpenCodeBridge, createTransport, resolveExecutable } from "../extensions/opencode-core.ts";

function harness(options = {}) {
  const events = [], lookups = [];
  let closes = 0, now = 1_000;
  const bridge = createOpenCodeBridge({
    transport: { send(event) { events.push(event); return true; }, close: async () => { closes++; } },
    getSession: async (id) => { lookups.push(id); return { id }; },
    now: () => now, ...options,
  });
  const fire = (type, properties) => bridge.event({ event: { type, properties } });
  const root = (sessionID = "ses_main", parentID) => fire("session.created", { info: { id: sessionID, parentID } });
  const status = (type, sessionID = "ses_main") => fire("session.status", { sessionID, status: { type } });
  const info = (fields = {}, sessionID = "ses_main") => fire("message.updated", { info: {
    role: "assistant", id: "msg_assistant", parentID: "msg_user", sessionID,
    time: { created: 1 }, ...fields,
  } });
  const part = (fields, sessionID = "ses_main") => fire("message.part.updated", { part: {
    id: `prt_${fields.type}`, messageID: "msg_assistant", sessionID, ...fields,
  } });
  const begin = (sessionID = "ses_main") => {
    root(sessionID); fire("message.updated", { info: { role: "user", id: "msg_user", sessionID } });
    status("busy", sessionID); info({}, sessionID); part({ type: "step-start" }, sessionID);
  };
  const complete = (text = "Done.", sessionID = "ses_main", fields = {}) => {
    part({ type: "text", text, time: { start: 1, end: 2 } }, sessionID);
    part({ type: "step-finish", reason: "stop" }, sessionID);
    info({ time: { created: 1, completed: 2 }, finish: "stop", ...fields }, sessionID);
  };
  return { bridge, events, lookups, fire, root, status, info, part, begin, complete,
    time: (value) => { now = value; }, closes: () => closes };
}

test("native loader entrypoint exports only the plugin and loading performs no model/setup calls", async () => {
  const module = await import("../extensions/opencode.ts");
  assert.deepEqual(Object.keys(module), ["default"]);
  let calls = 0;
  const hooks = await plugin({ client: { session: { get: async () => { calls++; return {}; } } } });
  assert.deepEqual(Object.keys(hooks), ["event", "experimental.session.compacting", "dispose"]);
  await hooks.dispose(); assert.equal(calls, 0);
});

test("success waits for idle and forwards only completed final assistant text once", async () => {
  const h = harness(); h.begin();
  h.part({ type: "text", text: "PRIVATE STREAM", time: { start: 1 } });
  h.part({ type: "reasoning", text: "PRIVATE REASONING", time: { end: 2 } });
  h.part({ type: "file", url: "file:///PRIVATE-PATH", time: { end: 2 } });
  h.part({ type: "text", text: "PRIVATE SYNTHETIC", synthetic: true, time: { end: 2 } });
  h.part({ type: "text", text: "PRIVATE IGNORED", ignored: true, time: { end: 2 } });
  h.complete(); h.part({ id: "prt_second", type: "text", text: "Tests pass.", time: { end: 3 } });
  assert.equal(h.events.length, 1);
  h.status("busy"); // The real loop reports busy again while checking its exit condition.
  h.status("idle"); h.fire("session.idle", { sessionID: "ses_main" }); h.status("idle");
  assert.equal(h.events.length, 2);
  assert.equal(h.events[1].last_assistant_message, "Done.\nTests pass.");
  assert.equal(h.events[1].outcome, "completed");
  assert.equal(h.events[0].turn_id, h.events[1].turn_id);
  assert.match(h.events[0].turn_id, /^[\da-f-]{36}$/);
  assert.equal(JSON.stringify(h.events).includes("PRIVATE"), false);
  await h.bridge.dispose(); assert.equal(h.closes(), 1);
});

test("successive model steps discard progress text and do not create extra turn starts", () => {
  const h = harness(); h.begin(); h.complete("PRIVATE PROGRESS");
  h.part({ type: "tool", state: { output: "PRIVATE TOOL" } });
  h.info({ id: "msg_final" });
  h.part({ type: "step-start", messageID: "msg_final" });
  h.part({ type: "text", messageID: "msg_final", text: "Fixed.", time: { end: 3 } });
  h.part({ type: "step-finish", messageID: "msg_final", reason: "stop" });
  h.info({ id: "msg_final", time: { created: 2, completed: 3 }, finish: "stop" }); h.status("idle");
  assert.equal(h.events.length, 2); assert.equal(h.events[1].last_assistant_message, "Fixed.");
});

test("later full-value exclusions and retractions cannot replay cached text", () => {
  for (const update of [
    { type: "text", ignored: true, time: { end: 3 } },
    { type: "text", synthetic: true, time: { end: 3 } },
    { type: "reasoning", time: { end: 3 } },
    { type: "text", time: { start: 3 } },
  ]) {
    const h = harness(); h.begin(); h.complete("PRIVATE RETRACTED TEXT");
    h.part({ id: "prt_text", text: "PRIVATE REPLACEMENT", ...update }); h.status("idle");
    assert.equal(h.events[1].outcome, "aborted");
    assert.equal(h.events[1].last_assistant_message, undefined);
    assert.equal(JSON.stringify(h.events).includes("PRIVATE"), false);
  }
});

test("idle without authoritative terminal completion is quiet, including old history and tool calls", () => {
  for (const situation of ["no-message", "not-completed", "missing-step", "tool-calls", "unknown", "history", "tools"]) {
    const h = harness(); h.begin();
    if (situation === "history") {
      h.info({ id: "msg_historical", finish: "stop", time: { created: 0, completed: 1 } });
    } else if (situation !== "no-message") {
      h.part({ type: "text", text: "PRIVATE STALE", time: { end: 2 } });
      if (situation !== "missing-step") h.part({ type: "step-finish", reason: ["tool-calls", "unknown"].includes(situation) ? situation : "stop" });
      if (situation !== "not-completed") h.info({ finish: "stop", time: { created: 1, completed: 2 } });
      if (situation === "tools") h.part({ type: "tool" });
    }
    h.status("idle"); assert.equal(h.events[1].outcome, "aborted", situation);
    assert.equal(h.events[1].last_assistant_message, undefined);
  }
});

test("retry preserves the activity but requires fresh text and step completion", () => {
  const h = harness(); h.begin(); h.complete("PRIVATE FIRST ATTEMPT");
  h.status("retry"); h.status("busy"); h.part({ type: "step-start" }); h.complete("Recovered.");
  h.status("idle"); assert.equal(h.events.length, 2);
  assert.equal(h.events[1].last_assistant_message, "Recovered.");
  for (const cleanup of [false, true]) {
    const canceled = harness(); canceled.begin(); canceled.complete("PRIVATE PRIOR ATTEMPT");
    canceled.status("retry");
    if (cleanup) canceled.info({ finish: "stop", time: { created: 1, completed: 3 } });
    canceled.status("idle");
    assert.equal(canceled.events[1].outcome, "aborted");
  }
});

test("compaction/cancellation cannot replay an earlier successful reply", async () => {
  for (const boundary of ["hook", "summary", "compacted"]) {
    const h = harness(); h.begin(); h.complete("PRIVATE BEFORE COMPACTION");
    if (boundary === "hook") await h.bridge["experimental.session.compacting"]({ sessionID: "ses_main" });
    if (boundary === "summary") h.info({ id: "msg_summary", summary: true });
    if (boundary === "compacted") h.fire("session.compacted", { sessionID: "ses_main" });
    h.info({ finish: "stop", time: { created: 1, completed: 2 } }); h.status("idle");
    assert.equal(h.events[1].outcome, "aborted", boundary);
  }
});

test("interim compaction errors are quiet and a later final message succeeds", () => {
  const h = harness(); h.begin();
  h.fire("session.error", { sessionID: "ses_main", error: { name: "ContextOverflowError", data: { message: "PRIVATE" } } });
  assert.equal(h.events.length, 1);
  h.info({ id: "msg_summary", summary: true }); h.info({ id: "msg_new" });
  h.part({ messageID: "msg_new", type: "step-start" });
  h.part({ messageID: "msg_new", type: "text", text: "Finished.", time: { end: 3 } });
  h.part({ messageID: "msg_new", type: "step-finish", reason: "stop" });
  h.info({ id: "msg_new", time: { created: 2, completed: 3 }, finish: "stop" }); h.status("idle");
  assert.equal(h.events[1].outcome, "completed"); assert.equal(h.events[1].last_assistant_message, "Finished.");
});

test("terminal failed compaction reports generic failure from summary metadata without text", () => {
  const h = harness(); h.begin(); h.complete("PRIVATE OLD OUTPUT");
  h.info({ id: "msg_summary", summary: true });
  h.part({ messageID: "msg_summary", type: "text", text: "PRIVATE SUMMARY", time: { end: 3 } });
  h.info({ id: "msg_summary", summary: true, finish: "error", error: { name: "ContextOverflowError", data: { message: "PRIVATE" } }, time: { created: 2, completed: 3 } });
  h.status("idle"); assert.equal(h.events[1].outcome, "error");
  assert.equal(h.events[1].last_assistant_message, undefined);
  assert.equal(JSON.stringify(h.events).includes("PRIVATE"), false);
});

test("terminal errors are generic and native aborts are quiet even before cleanup", () => {
  for (const name of ["APIError", "ProviderAuthError", "ContextOverflowError", "MessageAbortedError"]) {
    const h = harness(); h.begin(); h.complete("PRIVATE STALE SUCCESS");
    h.fire("session.error", { sessionID: "ses_main", error: { name, data: { message: "PRIVATE ERROR", responseBody: "PRIVATE" } } });
    h.status("idle"); h.info({ error: { name }, time: { created: 1, completed: 5 } }); h.status("idle");
    assert.equal(h.events.length, 2);
    assert.equal(h.events[1].outcome, name === "MessageAbortedError" ? "aborted" : "error");
    assert.equal(h.events[1].last_assistant_message, undefined);
    assert.equal(JSON.stringify(h.events).includes("PRIVATE"), false);
  }
});

test("an error stored only on the final message also overrides text", () => {
  const h = harness(); h.begin(); h.complete("PRIVATE", "ses_main", { error: { name: "StructuredOutputError" } });
  h.status("idle"); assert.equal(h.events[1].outcome, "error");
});

test("new user input invalidates previous prose; each settled activity gets a fresh UUID", () => {
  const h = harness(); h.begin(); h.complete("PRIVATE OLD TURN");
  h.fire("message.updated", { info: { role: "user", id: "msg_new_user", sessionID: "ses_main", text: "PRIVATE USER" } });
  h.info({ time: { created: 1, completed: 2 }, finish: "stop" }); h.status("idle");
  assert.equal(h.events[1].outcome, "aborted");
  h.begin(); h.complete(); h.status("idle");
  assert.notEqual(h.events[0].turn_id, h.events[2].turn_id);
});

test("native permission/question requests are scoped, deduplicated and never forward details", () => {
  const h = harness(); h.root();
  const permission = { id: "per_1", sessionID: "ses_main", permission: "bash", patterns: ["PRIVATE"], metadata: { path: "PRIVATE" } };
  h.fire("permission.asked", permission); assert.equal(h.events.length, 0);
  h.begin(); h.fire("permission.asked", { ...permission, tool: { messageID: "msg_stale" } });
  h.fire("permission.asked", { ...permission, tool: { messageID: "msg_assistant", callID: "PRIVATE" } });
  h.fire("permission.asked", permission);
  h.fire("question.asked", { id: "que_1", sessionID: "ses_main", questions: [{ question: "PRIVATE QUESTION" }], tool: { messageID: "msg_assistant" } });
  h.fire("question.asked", { id: "que_empty", sessionID: "ses_main", questions: [] });
  h.fire("question.asked", { id: "que_invalid", sessionID: "ses_main", questions: [{ question: " " }] });
  assert.deepEqual(h.events.map((e) => e.hook_event_name), ["agent_start", "permission_asked", "question_asked"]);
  assert.ok(h.events.slice(1).every((e) => e.turn_id === h.events[0].turn_id && /^[\da-f-]{36}$/.test(e.request_id)));
  assert.equal(JSON.stringify(h.events).includes("PRIVATE"), false);
  h.status("idle"); assert.equal(h.events[3].outcome, "aborted");
});

test("native permission/question resolutions cancel only their unsent attention", () => {
  const canceled = [];
  const h = harness({ transport: { send: () => true, cancelAttention: (...ids) => canceled.push(ids), close: async () => {} } });
  h.begin();
  h.fire("permission.asked", { id: "per_1", sessionID: "ses_main", permission: "bash" });
  h.fire("question.asked", { id: "que_1", sessionID: "ses_main", questions: [{ question: "Proceed?" }] });
  h.fire("question.replied", { sessionID: "ses_main", requestID: "unseen", answers: ["PRIVATE"] });
  h.fire("permission.replied", { sessionID: "ses_main", requestID: "per_1", reply: "once" });
  h.fire("question.rejected", { sessionID: "ses_main", requestID: "que_1" });
  assert.equal(canceled.length, 2); assert.equal(canceled[0][0], "ses_main");
  assert.notEqual(canceled[0][2], canceled[1][2]);
});

test("subagents never chime, including existing child sessions discovered by read-only lookup", async () => {
  const h = harness({ getSession: async (id) => ({ id, parentID: "ses_parent" }) });
  h.root("ses_child", "ses_parent"); h.status("busy", "ses_child"); h.info({}, "ses_child"); h.complete("PRIVATE", "ses_child"); h.status("idle", "ses_child");
  h.status("busy", "ses_resumed_child"); await new Promise((resolve) => setImmediate(resolve));
  h.complete("PRIVATE", "ses_resumed_child"); h.status("idle", "ses_resumed_child");
  assert.deepEqual(h.events, []);
});

test("resumed roots use only bounded session metadata lookup; stale results cannot revive ended turns", async () => {
  let resolveLookup;
  const h = harness({ getSession: () => new Promise((resolve) => { resolveLookup = resolve; }) });
  h.status("busy"); await new Promise((resolve) => setImmediate(resolve));
  assert.equal(h.events.length, 0);
  resolveLookup({ id: "ses_main", path: "PRIVATE", title: "PRIVATE" });
  await new Promise((resolve) => setImmediate(resolve)); h.info(); h.part({ type: "step-start" }); h.complete(); h.status("idle");
  assert.equal(h.events.length, 1); assert.equal(h.events[0].hook_event_name, "agent_settled");
  const stale = harness({ getSession: () => new Promise((resolve) => { resolveLookup = resolve; }) });
  stale.status("busy"); await new Promise((resolve) => setImmediate(resolve)); stale.status("idle");
  resolveLookup({ id: "ses_main" }); await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(stale.events, []);
});

test("failed or mismatched metadata lookup remains quiet and never falls back to transcript access", async () => {
  for (const getSession of [async () => { throw Error("PRIVATE"); }, async () => ({ id: "other" })]) {
    const h = harness({ getSession }); h.status("busy");
    await new Promise((resolve) => setImmediate(resolve)); h.info(); h.complete(); h.status("idle");
    assert.deepEqual(h.events, []);
  }
});

test("oversized/invalid final text closes the turn quietly; JSON escaping counts toward the cap", () => {
  for (const text of ["a".repeat(65_537), "😀".repeat(20_000), "\n".repeat(40_000), "bad\ud800text"]) {
    const h = harness(); h.begin(); h.complete(text); h.status("idle");
    assert.equal(h.events[1].outcome, "aborted"); assert.equal(h.events[1].last_assistant_message, undefined);
    assert.ok(Buffer.byteLength(JSON.stringify(h.events[1])) < 1024);
  }
  const empty = harness(); empty.begin(); empty.complete(""); empty.status("idle");
  assert.equal(empty.events[1].last_assistant_message, "");
});

test("excess parts, removal, and malformed native envelopes fail quiet", async () => {
  const h = harness(); h.begin();
  for (let n = 0; n < 33; n++) h.part({ id: `part_${n}`, type: "text", text: "x", time: { end: 2 } });
  h.complete(); h.status("idle"); assert.equal(h.events[1].outcome, "aborted");
  const removed = harness(); removed.begin(); removed.complete();
  removed.fire("message.part.removed", { sessionID: "ses_main", messageID: "msg_assistant", partID: "prt_text" });
  removed.status("idle"); assert.equal(removed.events[1].outcome, "aborted");
  for (const event of [null, [], {}, { properties: [] }, { type: "session.status", properties: { sessionID: "x".repeat(257), status: { type: "busy" } } }]) {
    await h.bridge.event({ event });
  }
  assert.equal(h.events.length, 2);
});

test("session deletion, eviction, expiration and disposal close activities quietly", async () => {
  const h = harness(); h.begin(); h.complete("PRIVATE");
  h.fire("session.deleted", { info: { id: "ses_main" } }); assert.equal(h.events[1].outcome, "aborted");
  h.begin(); h.time(3_602_000); h.root("another"); assert.equal(h.events[3].outcome, "aborted");
  h.begin(); for (let n = 0; n < 128; n++) h.root(`session_${n}`);
  assert.equal(h.events[5].outcome, "aborted");
  h.begin(); await h.bridge.dispose(); await h.bridge.dispose();
  assert.equal(h.events[7].outcome, "aborted"); assert.equal(h.closes(), 1);
  h.begin(); assert.equal(h.events.length, 8);
});

test("a rejected start is never retried mid-turn or followed by attention/settlement", () => {
  const calls = [];
  const h = harness({ transport: { send: (e) => { calls.push(e); return false; }, close: async () => {} } });
  h.begin(); h.status("busy"); h.complete(); h.status("idle");
  assert.equal(calls.length, 1); assert.equal(calls[0].hook_event_name, "agent_start");
});

test("executable resolution respects explicit absolute overrides", async () => {
  assert.equal(resolveExecutable({ AWAITONAL_EXECUTABLE: "relative" }), undefined);
  assert.equal(resolveExecutable({ AWAITONAL_EXECUTABLE: "/path with spaces/awaitonal" }), "/path with spaces/awaitonal");
  assert.equal(resolveExecutable({ AWAITONAL_PLUGIN_RUNTIME: "relative" }), undefined);
  const directory = await mkdtemp(join(tmpdir(), "awaitonal-opencode-"));
  try {
    await mkdir(join(directory, "bin")); const executable = join(directory, "bin", "awaitonal");
    await writeFile(executable, "#!/bin/sh\nexit 0\n", { mode: 0o700 });
    assert.equal(resolveExecutable({ AWAITONAL_PLUGIN_RUNTIME: directory }), executable);
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test("real transport sends bounded JSON in order with safe argv and no shell", async () => {
  const directory = await mkdtemp(join(tmpdir(), "awaitonal-opencode-"));
  try {
    const executable = join(directory, "fake awaitonal"), log = join(directory, "events.jsonl");
    await writeFile(executable, `#!${process.execPath}\nimport fs from 'node:fs';let s='';process.stdin.on('data',b=>s+=b);process.stdin.on('end',()=>fs.appendFileSync(process.env.TEST_LOG,JSON.stringify({args:process.argv.slice(2),event:JSON.parse(s)})+'\\n'));\n`, { mode: 0o700 });
    const transport = createTransport({ ...process.env, AWAITONAL_EXECUTABLE: executable, TEST_LOG: log });
    const base = { session_id: "session with '$(echo nope)'", turn_id: "turn" };
    assert.equal(transport.send({ ...base, hook_event_name: "agent_start" }), true);
    assert.equal(transport.send({ ...base, hook_event_name: "agent_settled", outcome: "completed", last_assistant_message: "Done." }), true);
    await transport.close();
    const rows = (await readFile(log, "utf8")).trim().split("\n").map(JSON.parse);
    assert.deepEqual(rows.map((row) => row.args), [["hook", "opencode"], ["hook", "opencode"]]);
    assert.deepEqual(rows.map((row) => row.event.hook_event_name), ["agent_start", "agent_settled"]);
    assert.equal(rows[0].event.session_id, base.session_id);
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test("transport reserves settlements and cancels unsent attention under queue pressure", async () => {
  const directory = await mkdtemp(join(tmpdir(), "awaitonal-opencode-"));
  try {
    const executable = join(directory, "slow");
    await writeFile(executable, `#!${process.execPath}\nsetInterval(()=>{},1000);\n`, { mode: 0o700 });
    const transport = createTransport({ ...process.env, AWAITONAL_EXECUTABLE: executable });
    const admitted = [];
    for (let n = 0; n < 100; n++) {
      const event = { hook_event_name: "agent_start", session_id: `s${n}`, turn_id: `t${n}` };
      if (transport.send(event)) admitted.push(event);
    }
    assert.equal(admitted.length, 8);
    for (const event of admitted) assert.equal(transport.send({ ...event, hook_event_name: "agent_settled", outcome: "aborted" }), true);
    const started = performance.now(); await transport.close();
    assert.ok(performance.now() - started < 2500);
    assert.equal(transport.send({ hook_event_name: "agent_start", session_id: "later", turn_id: "later" }), false);
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test("missing executable/service stays nonblocking and close is bounded", async () => {
  const transport = createTransport({ AWAITONAL_EXECUTABLE: "/no/such/awaitonal" });
  const started = performance.now();
  transport.send({ hook_event_name: "agent_start", session_id: "s", turn_id: "t" });
  transport.send({ hook_event_name: "agent_settled", session_id: "s", turn_id: "t", outcome: "aborted" });
  assert.ok(performance.now() - started < 100);
  await transport.close(); assert.ok(performance.now() - started < 2000);
});
