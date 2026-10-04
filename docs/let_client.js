/*
 * IRLDS browser client (classic script, no dependencies).
 *
 * Browser: <script src="let_client.js"></script> → window.IRLDS.LetClient
 * Node:    const { LetClient } = require("./let_client.js")
 *
 * Wraps the WebSocket and the IRLDS protocol: envelope parsing, seq gap detection
 * and resync, reconnect with backoff, and a merged view of the session state.
 * No DOM access; UI belongs to the consumer.
 */
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
  if (root && typeof root.document !== "undefined") {
    root.IRLDS = Object.assign(root.IRLDS || {}, api);
  }
})(typeof window !== "undefined" ? window : typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var EVENTS = [
    "open", "close", "hello", "snapshot", "sector_update", "lap_update",
    "status", "reset_ack", "pit_ack", "pong", "error", "gap",
  ];
  var DEFAULT_RECONNECT = { minMs: 500, maxMs: 10000, factor: 2, jitter: 0.2 };
  var OPEN = 1;

  function LetClient(options) {
    var opts = options || {};
    this.url = opts.url || "ws://127.0.0.1:8765";
    this.reconnect = Object.assign({}, DEFAULT_RECONNECT, opts.reconnect || {});
    this.WebSocketImpl = opts.WebSocketImpl || (typeof WebSocket !== "undefined" ? WebSocket : null);
    // Injectable for tests.
    this._timers = opts.timers || {
      setTimeout: function (fn, ms) { return setTimeout(fn, ms); },
      clearTimeout: function (id) { clearTimeout(id); },
    };
    this._random = opts.random || Math.random;
    this._log = opts.logger || console;

    this.state = {
      connected: false,
      iracingConnected: null,
      clients: null,
      driverName: null,
      sectorCount: null,
      snapshot: null,
      lastSeq: null,
    };

    this._handlers = {};
    this._ws = null;
    this._wantOpen = false;
    this._attempt = 0;
    this._reconnectTimer = null;
    this._resyncing = false;
  }

  // ---- events ---------------------------------------------------------

  LetClient.prototype.on = function (type, handler) {
    (this._handlers[type] = this._handlers[type] || []).push(handler);
    var self = this;
    return function () { self.off(type, handler); };
  };

  LetClient.prototype.off = function (type, handler) {
    var list = this._handlers[type];
    if (!list) return;
    var i = list.indexOf(handler);
    if (i >= 0) list.splice(i, 1);
  };

  LetClient.prototype._emit = function (type, data, msg) {
    var list = (this._handlers[type] || []).slice();
    for (var i = 0; i < list.length; i++) {
      try {
        list[i](data, msg);
      } catch (err) {
        this._log.error("IRLDS handler for " + type + " threw", err);
      }
    }
  };

  // ---- connection -----------------------------------------------------

  LetClient.prototype.connect = function () {
    this._wantOpen = true;
    if (this._ws) return;
    this._clearReconnectTimer();
    this._open();
  };

  LetClient.prototype.close = function () {
    this._wantOpen = false;
    this._clearReconnectTimer();
    var ws = this._ws;
    if (ws) {
      try { ws.close(1000); } catch (e) { /* ignore */ }
    }
  };

  LetClient.prototype._open = function () {
    var self = this;
    var ws;
    try {
      ws = new this.WebSocketImpl(this.url);
    } catch (err) {
      this._log.warn("IRLDS connect failed", err);
      this._scheduleReconnect();
      return;
    }
    this._ws = ws;

    ws.onopen = function () {
      if (self._ws !== ws) return;
      self._attempt = 0;
      self._resyncing = false;
      // Server seq may have restarted; rebuild from the hello + snapshot that follow.
      self.state.lastSeq = null;
      self.state.connected = true;
      self._emit("open", {});
    };
    ws.onmessage = function (ev) {
      if (self._ws !== ws) return;
      self._handleRaw(ev.data);
    };
    ws.onerror = function () { /* a close event follows */ };
    ws.onclose = function (ev) {
      if (self._ws !== ws) return;
      self._ws = null;
      var wasConnected = self.state.connected;
      self.state.connected = false;
      self._resyncing = false;
      self._emit("close", { code: ev && ev.code, reason: ev && ev.reason, wasConnected: wasConnected });
      if (self._wantOpen) self._scheduleReconnect();
    };
  };

  LetClient.prototype.nextDelay = function () {
    var r = this.reconnect;
    var base = Math.min(r.maxMs, r.minMs * Math.pow(r.factor, this._attempt));
    var jitter = base * r.jitter * (2 * this._random() - 1);
    return Math.max(0, Math.round(base + jitter));
  };

  LetClient.prototype._scheduleReconnect = function () {
    if (!this._wantOpen || this._reconnectTimer !== null) return;
    var self = this;
    var delay = this.nextDelay();
    this._attempt++;
    this._reconnectTimer = this._timers.setTimeout(function () {
      self._reconnectTimer = null;
      if (self._wantOpen && !self._ws) self._open();
    }, delay);
  };

  LetClient.prototype._clearReconnectTimer = function () {
    if (this._reconnectTimer !== null) {
      this._timers.clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
  };

  // ---- incoming -------------------------------------------------------

  LetClient.prototype._handleRaw = function (raw) {
    var msg;
    try {
      msg = JSON.parse(raw);
    } catch (err) {
      this._log.warn("IRLDS: ignoring non-JSON message", raw);
      return;
    }
    if (!msg || typeof msg !== "object" || typeof msg.type !== "string") {
      this._log.warn("IRLDS: ignoring message without type", raw);
      return;
    }
    this.handleMessage(msg);
  };

  /** Process one decoded envelope. Exposed for tests and custom transports. */
  LetClient.prototype.handleMessage = function (msg) {
    var st = this.state;
    var data = msg.data && typeof msg.data === "object" ? msg.data : {};
    var seq = typeof msg.seq === "number" ? msg.seq : null;

    if (msg.type === "snapshot") {
      if (seq !== null && st.lastSeq !== null && seq <= st.lastSeq) return; // stale broadcast
      var asOf = typeof data.as_of_seq === "number" ? data.as_of_seq : null;
      var next = asOf;
      if (seq !== null) next = next === null ? seq : Math.max(next, seq);
      if (next !== null) st.lastSeq = next;
      this._resyncing = false;
    } else if (seq !== null) {
      if (st.lastSeq !== null) {
        if (seq <= st.lastSeq) return; // stale or duplicate
        if (seq > st.lastSeq + 1) {
          this._emit("gap", { expected: st.lastSeq + 1, received: seq });
          if (!this._resyncing) {
            this._resyncing = true;
            this.getSnapshot();
          }
        }
      }
      st.lastSeq = seq;
    }

    switch (msg.type) {
      case "hello":
        st.iracingConnected = data.iracing_connected;
        st.clients = data.clients;
        st.driverName = data.driver_name;
        st.sectorCount = data.sector_count;
        break;
      case "snapshot":
        st.snapshot = Object.assign({}, data);
        st.driverName = data.driver_name;
        st.sectorCount = data.sector_count;
        if ("iracing_connected" in data) st.iracingConnected = data.iracing_connected;
        if ("clients" in data) st.clients = data.clients;
        break;
      case "status":
        st.iracingConnected = data.iracing_connected;
        st.clients = data.clients;
        if (st.snapshot) {
          st.snapshot.iracing_connected = data.iracing_connected;
          st.snapshot.clients = data.clients;
        }
        break;
      case "sector_update":
        st.driverName = data.driver_name;
        if (st.snapshot) {
          st.snapshot.driver_name = data.driver_name;
          st.snapshot.current_lap_sectors = data.current_lap_sectors;
          st.snapshot.best_sector_times = data.best_sector_times;
          st.snapshot.optimal_lap_time = data.optimal_lap_time;
        }
        break;
      case "lap_update":
        st.driverName = data.driver_name;
        if (st.snapshot) {
          var lap = {
            driver_name: data.driver_name,
            lap_number: data.lap_number,
            lap_time: data.lap_time,
            sectors: data.sectors,
            valid: data.valid,
          };
          var s = st.snapshot;
          s.driver_name = data.driver_name;
          s.last_lap = lap;
          s.lap_count = (s.lap_count || 0) + 1;
          s.current_lap = data.current_lap;
          s.current_lap_sectors = [];
          s.best_sector_times = data.best_sector_times;
          s.optimal_lap_time = data.optimal_lap_time;
          s.best_lap_number = data.best_lap_number;
          if (data.valid && data.best_lap_number === data.lap_number) s.best_lap = lap;
        }
        break;
      case "reset_ack":
      case "pit_ack":
      case "pong":
      case "error":
        break;
      default:
        return; // unknown types are ignored
    }
    this._emit(msg.type, data, msg);
  };

  // ---- commands -------------------------------------------------------

  LetClient.prototype._send = function (type, data) {
    var ws = this._ws;
    if (!ws || !this.state.connected || (ws.readyState !== undefined && ws.readyState !== OPEN)) {
      // Never queue: a stale reset replayed later could hit the wrong driver.
      this._emit("error", { code: "not_connected", message: "not connected to IRLDS", request_type: type });
      return false;
    }
    ws.send(JSON.stringify({ type: type, data: data || {} }));
    return true;
  };

  LetClient.prototype.reset = function (driverName) {
    return this._send("reset", { driver_name: driverName });
  };

  LetClient.prototype.returnToPits = function () {
    return this._send("return_to_pits", {});
  };

  LetClient.prototype.getSnapshot = function () {
    return this._send("get_snapshot", {});
  };

  LetClient.prototype.ping = function () {
    return this._send("ping", {});
  };

  LetClient.EVENTS = EVENTS.slice();

  return { LetClient: LetClient };
});
