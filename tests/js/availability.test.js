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

test("'לא זמין/ה' clears the day, marks it, and a second click only unmarks it (shifts stay cleared)", () => {
  const start = { "2026-11-29|1": true, "2026-11-29|2": true, "2026-11-30|1": true };
  const r = M.toggleOff(start, {}, SUN);
  eq(M.toSlots(r.sel), [{ day: MON, shift_id: 1 }]); eq(r.off, { [SUN]: true }); eq(M.isOff(r.off, SUN), true);
  eq(start, { "2026-11-29|1": true, "2026-11-29|2": true, "2026-11-30|1": true }, "input must not be mutated");
  const again = M.toggleOff(r.sel, r.off, SUN);
  eq(again.off, {}); eq(M.toSlots(again.sel), [{ day: MON, shift_id: 1 }]);
});

test("'כל המשמרות' resets an unavailable day and selects every shift of it", () => {
  const off = M.toggleOff({}, {}, SUN);
  const r = M.selectAllDay(off.sel, off.off, SUN, SHIFTS);
  eq(r.off, {}); eq(M.toSlots(r.sel), [{ day: SUN, shift_id: 1 }, { day: SUN, shift_id: 2 }]);
  const other = M.selectAllDay({}, { [MON]: true }, SUN, SHIFTS);
  eq(other.off, { [MON]: true }, "other days keep their state");
});

test("saved unavailable days are loaded as they were saved; an empty day is never assumed unavailable", () => {
  eq(M.offFromDays(["2026-12-01", "2026-12-04"]), { "2026-12-01": true, "2026-12-04": true });
  eq(M.offFromDays([]), {}); eq(M.offFromDays(undefined), {});
  const days = ["2026-11-29", "2026-11-30", "2026-12-01"];
  const sel = M.fromSlots([{ day: "2026-11-29", shift_id: 1 }]);
  eq(M.missingDays(sel, M.offFromDays([]), days), ["2026-11-30", "2026-12-01"], "a legacy submission: the empty days still need a choice");
});

test("every day needs a choice: missing days are the days with neither a shift nor an explicit 'unavailable'", () => {
  const days = ["2026-11-29", "2026-11-30", "2026-12-01", "2026-12-02"];
  let sel = {}, off = {};
  eq(M.missingDays(sel, off, days), days);
  sel = M.toggle(sel, "2026-11-29", 1);                              // a shift
  off = M.toggleOff(sel, off, "2026-12-01").off;                     // explicit unavailable
  eq(M.missingDays(sel, off, days), ["2026-11-30", "2026-12-02"]);
  const r = M.toggleOff(sel, off, "2026-12-01");                     // a second click: back to untouched, not unavailable
  eq(M.missingDays(r.sel, r.off, days), ["2026-11-30", "2026-12-01", "2026-12-02"]);
  const clearedShift = M.toggle(sel, "2026-11-29", 1, false);       // unticking the only shift leaves the day untouched
  eq(M.missingDays(clearedShift, off, days)[0], "2026-11-29");
  eq(M.missingDays(M.selectAllDay(sel, off, "2026-12-01", [{ id: 1 }, { id: 2 }]).sel, M.selectAllDay(sel, off, "2026-12-01", [{ id: 1 }]).off, days), ["2026-11-30", "2026-12-02"]);
});

test("the unavailable days sent to the server are the marked days of the week, in week order", () => {
  const days = ["2026-11-29", "2026-11-30", "2026-12-01"];
  eq(M.unavailableList({ "2026-12-01": true, "2026-11-29": true, "2027-01-01": true }, days), ["2026-11-29", "2026-12-01"]);
  eq(M.unavailableList({}, days), []);
});

test("changing only the unavailable days makes the form dirty; identical sets do not", () => {
  const saved = { sel: M.fromSlots([{ day: SUN, shift_id: 1 }]), text: "", off: { [MON]: true } };
  eq(M.isDirty(saved.sel, "", saved, { [MON]: true }), false);
  eq(M.isDirty(saved.sel, "", saved, {}), true);
  eq(M.isDirty(saved.sel, "", saved, { [MON]: true, "2026-12-01": true }), true);
  eq(M.isDirty(saved.sel, "", { sel: saved.sel, text: "" }, {}), false, "no saved off set equals none");
});

test("approved leave dates are grouped into consecutive ranges", () => {
  eq(M.groupDates(["2026-12-02", "2026-12-01", "2026-12-04"]), [{ start: "2026-12-01", end: "2026-12-02" }, { start: "2026-12-04", end: "2026-12-04" }]);
  eq(M.groupDates(["2026-11-30", "2026-12-01"]), [{ start: "2026-11-30", end: "2026-12-01" }], "across a month boundary");
  eq(M.groupDates(["2026-12-01", "2026-12-01"]), [{ start: "2026-12-01", end: "2026-12-01" }]);
  eq(M.groupDates([]), []); eq(M.groupDates(null), []);
});

test("status filters: total shows everyone, leave shows only full-week exempt employees, order is kept", () => {
  const e = [{ id: 1, status: "submitted", leave_dates: ["2026-12-01"] }, { id: 2, status: "missing" }, { id: 3, status: "exempt" }, { id: 4, status: "submitted" }, { id: 5, status: "missing" }];
  eq(M.filterEmployees(e, "total").map((x) => x.id), [1, 2, 3, 4, 5]);
  eq(M.filterEmployees(e, "submitted").map((x) => x.id), [1, 4]);
  eq(M.filterEmployees(e, "missing").map((x) => x.id), [2, 5]);
  eq(M.filterEmployees(e, "leave").map((x) => x.id), [3], "partial leave (employee 1) never appears under leave");
  eq(M.filterEmployees(e, "nonsense").map((x) => x.id), [1, 2, 3, 4, 5]);
  eq(M.filterEmployees([], "leave"), []);
  const input = e.slice(); M.filterEmployees(input, "missing"); eq(input.length, 5, "the input is not mutated");
});

console.log((count - failures) + "/" + count + " availability tests passed");
process.exit(failures ? 1 : 0);
