/* Tests for static/markdown.js. Run with:  node tests/js/markdown.test.js
   (tests/test_js_renderer.py runs this in CI.) Works with a tiny fake DOM, so no dependencies. */
"use strict";
const MD = require("../../static/markdown.js");

// ---- a minimal DOM: elements, text nodes, fragments, and a serializer that escapes text ----
class TextNode { constructor(t) { this.nodeType = 3; this.data = String(t); } }
class El {
  constructor(tag) { this.nodeType = 1; this.tagName = tag.toUpperCase(); this.attrs = {}; this.children = []; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  appendChild(c) {
    if (c.nodeType === 11) { c.children.forEach((x) => this.children.push(x)); c.children = []; } else this.children.push(c);
    return c;
  }
}
const doc = {
  createElement: (t) => new El(t),
  createTextNode: (t) => new TextNode(t),
  createDocumentFragment: () => { const f = new El("#fragment"); f.nodeType = 11; return f; },
};
const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
function ser(n) {
  if (n.nodeType === 3) return esc(n.data);
  const attrs = Object.entries(n.attrs).map(([k, v]) => ` ${k}="${esc(v)}"`).join("");
  return `<${n.tagName.toLowerCase()}${attrs}>${n.children.map(ser).join("")}</${n.tagName.toLowerCase()}>`;
}
const html = (md, opts) => MD.render(md, doc, opts).children.map(ser).join("");

function walk(n, fn) { fn(n); (n.children || []).forEach((c) => walk(c, fn)); }
const ALLOWED_ATTRS = new Set(["dir", "class", "role", "tabindex", "aria-label", "scope"]);
function assertSafe(md) {
  const frag = MD.render(md, doc, { tableLabel: "t" });
  walk(frag, (n) => {
    if (n.nodeType !== 1 || n.tagName === "#FRAGMENT") return;
    if (!MD.ALLOWED_TAGS.includes(n.tagName)) throw new Error(`tag ${n.tagName} is not allowed (input: ${JSON.stringify(md).slice(0, 80)})`);
    Object.keys(n.attrs).forEach((a) => { if (!ALLOWED_ATTRS.has(a)) throw new Error(`attribute ${a} is not allowed`); });
  });
  const out = frag.children.map(ser).join("");
  if (/<(script|img|iframe|a|svg|style|object|embed|link|form|input)\b/i.test(out)) throw new Error(`dangerous tag in output: ${out.slice(0, 120)}`);
}

let failures = 0, count = 0;
function test(name, fn) {
  count++;
  try { fn(); } catch (e) { failures++; console.error(`FAIL ${name}: ${e.message}`); }
}
function eq(a, b, msg) { if (a !== b) throw new Error(`${msg || "mismatch"}\n  got:  ${a}\n  want: ${b}`); }
function has(s, sub) { if (!s.includes(sub)) throw new Error(`expected ${JSON.stringify(sub)} in ${s}`); }
function hasNot(s, sub) { if (s.includes(sub)) throw new Error(`did not expect ${JSON.stringify(sub)} in ${s}`); }

test("paragraphs split on blank lines; a single newline is a line break", () => {
  eq(html("one\ntwo\n\nthree"), '<p dir="auto">one<br></br>two</p><p dir="auto">three</p>');
});

test("bold works in Hebrew and English, mixed", () => {
  eq(html("**שלום** world"), '<p dir="auto"><strong>שלום</strong> world</p>');
  eq(html("סך הכל: **12** משמרות / **3 gaps**"), '<p dir="auto">סך הכל: <strong>12</strong> משמרות / <strong>3 gaps</strong></p>');
});

test("an unmatched ** stays literal", () => {
  eq(html("2 ** 3 and **open"), '<p dir="auto">2 ** 3 and **open</p>');
});

test("bullet and numbered lists", () => {
  eq(html("- א\n- ב\n* ג"), '<ul><li dir="auto">א</li><li dir="auto">ב</li><li dir="auto">ג</li></ul>');
  eq(html("1. one\n2) two"), '<ol><li dir="auto">one</li><li dir="auto">two</li></ol>');
});

test("a list ends at a blank line and a following paragraph is separate", () => {
  eq(html("- a\n\ntext"), '<ul><li dir="auto">a</li></ul><p dir="auto">text</p>');
});

test("tables render with header, body and a keyboard-scrollable region", () => {
  const out = html("| יום | משמרת |\n|---|---|\n| ראשון | בוקר |\n| שני | ערב |", { tableLabel: "טבלה" });
  has(out, '<div class="md-table" role="region" tabindex="0" aria-label="טבלה">');
  has(out, '<th dir="auto" scope="col">יום</th>');
  has(out, '<td dir="auto">ראשון</td>');
  eq((out.match(/<tr>/g) || []).length, 3);
});

test("table rows are padded or trimmed to the header width; cells are escaped", () => {
  const out = html("a | b\n--|--\n1 |\n2 | <b>x</b> | 4");
  eq((out.match(/<td /g) || []).length, 4);
  has(out, "&lt;b&gt;x");
});

test("headings degrade to a bold paragraph", () => {
  eq(html("## Title"), '<p dir="auto"><strong>Title</strong></p>');
});

test("HTML, links and images are plain text, never elements", () => {
  const payloads = [
    "<script>alert(1)</script>",
    '<img src=x onerror="alert(1)">',
    "[click me](javascript:alert(1))",
    "![pic](http://evil.example/x.png)",
    '<a href="javascript:alert(1)">x</a>',
    "**<b onmouseover=alert(1)>bold</b>**",
    "<iframe src=//evil></iframe>",
    "<svg/onload=alert(1)>",
    "| <img src=x onerror=alert(1)> | b |\n|---|---|\n| <script>x</script> | y |",
    "- <style>*{display:none}</style>",
  ];
  payloads.forEach((p) => {
    assertSafe(p);
    const out = html(p);
    hasNot(out, "<script"); hasNot(out, "<img"); hasNot(out, "<iframe"); hasNot(out, "<svg"); hasNot(out, "<a ");
    hasNot(out, 'href="'); hasNot(out, 'src="');  // attributes; the words may still appear as escaped text
  });
  has(html("<script>alert(1)</script>"), "&lt;script&gt;alert(1)&lt;/script&gt;");
  has(html("[click me](javascript:alert(1))"), "[click me](javascript:alert(1))");
});

test("every block carries dir=auto so mixed Hebrew and English reads correctly", () => {
  const out = html("Hebrew עברית 123\n\n- item\n\n| h |\n|---|\n| c |");
  has(out, '<p dir="auto">'); has(out, '<li dir="auto">'); has(out, '<th dir="auto"'); has(out, '<td dir="auto">');
});

test("very long input is truncated", () => {
  const out = html("a".repeat(MD.MAX_CHARS * 2));
  if (out.length > MD.MAX_CHARS + 200) throw new Error("not truncated");
  has(out, "…");
});

test("a pipe line followed by a dash line that is not a table terminates and stays text", () => {
  // regression: this input once made the parser loop forever
  ["x|\n---", "a|\n--", "|\n-", "x|\n---\ny"].forEach((s) => { assertSafe(s); has(html(s), "<p"); });
});

test("empty and odd inputs do not throw", () => {
  [null, undefined, "", "\n\n", "|", "|||", "---", "- ", "1.", "**", "\\*\\*x\\*\\*", "\r\n\r\n"].forEach((x) => { assertSafe(x); });
  eq(html("\\*\\*not bold\\*\\*"), '<p dir="auto">**not bold**</p>');
});

test("fuzz: whatever the input, only allowed tags and attributes come out", () => {
  let seed = 12345;
  const rnd = () => (seed = (seed * 1664525 + 1013904223) % 4294967296) / 4294967296;
  const alphabet = ["*", "**", "|", "-", "\n", "\n\n", "<", ">", "&", '"', "'", "#", " ", "1.", "- ", "|-|", "<script>", "javascript:", "](", "[", "א", "b", "0", "\\", "\r"];
  for (let i = 0; i < 3000; i++) {
    let s = "";
    const n = 1 + Math.floor(rnd() * 40);
    for (let j = 0; j < n; j++) s += alphabet[Math.floor(rnd() * alphabet.length)];
    assertSafe(s);
  }
});

console.log(`${count - failures}/${count} markdown tests passed`);
process.exit(failures ? 1 : 0);
