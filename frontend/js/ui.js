/* Small DOM + formatting helpers shared by every view. */

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "html") node.innerHTML = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

export const $ = (selector, scope = document) => scope.querySelector(selector);

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export function toast(message, kind = "info") {
  const host = $("#toasts");
  const node = el("div", { class: `toast toast--${kind}`, text: message });
  host.append(node);
  setTimeout(() => {
    node.style.transition = "opacity .3s";
    node.style.opacity = "0";
    setTimeout(() => node.remove(), 320);
  }, kind === "bad" ? 6000 : 3600);
}

export function fmtNum(value) {
  const number = Number(value ?? 0);
  if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(1)}M`;
  if (number >= 1000) return `${(number / 1000).toFixed(number >= 10_000 ? 0 : 1)}k`;
  return String(number);
}

export function fmtBytes(value) {
  const number = Number(value ?? 0);
  if (number >= 1_048_576) return `${(number / 1_048_576).toFixed(1)} MB`;
  if (number >= 1024) return `${Math.round(number / 1024)} KB`;
  return `${number} B`;
}

export function fmtDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** Panel with the gutter ordinal that runs through the whole interface. */
export function panel(ordinal, title, meta, ...body) {
  return el("section", { class: "panel", "data-ord": ordinal },
    (title || meta) && el("div", { class: "panel__head" },
      title && el("h2", { class: "panel__title", text: title }),
      meta && el("span", { class: "panel__meta", text: meta })),
    ...body);
}

export function empty(heading, message) {
  return el("div", { class: "empty" },
    el("h3", { text: heading }),
    el("p", { text: message }));
}

export function busyButton(button, isBusy, busyLabel) {
  if (isBusy) {
    button.dataset.label = button.textContent;
    button.disabled = true;
    button.innerHTML = `<span class="spinner"></span>${escapeHtml(busyLabel)}`;
  } else {
    button.disabled = false;
    button.textContent = button.dataset.label || button.textContent;
  }
}

/**
 * Minimal markdown for model output: fenced code, inline code, bold, lists.
 * Deliberately tiny — answers are prose with occasional short snippets, and a
 * full markdown library would be a lot of weight for that.
 */
export function renderMarkdown(text) {
  const fences = [];
  let working = String(text ?? "").replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    fences.push(`<pre><code data-lang="${escapeHtml(lang)}">${escapeHtml(code.replace(/\n$/, ""))}</code></pre>`);
    return `\u0000FENCE${fences.length - 1}\u0000`;
  });

  working = escapeHtml(working)
    .replace(/`([^`\n]+)`/g, (_, code) => `<code>${code}</code>`)
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");

  const blocks = working.split(/\n{2,}/).map((block) => {
    const lines = block.split("\n").filter((line) => line.trim() !== "");
    if (!lines.length) return "";
    if (lines.every((line) => /^\s*(?:[-*•]|\d+\.)\s+/.test(line))) {
      const items = lines.map((line) => `<li>${line.replace(/^\s*(?:[-*•]|\d+\.)\s+/, "")}</li>`).join("");
      return `<ul>${items}</ul>`;
    }
    return `<p>${lines.join("<br>")}</p>`;
  });

  return blocks.join("").replace(/\u0000FENCE(\d+)\u0000/g, (_, index) => fences[Number(index)]);
}

/** Turns [1] [2] markers in an answer into clickable citation chips. */
export function linkCitations(html, maxCitation) {
  return html.replace(/\[(\d{1,2})\]/g, (match, digits) => {
    const number = Number(digits);
    if (!number || number > maxCitation) return match;
    return `<button class="cite" data-cite="${number}" title="Show the cited source">${number}</button>`;
  });
}
