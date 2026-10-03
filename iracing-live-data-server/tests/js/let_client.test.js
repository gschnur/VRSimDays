"use strict";
// Run: node --test tests/js/*.test.js   (or just `node --test` from the project root)
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const { LetClient } = require(path.join(__dirname, "..", "..", "client", "let_client.js"));

class FakeWebSocket {
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.sent = [];
    this.closedWith = null;
    FakeWebSocket.instances.push(this);
  }
  send(text) { this.sent.push(JSON.parse(text)); }
  close(code) {
    this.closedWith = code;
    this.serverClose(code);
  }
  // test helpers
  open() { this.readyState = 1; this.onopen && this.onopen({}); }
  message(obj) { this.onmessage && this.onmessage({ data: typeof obj === "string" ? obj : JSON.stringify(obj) }); }
  serverClose(code = 1006) {
    if (this.readyState === 3) return;
    this.readyState = 3;
    this.onclose && this.onclose({ code, reason: "" });
  }
}
FakeWebSocket.instances = [];

class FakeTimers {
  constructor() { this.now = 0; this.pending = new Map(); this.nextId = 1; this.delays = []; }
  setTimeout(fn, ms) {
    const id = this.nextId++;
    this.pending.set(id, { fn, at: this.now + ms });
    this.delays.push(ms);
    return id;
  }
  clearTimeout(id) { this.pending.delete(id); }
  advance(ms) {
    this.now += ms;
    for (const [id, t] of [...this.pending]) {
      if (t.at <= this.now) { this.pending.delete(id); t.fn(); }
    }
  }
}

const quietLogger = { warnings: [], warn(...a) { this.warnings.push(a); }, error() {} };

function makeClient(opts = {}) {
  FakeWebSocket.instances = [];
  const timers = new FakeTimers();
  const logger = Object.assign({}, quietLogger, { warnings: [] });
  const client = new LetClient({
    url: "ws://test",
    WebSocketImpl: FakeWebSocket,
    timers,
    random: () => 0.5, // zero jitter
    logger,
    ...opts,
  });
  return { client, timers, logger, ws: () => FakeWebSocket.instances.at(-1) };
}

const env = (type, data, seq = null) => ({ type, seq, ts: 1, data });
const hello = (over = {}) =>
  env("hello", { server_version: "0.1.0", sector_count: 3, iracing_connected: true, driver_name: null, clients: 1, ...over });
const snapshot = (asOf, over = {}, seq = null) =>
  env("snapshot", {
    driver_name: null, sector_count: 3, current_lap: 0, lap_count: 0, last_lap: null, best_lap: null,
    best_lap_number: 0, best_sector_times: [null, null, null], optimal_lap_time: null, current_lap_sectors: [],
    iracing_connected: true, clients: 1, as_of_seq: asOf, ...over,
  }, seq);
const sector = (seq, over = {}) =>
  env("sector_update", { driver_name: "A", sector: 1, time: 30, lap_number: 1, current_lap_sectors: [30],
    best_sector_times: [30, null, null], optimal_lap_time: null, ...over }, seq);

function connected(opts) {
  const h = makeClient(opts);
  h.client.connect();
  h.ws().open();
  h.ws().message(hello());
  h.ws().message(snapshot(5));
  return h;
}

test("hello and snapshot populate state", () => {
  const { client, ws } = makeClient();
  const seen = [];
  client.on("hello", (d) => seen.push(["hello", d.sector_count]));
  client.on("snapshot", (d) => seen.push(["snapshot", d.as_of_seq]));
  client.connect();
  ws().open();
  assert.equal(client.state.connected, true);
  ws().message(hello({ driver_name: "Jane", clients: 2 }));
  ws().message(snapshot(7, { driver_name: "Jane", clients: 2 }));
  assert.deepEqual(seen, [["hello", 3], ["snapshot", 7]]);
  assert.equal(client.state.lastSeq, 7);
  assert.equal(client.state.driverName, "Jane");
  assert.equal(client.state.clients, 2);
  assert.equal(client.state.iracingConnected, true);
  assert.equal(client.state.snapshot.sector_count, 3);
});

