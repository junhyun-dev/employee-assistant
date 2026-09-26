(function (global) {
  "use strict";

  var DB_NAME = "employee-assistant-local-drafts";
  var DB_VERSION = 1;
  var STORE_NAME = "drafts";
  var RECORD_ID = "active-draft";
  var SCHEMA_VERSION = "employee-assistant.draft.v1";
  var INQUIRY_TYPE = "monitor_and_laptop_replacement";
  var TTL_MS = 24 * 60 * 60 * 1000;
  var opaqueGuards = new Map();
  var nextOpaqueGuard = 0;

  function storageError(code, message) {
    var error = new Error(message);
    error.code = code;
    return error;
  }

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function hasExactKeys(value, keys) {
    if (!isPlainObject(value)) return false;
    var actual = Object.keys(value).sort();
    var expected = keys.slice().sort();
    return actual.length === expected.length && actual.every(function (key, index) { return key === expected[index]; });
  }

  function isLimitedString(value, limit) {
    return typeof value === "string" && value.length <= limit;
  }

  function isValidRevision(value) {
    return Number.isSafeInteger(value) && value >= 1;
  }

  function parseTime(value) {
    if (typeof value !== "string") return NaN;
    var parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : NaN;
  }

  function validatePayload(payload) {
    if (!hasExactKeys(payload, ["inquiry_type", "employee_input", "drafts", "edit_meta", "ui"])) return false;
    if (payload.inquiry_type !== INQUIRY_TYPE) return false;
    if (!hasExactKeys(payload.employee_input, ["tenure", "symptom", "purchase"])) return false;
    if (!isLimitedString(payload.employee_input.tenure, 80)) return false;
    if (!isLimitedString(payload.employee_input.symptom, 500)) return false;
    if (!["", "not-purchased", "purchased", "unknown"].includes(payload.employee_input.purchase)) return false;
    if (!hasExactKeys(payload.drafts, ["monitor", "it"])) return false;
    if (!isLimitedString(payload.drafts.monitor, 12000) || !isLimitedString(payload.drafts.it, 12000)) return false;
    if (!hasExactKeys(payload.edit_meta, ["monitor_touched", "it_touched"])) return false;
    if (typeof payload.edit_meta.monitor_touched !== "boolean" || typeof payload.edit_meta.it_touched !== "boolean") return false;
    if (!hasExactKeys(payload.ui, ["mode", "active_draft"])) return false;
    if (!["conversation", "workflow"].includes(payload.ui.mode)) return false;
    if (!["monitor", "it"].includes(payload.ui.active_draft)) return false;
    return true;
  }

  function validateSnapshot(record) {
    if (!hasExactKeys(record, ["id", "kind", "schema_version", "revision", "saved_at", "expires_at", "payload"])) return false;
    if (record.id !== RECORD_ID || record.kind !== "snapshot" || record.schema_version !== SCHEMA_VERSION) return false;
    if (!isValidRevision(record.revision)) return false;
    var savedAt = parseTime(record.saved_at);
    var expiresAt = parseTime(record.expires_at);
    if (!Number.isFinite(savedAt) || !Number.isFinite(expiresAt) || expiresAt - savedAt !== TTL_MS) return false;
    return validatePayload(record.payload);
  }

  function validateTombstone(record) {
    return hasExactKeys(record, ["id", "kind", "schema_version", "revision", "updated_at"]) &&
      record.id === RECORD_ID && record.kind === "empty" && record.schema_version === SCHEMA_VERSION &&
      isValidRevision(record.revision) && Number.isFinite(parseTime(record.updated_at));
  }

  function safeRevision(record) {
    return record && isValidRevision(record.revision) ? record.revision : 0;
  }

  function metadata(record) {
    return {
      status: "available",
      revision: record.revision,
      saved_at: record.saved_at,
      expires_at: record.expires_at,
      opaque_token: null
    };
  }

  function emptyMetadata(revision, reason) {
    return {
      status: reason || "empty",
      revision: revision,
      saved_at: null,
      expires_at: null,
      opaque_token: null
    };
  }

  function tombstone(revision, now) {
    return {
      id: RECORD_ID,
      kind: "empty",
      schema_version: SCHEMA_VERSION,
      revision: revision,
      updated_at: new Date(now).toISOString()
    };
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function opaqueEqual(left, right, seen) {
    if (Object.is(left, right)) return true;
    if (typeof left !== typeof right || left === null || right === null || typeof left !== "object") return false;
    seen = seen || new Map();
    if (seen.has(left)) return seen.get(left) === right;
    seen.set(left, right);

    var leftTag = Object.prototype.toString.call(left);
    if (leftTag !== Object.prototype.toString.call(right)) return false;
    if (leftTag === "[object Date]") return left.getTime() === right.getTime();
    if (leftTag === "[object RegExp]") {
      return left.source === right.source && left.flags === right.flags && left.lastIndex === right.lastIndex;
    }
    if (leftTag === "[object ArrayBuffer]") {
      left = new Uint8Array(left);
      right = new Uint8Array(right);
    }
    if (ArrayBuffer.isView(left)) {
      if (!ArrayBuffer.isView(right) || left.constructor !== right.constructor || left.byteLength !== right.byteLength) return false;
      var leftBytes = new Uint8Array(left.buffer, left.byteOffset, left.byteLength);
      var rightBytes = new Uint8Array(right.buffer, right.byteOffset, right.byteLength);
      return leftBytes.every(function (value, index) { return value === rightBytes[index]; });
    }
    if (leftTag === "[object Blob]" || leftTag === "[object File]") {
      // Blob contents cannot be compared synchronously while keeping the IndexedDB
      // transaction active. This app never writes them, so an opaque record that
      // contains one stays protected instead of being deleted on a weak comparison.
      return false;
    }
    if (Array.isArray(left)) {
      if (left.length !== right.length) return false;
      var leftArrayKeys = Object.keys(left).sort();
      var rightArrayKeys = Object.keys(right).sort();
      return leftArrayKeys.length === rightArrayKeys.length && leftArrayKeys.every(function (key, index) {
        return key === rightArrayKeys[index] && opaqueEqual(left[key], right[key], seen);
      });
    }
    if (leftTag === "[object Map]") {
      if (left.size !== right.size) return false;
      var leftEntries = Array.from(left.entries());
      var rightEntries = Array.from(right.entries());
      return leftEntries.every(function (entry, index) {
        return opaqueEqual(entry[0], rightEntries[index][0], seen) &&
          opaqueEqual(entry[1], rightEntries[index][1], seen);
      });
    }
    if (leftTag === "[object Set]") {
      if (left.size !== right.size) return false;
      var leftValues = Array.from(left.values());
      var rightValues = Array.from(right.values());
      return leftValues.every(function (value, index) {
        return opaqueEqual(value, rightValues[index], seen);
      });
    }
    if (leftTag !== "[object Object]") return false;
    var leftKeys = Object.keys(left).sort();
    var rightKeys = Object.keys(right).sort();
    return leftKeys.length === rightKeys.length && leftKeys.every(function (key, index) {
      return key === rightKeys[index] && opaqueEqual(left[key], right[key], seen);
    });
  }

  function rememberOpaqueRecord(record) {
    var token = "opaque-" + Date.now() + "-" + (++nextOpaqueGuard);
    opaqueGuards.set(token, record);
    if (opaqueGuards.size > 8) opaqueGuards.delete(opaqueGuards.keys().next().value);
    return token;
  }

  function unreadableReason(record) {
    return record && typeof record.schema_version === "string" && record.schema_version !== SCHEMA_VERSION
      ? "unsupported_schema"
      : "invalid_record";
  }

  function unreadableMetadata(current) {
    return {
      status: "unreadable",
      revision: current.revision,
      saved_at: null,
      expires_at: null,
      unreadable_reason: current.reason,
      opaque_token: rememberOpaqueRecord(current.record)
    };
  }

  function openDatabase() {
    return new Promise(function (resolve, reject) {
      if (!global.indexedDB) {
        reject(storageError("unavailable", "이 브라우저에서 임시 저장소를 사용할 수 없습니다."));
        return;
      }
      var request;
      try {
        request = global.indexedDB.open(DB_NAME, DB_VERSION);
      } catch (error) {
        reject(storageError("unavailable", "임시 저장소를 열 수 없습니다."));
        return;
      }
      request.onupgradeneeded = function () {
        var db = request.result;
        if (!db.objectStoreNames.contains(STORE_NAME)) db.createObjectStore(STORE_NAME, { keyPath: "id" });
      };
      request.onsuccess = function () { resolve(request.result); };
      request.onerror = function () { reject(storageError("unavailable", "임시 저장소를 열 수 없습니다.")); };
      request.onblocked = function () { reject(storageError("blocked", "다른 탭이 저장소 변경을 막고 있습니다.")); };
    });
  }

  async function transact(handler) {
    var db = await openDatabase();
    return new Promise(function (resolve, reject) {
      var tx;
      var result;
      var failed = false;
      try {
        tx = db.transaction(STORE_NAME, "readwrite");
      } catch (error) {
        db.close();
        reject(storageError("unavailable", "임시 저장 작업을 시작할 수 없습니다."));
        return;
      }
      var store = tx.objectStore(STORE_NAME);
      var request = store.get(RECORD_ID);
      request.onsuccess = function () {
        try {
          result = handler(request.result, store);
        } catch (error) {
          failed = true;
          try { tx.abort(); } catch (abortError) { /* transaction is already stopping */ }
          reject(error && typeof error.code === "string"
            ? error
            : storageError("write_failed", "임시 저장 작업이 완료되지 않았습니다."));
        }
      };
      request.onerror = function () {
        failed = true;
        reject(storageError("read_failed", "임시 저장본을 읽지 못했습니다."));
      };
      tx.oncomplete = function () {
        db.close();
        if (!failed) resolve(result);
      };
      tx.onabort = function () {
        db.close();
        if (!failed) reject(storageError("write_failed", "임시 저장 작업이 완료되지 않았습니다."));
      };
      tx.onerror = function () {
        if (!failed) {
          failed = true;
          db.close();
          reject(storageError("write_failed", "임시 저장 작업이 완료되지 않았습니다."));
        }
      };
    });
  }

  function classifyRecord(record, now) {
    if (!record) return { kind: "empty", revision: 0, reason: "empty" };
    if (validateTombstone(record)) return { kind: "empty", revision: record.revision, reason: "empty" };
    if (!validateSnapshot(record)) {
      return {
        kind: "unreadable",
        revision: safeRevision(record),
        reason: unreadableReason(record),
        record: record
      };
    }
    if (parseTime(record.expires_at) <= now) {
      return { kind: "expired", revision: record.revision, reason: "expired", record: record };
    }
    return { kind: "snapshot", revision: record.revision, record: record };
  }

  function expireRecord(current, store, now) {
    var nextRevision = current.revision + 1;
    store.put(tombstone(nextRevision, now));
    return { kind: "empty", revision: nextRevision, reason: "expired" };
  }

  function ensureExpected(actualRevision, expectedRevision) {
    if (!Number.isSafeInteger(expectedRevision) || expectedRevision < 0) {
      throw storageError("invalid", "저장본 판본이 올바르지 않습니다.");
    }
    if (actualRevision !== expectedRevision) {
      throw storageError("conflict", "다른 탭에서 임시 저장본이 먼저 바뀌었습니다.");
    }
  }

  function inspect() {
    var now = Date.now();
    return transact(function (record, store) {
      var current = classifyRecord(record, now);
      if (current.kind === "unreadable") return unreadableMetadata(current);
      if (current.kind === "expired") current = expireRecord(current, store, now);
      return current.kind === "snapshot" ? metadata(current.record) : emptyMetadata(current.revision, current.reason);
    });
  }

  function save(expectedRevision, payload) {
    if (!validatePayload(payload)) return Promise.reject(storageError("invalid", "저장할 문의 내용의 형식이 올바르지 않습니다."));
    var now = Date.now();
    return transact(function (record, store) {
      var current = classifyRecord(record, now);
      if (current.kind === "unreadable") throw storageError("unreadable", "읽을 수 없는 저장본이 남아 있습니다.");
      if (current.kind === "expired") {
        current = expireRecord(current, store, now);
        return { error: storageError("expired", "24시간이 지난 저장본을 삭제했습니다.") };
      }
      ensureExpected(current.revision, expectedRevision);
      var next = {
        id: RECORD_ID,
        kind: "snapshot",
        schema_version: SCHEMA_VERSION,
        revision: current.revision + 1,
        saved_at: new Date(now).toISOString(),
        expires_at: new Date(now + TTL_MS).toISOString(),
        payload: clone(payload)
      };
      store.put(next);
      return { metadata: metadata(next) };
    }).then(function (result) {
      if (result.error) throw result.error;
      return result.metadata;
    });
  }

  function load(expectedRevision) {
    var now = Date.now();
    return transact(function (record, store) {
      var current = classifyRecord(record, now);
      if (current.kind === "unreadable") throw storageError("unreadable", "읽을 수 없는 저장본은 불러올 수 없습니다.");
      if (current.kind === "expired") {
        current = expireRecord(current, store, now);
        return { error: storageError("expired", "24시간이 지난 저장본을 삭제했습니다.") };
      }
      ensureExpected(current.revision, expectedRevision);
      if (current.kind !== "snapshot") throw storageError(current.reason, "불러올 수 있는 임시 저장본이 없습니다.");
      return { value: { metadata: metadata(current.record), payload: clone(current.record.payload) } };
    }).then(function (result) {
      if (result.error) throw result.error;
      return result.value;
    });
  }

  function remove(expectedRevision, opaqueToken) {
    var now = Date.now();
    return transact(function (record, store) {
      var current = classifyRecord(record, now);
      if (current.kind === "unreadable") {
        if (!opaqueToken || !opaqueGuards.has(opaqueToken) ||
            !opaqueEqual(current.record, opaqueGuards.get(opaqueToken))) {
          throw storageError("conflict", "확인한 뒤 저장본의 내용이 바뀌었습니다.");
        }
        ensureExpected(current.revision, expectedRevision);
        var opaqueRevision = current.revision + 1;
        store.put(tombstone(opaqueRevision, now));
        opaqueGuards.delete(opaqueToken);
        return { metadata: emptyMetadata(opaqueRevision, "empty") };
      }
      if (opaqueToken) throw storageError("conflict", "확인한 뒤 저장본의 내용이 바뀌었습니다.");
      if (current.kind === "expired") {
        current = expireRecord(current, store, now);
        return { error: storageError("expired", "24시간이 지난 저장본을 삭제했습니다.") };
      }
      ensureExpected(current.revision, expectedRevision);
      if (current.kind !== "snapshot") throw storageError("empty", "삭제할 임시 저장본이 없습니다.");
      var nextRevision = current.revision + 1;
      store.put(tombstone(nextRevision, now));
      return { metadata: emptyMetadata(nextRevision, "empty") };
    }).then(function (result) {
      if (result.error) throw result.error;
      return result.metadata;
    });
  }

  global.EmployeeAssistantDraftStore = {
    inspect: inspect,
    save: save,
    load: load,
    remove: remove
  };
})(window);
