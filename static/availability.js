/* The availability form's selection model: pure functions, no DOM, so they can be tested under node.

   A selection is a plain object whose keys are "YYYY-MM-DD|shiftId" and whose values are true. Every function
   returns a NEW object; nothing mutates its input. The per-day shortcuts are only functions over the selection
   ("select every shift of a day", "clear a day"): they hold no state of their own, so editing a single checkbox
   afterwards simply changes the selection again and the display always follows it. */
(function (root) {
  "use strict";

  var TEXT_MAX = 1000;

  function key(day, shiftId) { return day + "|" + shiftId; }

  function fromSlots(slots) {
    var sel = {};
    (slots || []).forEach(function (s) { sel[key(s.day, s.shift_id)] = true; });
    return sel;
  }

  function toSlots(sel) {
    return Object.keys(sel).filter(function (k) { return sel[k]; }).map(function (k) {
      var p = k.split("|");
      return { day: p[0], shift_id: parseInt(p[1], 10) };
    }).sort(function (a, b) { return a.day < b.day ? -1 : a.day > b.day ? 1 : a.shift_id - b.shift_id; });
  }

  function copy(sel) { var out = {}; Object.keys(sel).forEach(function (k) { if (sel[k]) out[k] = true; }); return out; }

  function has(sel, day, shiftId) { return !!sel[key(day, shiftId)]; }

  function toggle(sel, day, shiftId, on) {
    var out = copy(sel), k = key(day, shiftId);
    var want = on === undefined ? !out[k] : !!on;
    if (want) out[k] = true; else delete out[k];
    return out;
  }

  function selectAll(sel, day, shifts) {
    var out = copy(sel);
    shifts.forEach(function (s) { out[key(day, s.id)] = true; });
    return out;
  }

  function clearDay(sel, day) {
    var out = copy(sel), prefix = day + "|";
    Object.keys(out).forEach(function (k) { if (k.indexOf(prefix) === 0) delete out[k]; });
    return out;
  }

  function countDay(sel, day) {
    var prefix = day + "|";
    return Object.keys(sel).filter(function (k) { return sel[k] && k.indexOf(prefix) === 0; }).length;
  }

  function count(sel) { return Object.keys(sel).filter(function (k) { return sel[k]; }).length; }

  function dayState(sel, day, shifts) {
    var n = shifts.filter(function (s) { return has(sel, day, s.id); }).length;
    return n === 0 ? "none" : n === shifts.length ? "all" : "some";
  }

  function equal(a, b) {
    var ka = Object.keys(a).filter(function (k) { return a[k]; }).sort(), kb = Object.keys(b).filter(function (k) { return b[k]; }).sort();
    return ka.length === kb.length && ka.every(function (k, i) { return k === kb[i]; });
  }

  /* Characters as the server counts them (code points, after trimming). */
  function textLength(text) {
    return Array.from(String(text || "").replace(/\r\n?/g, "\n").trim()).length;
  }

  /* Problems that stop a save: [] means it can be sent. The server repeats every check. */
  function problems(sel, text) {
    var out = [];
    if (count(sel) === 0) out.push("no_slots");
    if (textLength(text) > TEXT_MAX) out.push("text_too_long");
    return out;
  }

  function isDirty(sel, text, saved) {
    return !equal(sel, saved.sel) || String(text || "").trim() !== String(saved.text || "").trim();
  }

  function splitDuration(totalSeconds) {
    var s = Math.max(0, Math.floor(totalSeconds));
    return { days: Math.floor(s / 86400), hours: Math.floor((s % 86400) / 3600), minutes: Math.floor((s % 3600) / 60) };
  }

  var api = { TEXT_MAX: TEXT_MAX, key: key, fromSlots: fromSlots, toSlots: toSlots, has: has, toggle: toggle, selectAll: selectAll,
              clearDay: clearDay, countDay: countDay, count: count, dayState: dayState, equal: equal, textLength: textLength,
              problems: problems, isDirty: isDirty, splitDuration: splitDuration };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.AvailabilityModel = api;
})(typeof window !== "undefined" ? window : globalThis);