test("in-order broadcasts update lastSeq and merge into snapshot", () => {
  const { client, ws } = connected();
  const got = [];
  client.on("sector_update", (d) => got.push(d.sector));
  ws().message(sector(6));
  ws().message(env("lap_update", {
    driver_name: "A", lap_number: 1, lap_time: 90, valid: true, sectors: [30, 30, 30], best_lap_time: 90,
    best_lap_number: 1, best_sector_times: [30, 30, 30], optimal_lap_time: 90, current_lap: 2,
  }, 7));
  ws().message(env("status", { iracing_connected: false, clients: 3 }, 8));
  assert.deepEqual(got, [1]);
  assert.equal(client.state.lastSeq, 8);
  const s = client.state.snapshot;
  assert.equal(s.last_lap.lap_time, 90);
  assert.equal(s.best_lap.lap_number, 1);
  assert.equal(s.current_lap, 2);
  assert.deepEqual(s.current_lap_sectors, []);
  assert.equal(s.optimal_lap_time, 90);
  assert.equal(client.state.iracingConnected, false);
  assert.equal(client.state.clients, 3);
  assert.equal(client.state.driverName, "A");
});

test("seq gap emits gap and requests a snapshot once", () => {
  const { client, ws } = connected();
  const gaps = [];
  client.on("gap", (d) => gaps.push(d));
  ws().message(sector(8));
  ws().message(sector(10));
  assert.deepEqual(gaps, [{ expected: 6, received: 8 }, { expected: 9, received: 10 }]);
  assert.deepEqual(ws().sent.map((m) => m.type), ["get_snapshot"]); // no duplicate while resyncing
  ws().message(snapshot(10));
  assert.equal(client.state.lastSeq, 10);
  ws().message(sector(12));
  assert.deepEqual(ws().sent.map((m) => m.type), ["get_snapshot", "get_snapshot"]);
});

test("stale and duplicate seq are dropped", () => {
  const { client, ws } = connected();
  const got = [];
  client.on("sector_update", (d, m) => got.push(m.seq));
  ws().message(sector(5)); // == as_of_seq: already reflected
  ws().message(sector(3));
  ws().message(sector(6));
  ws().message(sector(6));
  assert.deepEqual(got, [6]);
  assert.equal(client.state.lastSeq, 6);
});

test("as_of_seq handling: direct snapshot sets lastSeq; broadcast snapshot uses max", () => {
  const { client, ws } = connected();
  assert.equal(client.state.lastSeq, 5);
  ws().message(snapshot(9, { driver_name: "B" }, 9)); // broadcast after reset
  assert.equal(client.state.lastSeq, 9);
  assert.equal(client.state.driverName, "B");
  ws().message(snapshot(4, { driver_name: "OLD" }, 4)); // stale broadcast snapshot dropped
  assert.equal(client.state.driverName, "B");
  ws().message(snapshot(12)); // direct (seq null)
  assert.equal(client.state.lastSeq, 12);
});

test("reconnect uses exponential backoff, caps, and resets after open", () => {
  const { client, ws, timers } = connected({ reconnect: { minMs: 500, maxMs: 2000, factor: 2, jitter: 0.2 } });
  const closes = [];
  client.on("close", (d) => closes.push(d.code));

  ws().serverClose(1001);
  assert.equal(client.state.connected, false);
  assert.deepEqual(closes, [1001]);
  assert.deepEqual(timers.delays, [500]);

  timers.advance(499);
  assert.equal(FakeWebSocket.instances.length, 1);
  timers.advance(1);
  assert.equal(FakeWebSocket.instances.length, 2);

  ws().serverClose(); // connection refused
  timers.advance(1000);
  ws().serverClose();
  timers.advance(2000);
  ws().serverClose();
  assert.deepEqual(timers.delays, [500, 1000, 2000, 2000]);

  timers.advance(2000);
  ws().open();
  ws().serverClose();
  assert.equal(timers.delays.at(-1), 500);
});

