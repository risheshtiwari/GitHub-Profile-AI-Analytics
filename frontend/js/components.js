/* Component library.
   Every repeated piece of UI is built here once, so views describe *what* they
   show rather than how it's marked up. Icons are inline SVG paths (Lucide
   geometry) rather than a CDN font — no extra dependency, no network on load,
   and they inherit currentColor so they theme for free. */

import { el, escapeHtml } from "./ui.js";

/* ── Icons ─────────────────────────────────────────────────────────────── */

const ICONS = {
  activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  "bar-chart": '<line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/>',
  "git-compare": '<circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7"/><path d="M11 18H8a2 2 0 0 1-2-2V9"/>',
  "message-square": '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  "clipboard-check": '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/><path d="m9 14 2 2 4-4"/>',
  search: '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
  github: '<path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.4 5.4 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"/><path d="M9 18c-4.51 2-5-2-7-2"/>',
  "file-text": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
  check: '<polyline points="20 6 9 17 4 12"/>',
  "check-circle": '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
  x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
  "alert-circle": '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>',
  "alert-triangle": '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
  info: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>',
  "chevron-right": '<polyline points="9 18 15 12 9 6"/>',
  "chevron-down": '<polyline points="6 9 12 15 18 9"/>',
  "log-out": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>',
  "log-in": '<path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/>',
  menu: '<line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/>',
  trash: '<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
  "refresh-cw": '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
  send: '<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>',
  sparkles: '<path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3z"/>',
  code: '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
  folder: '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
  star: '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
  users: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  target: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
  gauge: '<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
  inbox: '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
  "external-link": '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>',
  "corner-down-right": '<polyline points="15 10 20 15 15 20"/><path d="M4 4v7a4 4 0 0 0 4 4h12"/>',
  bot: '<rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/><line x1="8" y1="16" x2="8" y2="16"/><line x1="16" y1="16" x2="16" y2="16"/>',
};

/**
 * Inline SVG icon. Decorative by default (aria-hidden); pass a label to make
 * it meaningful to screen readers.
 */
export function icon(name, { size = 16, label } = {}) {
  const paths = ICONS[name] || ICONS.info;
  const wrapper = el("span", { class: "icon-wrap", style: "display:inline-flex" });
  wrapper.innerHTML =
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" ` +
    `stroke-linecap="round" stroke-linejoin="round" width="${size}" height="${size}" ` +
    (label ? `role="img" aria-label="${escapeHtml(label)}"` : 'aria-hidden="true"') +
    `>${paths}</svg>`;
  return wrapper.firstChild;
}

/* ── Buttons ───────────────────────────────────────────────────────────── */

export function button(label, { variant = "secondary", size, iconName, iconAfter, onClick, type = "button", title, id, disabled } = {}) {
  const classes = ["btn", `btn--${variant}`];
  if (size) classes.push(`btn--${size}`);

  const node = el("button", {
    class: classes.join(" "),
    type,
    id,
    title,
    "aria-label": !label && title ? title : null,
    disabled: disabled || null,
    onClick,
  });

  if (iconName && !iconAfter) node.append(icon(iconName));
  if (label) node.append(document.createTextNode(label));
  if (iconName && iconAfter) node.append(icon(iconName));
  return node;
}

/**
 * Puts a button into a loading state and back, without losing its label.
 * Disabling during in-flight work is what stops double submits.
 */
export function setBusy(node, isBusy, busyLabel) {
  if (!node) return;
  if (isBusy) {
    if (!node.dataset.idleHtml) node.dataset.idleHtml = node.innerHTML;
    node.disabled = true;
    node.setAttribute("aria-busy", "true");
    node.replaceChildren(el("span", { class: "spinner" }), document.createTextNode(busyLabel || "Working…"));
  } else {
    node.disabled = false;
    node.removeAttribute("aria-busy");
    if (node.dataset.idleHtml) {
      node.innerHTML = node.dataset.idleHtml;
      delete node.dataset.idleHtml;
    }
  }
}

/* ── Surfaces ──────────────────────────────────────────────────────────── */

export function card({ title, subtitle, actions, body, id } = {}) {
  const node = el("section", { class: "card", id });
  if (title || subtitle || actions) {
    node.append(el("div", { class: "card__header" },
      el("div", {},
        title ? el("h2", { class: "card__title", text: title }) : null,
        subtitle ? el("div", { class: "card__subtitle", text: subtitle }) : null),
      actions ? el("div", { class: "row" }, actions) : null));
  }
  if (body) node.append(el("div", { class: "card__body" }, body));
  return node;
}

export function stat(label, value, { iconName, meta } = {}) {
  return el("div", { class: "stat" },
    el("div", { class: "stat__label" }, iconName ? icon(iconName, { size: 14 }) : null, label),
    el("div", { class: "stat__value", text: String(value) }),
    meta ? el("div", { class: "stat__meta", text: meta }) : null);
}

