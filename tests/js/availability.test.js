/* Tests for static/availability.js. Run with:  node tests/js/availability.test.js  (tests/test_js_renderer.py runs it in CI) */
"use strict";
const M = require("../../static/availability.js");

let failures = 0, count = 0;
function test(name, fn) { count++; try { fn(); } catch (e) { failures++; console.error("FAIL " + name + ": " + e.message); } }
function eq(a, b, msg) { const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) throw new Error((msg || "mismatch") + "\n  got:  " + x + "\n  want: " + y); }

const SHIFTS = [{ id: 1, name: "בוקר" }, { id: 2, name: "ערב" }];
const SUN = "2026-11-29", MON = "2026-11-30";

test("toggling a checkbox adds and removes one slot, without mutating the input", () => {
  const a = {};
  const b = M.toggle(a, SUN, 1);
  eq(a, {}); eq(b, { "2026-11-29|1": true });
  eq(M.toggle(b, SUN, 1), {});
  eq(M.toggle(b, SUN, 1, true), b);               // an explicit "on" never turns it off
});

test("'כל המשמרות' selects every shift of that day only", () => {
  const sel = M.selectAll({ "2026-11-30|2": true }, SUN, SHIFTS);
  eq(M.toSlots(sel), [{ day: SUN, shift_id: 1 }, { day: SUN, shift_id: 2 }, { day: MON, shift_id: 2 }]);
  eq(M.dayState(sel, SUN, SHIFTS), "all"); eq(M.dayState(sel, MON, SHIFTS), "some");
});

test("'לא זמין/ה' clears every shift of that day only", () => {
  const sel = M.clearDay({ "2026-11-29|1": true, "2026-11-29|2": true, "2026-11-30|1": true }, SUN);
  eq(M.toSlots(sel), [{ day: MON, shift_id: 1 }]);
  eq(M.dayState(sel, SUN, SHIFTS), "none");
});

test("the shortcuts hold no state: a single checkbox edit afterwards is reflected exactly", () => {
  let sel = M.selectAll({}, SUN, SHIFTS);
  sel = M.toggle(sel, SUN, 2, false);              // untick the evening after "כל המשמרות"
  eq(M.dayState(sel, SUN, SHIFTS), "some"); eq(M.toSlots(sel), [{ day: SUN, shift_id: 1 }]);
  sel = M.clearDay(sel, SUN);
  sel = M.toggle(sel, SUN, 2);                      // tick one after "לא זמין/ה"
  eq(M.toSlots(sel), [{ day: SUN, shift_id: 2 }]); eq(M.countDay(sel, SUN), 1);
  sel = M.selectAll(sel, SUN, SHIFTS);              // idempotent
  eq(M.count(sel), 2);
});

test("slots round trip and sort by day then numeric shift id", () => {
  const slots = [{ day: MON, shift_id: 10 }, { day: SUN, shift_id: 9 }, { day: SUN, shift_id: 10 }, { day: SUN, shift_id: 2 }];
  eq(M.toSlots(M.fromSlots(slots)), [{ day: SUN, shift_id: 2 }, { day: SUN, shift_id: 9 }, { day: SUN, shift_id: 10 }, { day: MON, shift_id: 10 }]);
  eq(M.toSlots(M.fromSlots(null)), []);
});

test("zero selected shifts is a problem; so is text over 1,000 characters, counted as code points", () => {
  eq(M.problems({}, ""), ["no_slots"]);
  eq(M.problems({ "2026-11-29|1": true }, "א".repeat(1000)), []);
  eq(M.problems({ "2026-11-29|1": true }, "א".repeat(1001)), ["text_too_long"]);
  eq(M.problems({ "2026-11-29|1": true }, "  " + "ב".repeat(1000) + "  "), []);   // trimmed first, like the server
  eq(M.textLength("😀".repeat(1000)), 1000);                                           // one code point each, not two UTF-16 units
  eq(M.problems({}, "א".repeat(1001)), ["no_slots", "text_too_long"]);
});

test("dirty tracking compares selection and trimmed text with the saved values", () => {
  const saved = { sel: M.fromSlots([{ day: SUN, shift_id: 1 }]), text: "שלום" };
  eq(M.isDirty(M.fromSlots([{ day: SUN, shift_id: 1 }]), " שלום ", saved), false);
  eq(M.isDirty(M.fromSlots([{ day: SUN, shift_id: 2 }]), "שלום", saved), true);
  eq(M.isDirty(saved.sel, "שלום!", saved), true);
  eq(M.isDirty({}, "", { sel: {}, text: null }), false);
});

test("durations split into days, hours and minutes and never go negative", () => {
  eq(M.splitDuration(5 * 86400 + 13 * 3600 + 20 * 60 + 59), { days: 5, hours: 13, minutes: 20 });
  eq(M.splitDuration(59), { days: 0, hours: 0, minutes: 0 });
  eq(M.splitDuration(-5), { days: 0, hours: 0, minutes: 0 });
});

console.log((count - failures) + "/" + count + " availability tests passed");
process.exit(failures ? 1 : 0);