test("jitter stays within the configured fraction", () => {
  for (const r of [0, 1]) {
    const { client } = makeClient({ random: () => r });
    const d = client.nextDelay();
    assert.equal(d, r === 0 ? 400 : 600);
  }
});

test("close() stops reconnecting", () => {
  const { client, ws, timers } = connected();
  client.close();
  assert.equal(ws().closedWith, 1000);
  timers.advance(60000);
  assert.equal(FakeWebSocket.instances.length, 1);
  assert.equal(timers.pending.size, 0);

  // close() during backoff cancels the pending attempt
  const h = connected();
  h.ws().serverClose();
  assert.equal(h.timers.pending.size, 1);
  h.client.close();
  assert.equal(h.timers.pending.size, 0);
});

test("reconnect rebuilds state from the new hello + snapshot (server restart)", () => {
  const { client, ws, timers } = connected();
  ws().message(sector(6));
  ws().serverClose();
  timers.advance(500);
  ws().open();
  assert.equal(client.state.lastSeq, null);
  ws().message(hello());
  ws().message(snapshot(0));
  assert.equal(client.state.lastSeq, 0);
  const got = [];
  client.on("sector_update", (d, m) => got.push(m.seq));
  ws().message(sector(1));
  assert.deepEqual(got, [1]);
});

test("commands are rejected while disconnected", () => {
  const { client, ws } = makeClient();
  const errors = [];
  client.on("error", (d) => errors.push(d));
  assert.equal(client.reset("Jane"), false);
  assert.equal(client.returnToPits(), false);
  assert.equal(errors.length, 2);
  assert.equal(errors[0].code, "not_connected");
  assert.equal(errors[0].request_type, "reset");

  client.connect();
  assert.equal(client.reset("Jane"), false); // socket not open yet
  assert.deepEqual(ws().sent, []);

  ws().open();
  assert.equal(client.reset("Jane"), true);
  assert.equal(client.returnToPits(), true);
  assert.equal(client.getSnapshot(), true);
  assert.deepEqual(ws().sent, [
    { type: "reset", data: { driver_name: "Jane" } },
    { type: "return_to_pits", data: {} },
    { type: "get_snapshot", data: {} },
  ]);

  ws().serverClose();
  assert.equal(client.reset("Later"), false); // never queued
});

test("invalid and unknown messages are ignored without throwing", () => {
  const { client, ws, logger } = connected();
  const any = [];
  for (const t of LetClient.EVENTS) client.on(t, () => any.push(t));
  ws().message("{not json");
  ws().message(JSON.stringify({ seq: 6, data: {} }));
  ws().message("42");
  ws().message(env("mystery", {}, null));
  assert.equal(logger.warnings.length, 3);
  assert.deepEqual(any, []);
  assert.equal(client.state.lastSeq, 5);
});

test("server error and ack messages are surfaced", () => {
  const { client, ws } = connected();
  const got = [];
  client.on("error", (d) => got.push(["error", d.code]));
  client.on("reset_ack", (d) => got.push(["reset_ack", d.driver_name]));
  client.on("pit_ack", (d) => got.push(["pit_ack", d.ok]));
  ws().message(env("error", { code: "invalid_driver_name", message: "x", request_type: "reset" }));
  ws().message(env("reset_ack", { ok: true, driver_name: "Jane" }));
  ws().message(env("pit_ack", { ok: false, detail: "disabled" }));
  assert.deepEqual(got, [["error", "invalid_driver_name"], ["reset_ack", "Jane"], ["pit_ack", false]]);
});

test("a throwing handler does not break dispatch", () => {
  const { client, ws } = connected();
  let second = false;
  client.on("sector_update", () => { throw new Error("boom"); });
  client.on("sector_update", () => { second = true; });
  ws().message(sector(6));
  assert.equal(second, true);
});
