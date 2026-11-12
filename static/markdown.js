/* A small, safe Markdown renderer for Copilot replies.

   Supports exactly: paragraphs (single newlines become line breaks), **bold**, bullet and numbered
   lists, and pipe tables. Everything else, including any HTML, links and images, is shown as plain
   text. Model output is untrusted, so:
   - text is only ever inserted with createTextNode, never as HTML;
   - elements are created only from a fixed allow-list (ALLOWED_TAGS) and carry only the fixed
     attributes set below (dir, class, role, tabindex, aria-label), never anything from the text;
   - there is no link, image or URL handling at all, so "javascript:" and "data:" have nothing to attach to.
   The parser (parse) is pure and DOM-free so it can be tested under node; render() builds nodes. */
(function (root) {
  "use strict";

  var MAX_CHARS = 20000;
  var ALLOWED_TAGS = ["P", "STRONG", "BR", "UL", "OL", "LI", "TABLE", "THEAD", "TBODY", "TR", "TH", "TD", "DIV"];

  var BULLET = /^\s{0,6}[-*•]\s+(.*)$/;
  var NUMBERED = /^\s{0,6}\d{1,3}[.)]\s+(.*)$/;
  var HEADING = /^\s{0,3}#{1,6}\s+(.*)$/;
  var TABLE_SEP = /^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$/;

  function parseInline(str) {
    // [{text}] and [{strong: [{text}]}]; an unmatched ** stays literal text.
    var out = [], i = 0, buf = "";
    function flush() { if (buf) { out.push({ text: buf }); buf = ""; } }
    while (i < str.length) {
      if (str.charAt(i) === "\\" && str.charAt(i + 1) === "*") { buf += "*"; i += 2; continue; }
      if (str.substr(i, 2) === "**" && /\S/.test(str.charAt(i + 2))) {
        // bold opens only before a non-space and closes at the next ** that follows a non-space ("2 ** 3" is not bold)
        var end = str.indexOf("**", i + 2);
        while (end > 0 && /\s/.test(str.charAt(end - 1))) end = str.indexOf("**", end + 2);
        if (end > i + 2) {
          flush();
          out.push({ strong: [{ text: str.slice(i + 2, end) }] });
          i = end + 2;
          continue;
        }
      }
      buf += str.charAt(i);
      i += 1;
    }
    flush();
    return out;
  }

  function splitRow(line) {
    var s = line.trim();
    if (s.charAt(0) === "|") s = s.slice(1);
    if (s.charAt(s.length - 1) === "|" && s.charAt(s.length - 2) !== "\\") s = s.slice(0, -1);
    var cells = [], cur = "";
    for (var i = 0; i < s.length; i++) {
      var ch = s.charAt(i);
      if (ch === "\\" && s.charAt(i + 1) === "|") { cur += "|"; i++; }
      else if (ch === "|") { cells.push(cur.trim()); cur = ""; }
      else cur += ch;
    }
    cells.push(cur.trim());
    return cells;
  }

  function startsBlock(line) {
    return BULLET.test(line) || NUMBERED.test(line) || HEADING.test(line);
  }

  // One definition of "a table starts here", used by both the table branch and the paragraph loop,
  // so the two can never disagree (a disagreement once meant a paragraph that consumed nothing).
  function isTableStart(lines, i) {
    return i + 1 < lines.length && lines[i].indexOf("|") >= 0 && TABLE_SEP.test(lines[i + 1]) && lines[i + 1].indexOf("-") >= 0
      && (lines[i + 1].indexOf("|") >= 0 || splitRow(lines[i]).length > 1);
  }

  function parse(text) {
    text = String(text == null ? "" : text).replace(/\r\n?/g, "\n");
    if (text.length > MAX_CHARS) text = text.slice(0, MAX_CHARS) + "…";
    var lines = text.split("\n"), blocks = [], i = 0;
    while (i < lines.length) {
      var line = lines[i], m;
      if (!line.trim()) { i++; continue; }

      if (isTableStart(lines, i)) {
        var head = splitRow(line), rows = [];
        i += 2;
        while (i < lines.length && lines[i].trim() && lines[i].indexOf("|") >= 0) { rows.push(splitRow(lines[i])); i++; }
        var n = head.length;
        blocks.push({
          type: "table",
          head: head.map(parseInline),
          rows: rows.map(function (r) {
            var cells = r.slice(0, n);
            while (cells.length < n) cells.push("");
            return cells.map(parseInline);
          })
        });
        continue;
      }

      if (BULLET.test(line) || NUMBERED.test(line)) {
        var ordered = NUMBERED.test(line) && !BULLET.test(line), items = [];
        while (i < lines.length && (m = (ordered ? NUMBERED : BULLET).exec(lines[i]))) { items.push(parseInline(m[1])); i++; }
        blocks.push({ type: ordered ? "ol" : "ul", items: items });
        continue;
      }

      if ((m = HEADING.exec(line))) {
        blocks.push({ type: "p", lines: [[{ strong: [{ text: m[1].replace(/\*\*/g, "") }] }]] });
        i++;
        continue;
      }

      // The first line is always consumed, so every pass of the outer loop makes progress.
      var para = [parseInline(line.trim())];
      i++;
      while (i < lines.length && lines[i].trim() && !startsBlock(lines[i]) && !isTableStart(lines, i)) {
        para.push(parseInline(lines[i].trim()));
        i++;
      }
      blocks.push({ type: "p", lines: para });
    }
    return blocks;
  }

  function inlineNodes(doc, inlines) {
    var frag = doc.createDocumentFragment();
    inlines.forEach(function (n) {
      if (n.strong) {
        var s = doc.createElement("strong");
        s.appendChild(doc.createTextNode(n.strong.map(function (t) { return t.text; }).join("")));
        frag.appendChild(s);
      } else {
        frag.appendChild(doc.createTextNode(n.text));
      }
    });
    return frag;
  }

  function auto(el) { el.setAttribute("dir", "auto"); return el; }

  function render(text, doc, opts) {
    doc = doc || root.document;
    opts = opts || {};
    var frag = doc.createDocumentFragment();
    parse(text).forEach(function (b) {
      var el;
      if (b.type === "p") {
        el = auto(doc.createElement("p"));
        b.lines.forEach(function (ln, idx) {
          if (idx) el.appendChild(doc.createElement("br"));
          el.appendChild(inlineNodes(doc, ln));
        });
      } else if (b.type === "ul" || b.type === "ol") {
        el = doc.createElement(b.type);
        b.items.forEach(function (it) {
          var li = auto(doc.createElement("li"));
          li.appendChild(inlineNodes(doc, it));
          el.appendChild(li);
        });
      } else {
        var wrap = doc.createElement("div");
        wrap.setAttribute("class", "md-table");
        wrap.setAttribute("role", "region");
        wrap.setAttribute("tabindex", "0");
        wrap.setAttribute("aria-label", opts.tableLabel || "table");
        var table = doc.createElement("table"), thead = doc.createElement("thead"), tbody = doc.createElement("tbody");
        var hr = doc.createElement("tr");
        b.head.forEach(function (c) { var th = auto(doc.createElement("th")); th.setAttribute("scope", "col"); th.appendChild(inlineNodes(doc, c)); hr.appendChild(th); });
        thead.appendChild(hr);
        b.rows.forEach(function (r) {
          var tr = doc.createElement("tr");
          r.forEach(function (c) { var td = auto(doc.createElement("td")); td.appendChild(inlineNodes(doc, c)); tr.appendChild(td); });
          tbody.appendChild(tr);
        });
        table.appendChild(thead);
        table.appendChild(tbody);
        wrap.appendChild(table);
        el = wrap;
      }
      frag.appendChild(el);
    });
    return frag;
  }

  var api = { parse: parse, render: render, ALLOWED_TAGS: ALLOWED_TAGS, MAX_CHARS: MAX_CHARS };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.SafeMarkdown = api;
})(typeof window !== "undefined" ? window : globalThis);