export function statGrid(items) {
  return el("div", { class: "stat-grid" }, ...items);
}

export function badge(text, variant = "neutral", { dot = false } = {}) {
  return el("span", { class: `badge badge--${variant}` },
    dot ? el("span", { class: "badge__dot" }) : null, text);
}

export function alert(message, { variant = "info", title, iconName } = {}) {
  const icons = { info: "info", warning: "alert-triangle", danger: "alert-circle", success: "check-circle" };
  return el("div", { class: `alert alert--${variant}`, role: variant === "danger" ? "alert" : null },
    icon(iconName || icons[variant] || "info"),
    el("div", {},
      title ? el("div", { class: "alert__title", text: title }) : null,
      el("div", { class: "alert__body" }, message)));
}

/* ── Tables ────────────────────────────────────────────────────────────── */

/**
 * columns: [{ key, label, numeric, render(row) }]
 * Returns a scroll-wrapped table — on narrow screens columns keep their
 * meaning by scrolling rather than stacking into ambiguity.
 */
export function table(columns, rows, { footer, caption } = {}) {
  const head = el("tr", {}, ...columns.map((column) =>
    el("th", { class: column.numeric ? "num" : "", scope: "col", text: column.label })));

  const body = rows.map((row) =>
    el("tr", {}, ...columns.map((column) => {
      const cell = el("td", { class: column.numeric ? "num" : "" });
      const value = column.render ? column.render(row) : row[column.key];
      if (value === null || value === undefined) cell.textContent = "—";
      else if (value.nodeType) cell.append(value);
      else cell.textContent = String(value);
      return cell;
    })));

  return el("div", { class: "table-wrap" },
    el("table", { class: "table" },
      caption ? el("caption", { class: "sr-only", text: caption }) : null,
      el("thead", {}, head),
      el("tbody", {}, ...body),
      footer ? el("tfoot", {}, footer) : null));
}

/* ── States ────────────────────────────────────────────────────────────── */

export function emptyState(heading, message, { iconName = "inbox", action } = {}) {
  return el("div", { class: "empty" },
    el("div", { class: "empty__icon" }, icon(iconName, { size: 21 })),
    el("h3", { text: heading }),
    el("p", { text: message }),
    action ? el("div", { class: "empty__actions" }, action) : null);
}

export function errorState(message, hint, { onRetry } = {}) {
  return card({
    body: el("div", {},
      alert(message, { variant: "danger", title: "Something went wrong" }),
      hint ? el("p", { class: "hint", style: "margin-top:12px", text: hint }) : null,
      onRetry ? el("div", { style: "margin-top:16px" },
        button("Try again", { variant: "secondary", iconName: "refresh-cw", onClick: onRetry })) : null),
  });
}

/** Skeleton placeholder shaped like the content it replaces. */
export function skeletonCard({ lines = 3, block = false } = {}) {
  const body = el("div", { class: "stack", style: "gap:12px" },
    el("div", { class: "skeleton skeleton--title" }),
    ...Array.from({ length: lines }, (_, index) =>
      el("div", { class: "skeleton skeleton--text", style: `width:${[92, 78, 85, 65][index % 4]}%` })),
    block ? el("div", { class: "skeleton skeleton--block", style: "margin-top:8px" }) : null);
  return card({ body });
}

export function skeletonGrid(count = 4) {
  return el("div", { class: "stat-grid" },
    ...Array.from({ length: count }, () =>
      el("div", { class: "stat" },
        el("div", { class: "skeleton skeleton--text", style: "width:60%;margin-bottom:10px" }),
        el("div", { class: "skeleton", style: "width:45%;height:22px" }))));
}

/**
 * Progress checklist for multi-stage jobs. States: wait | active | done | failed.
 * Long operations need to say what they're doing — a bare spinner reads as a hang.
 */
export function stepList(steps, activeIndex, { failedIndex = -1 } = {}) {
  return el("div", { class: "steps" },
    ...steps.map((label, index) => {
      let state = "is-wait";
      if (index === failedIndex) state = "is-failed";
      else if (index < activeIndex) state = "is-done";
      else if (index === activeIndex) state = "is-active";

      const dot = el("span", { class: "step__dot" });
      if (state === "is-done") dot.append(icon("check", { size: 11 }));
      else if (state === "is-failed") dot.append(icon("x", { size: 11 }));
      else if (state === "is-active") dot.append(el("span", { class: "spinner", style: "width:11px;height:11px" }));

      return el("div", { class: `step ${state}` }, dot, el("span", { text: label }));
    }));
}

export function progressBar() {
  return el("div", { class: "progress", role: "progressbar", "aria-label": "Working" }, el("i", {}));
}
