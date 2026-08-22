/* Charts.
   Hand-drawn SVG in the app's own palette — one accent for the primary series,
   a lighter tint for the rest, and gray for the track. No rainbow categorical
   palettes: with twelve languages a rainbow tells you nothing that rank and
   magnitude don't tell you better.

   Colours are literal hex rather than CSS variables because these strings are
   serialised into `innerHTML`; they mirror the tokens in app.css. */

import { escapeHtml, fmtNum } from "./ui.js";

const HATCH_DEFS = `
<defs>
  <pattern id="hatch-signal" width="6" height="6" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
    <rect width="6" height="6" fill="#EEF2FF"></rect>
    <line x1="0" y1="0" x2="0" y2="6" stroke="#4F46E5" stroke-width="2.4"></line>
  </pattern>
  <pattern id="hatch-flag" width="6" height="6" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
    <rect width="6" height="6" fill="#FFFAEB"></rect>
    <line x1="0" y1="0" x2="0" y2="6" stroke="#B54708" stroke-width="2.4"></line>
  </pattern>
</defs>`;

/* Each chart gets its own ID namespace: without this, several charts on one
   page all define `id="hatch-signal"`, the document ends up with duplicate IDs,
   and `url(#hatch-signal)` resolves to whichever SVG happened to render first —
   which is how the hatched series silently disappeared. */
let svgSeq = 0;

const svg = (viewBox, inner, extra = "") => {
  const ns = `c${++svgSeq}`;
  const scoped = (HATCH_DEFS + inner)
    .replaceAll("hatch-signal", `hatch-signal-${ns}`)
    .replaceAll("hatch-flag", `hatch-flag-${ns}`);
  return `<svg viewBox="${viewBox}" class="chart-svg" role="img" preserveAspectRatio="xMidYMid meet" ${extra}>${scoped}</svg>`;
};

/* ── Language distribution ─────────────────────────────────────────────── */

export function languageBars(distribution, limit = 8) {
  const entries = Object.entries(distribution || {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit);

  if (!entries.length) return `<p class="field__note">No language data.</p>`;

  const rowHeight = 30;
  const height = entries.length * rowHeight + 6;
  const labelWidth = 108;
  const trackWidth = 400 - labelWidth - 46;
  const max = Math.max(...entries.map(([, value]) => value));

  const rows = entries.map(([name, value], index) => {
    const y = index * rowHeight + 6;
    const width = Math.max(2, (value / max) * trackWidth);
    const fill = index === 0 ? "#4F46E5" : index === 1 ? "#B54708" : "url(#hatch-signal)";
    return `
      <text x="${labelWidth - 10}" y="${y + 13}" text-anchor="end" font-family="Inter, system-ui, sans-serif"
            font-size="11.5" fill="#101828">${escapeHtml(name)}</text>
      <rect x="${labelWidth}" y="${y + 3}" width="${trackWidth}" height="13" fill="#F2F4F7"></rect>
      <rect x="${labelWidth}" y="${y + 3}" width="${width}" height="13" fill="${fill}"></rect>
      <text x="${labelWidth + trackWidth + 8}" y="${y + 13}" font-family="Inter, system-ui, sans-serif"
            font-size="11" fill="#475467">${value.toFixed(1)}%</text>`;
  }).join("");

  return svg(`0 0 400 ${height}`, rows);
}

/* ── Composite score: five sub-scores as columns ───────────────────────── */

export function scoreColumns(breakdown) {
  const keys = ["consistency", "popularity", "code_diversity", "documentation", "testing"];
  const labels = { consistency: "consist", popularity: "popular", code_diversity: "diverse", documentation: "docs", testing: "tests" };

  const width = 400;
  const height = 168;
  const base = 128;
  const colWidth = 46;
  const gap = (width - keys.length * colWidth) / (keys.length + 1);

  const columns = keys.map((key, index) => {
    const value = Math.max(0, Math.min(100, Number(breakdown?.[key] ?? 0)));
    const x = gap + index * (colWidth + gap);
    const barHeight = Math.max(2, (value / 100) * (base - 18));
    const y = base - barHeight;
    const fill = value >= 60 ? "#4F46E5" : "url(#hatch-signal)";
    return `
      <rect x="${x}" y="${18}" width="${colWidth}" height="${base - 18}" fill="#F2F4F7"></rect>
      <rect x="${x}" y="${y}" width="${colWidth}" height="${barHeight}" fill="${fill}"></rect>
      <text x="${x + colWidth / 2}" y="${y - 5}" text-anchor="middle" font-family="Inter, system-ui, sans-serif"
            font-size="11" font-weight="600" fill="#101828">${value.toFixed(0)}</text>
      <text x="${x + colWidth / 2}" y="${base + 15}" text-anchor="middle" font-family="Inter, system-ui, sans-serif"
            font-size="10" fill="#475467">${labels[key]}</text>`;
  }).join("");

  const overall = Number(breakdown?.overall_score ?? 0);

  return svg(`0 0 ${width} ${height}`, `
    <line x1="0" y1="${base}" x2="${width}" y2="${base}" stroke="#E4E7EC" stroke-width="1"></line>
    ${columns}
    <text x="0" y="${height - 8}" font-family="Inter, system-ui, sans-serif" font-size="10.5" fill="#667085">
      OVERALL ${overall.toFixed(1)} / 100</text>`);
}

/* ── 52-week commit strip ──────────────────────────────────────────────── */

export function commitStrip(series) {
  const weeks = (series || []).slice(-52);
  if (!weeks.length) {
    return `<p class="field__note">No commit activity in the stored history.</p>`;
  }

  const cell = 13;
  const gap = 3;
  const width = weeks.length * (cell + gap);
  const height = 78;
  const max = Math.max(...weeks.map((week) => week.count || 0), 1);

  const bars = weeks.map((week, index) => {
    const count = week.count || 0;
    const level = count === 0 ? 0 : Math.ceil((count / max) * 4);
    const barHeight = count === 0 ? 3 : Math.max(4, (count / max) * 52);
    const x = index * (cell + gap);
    const y = 56 - barHeight;
    const fill = ["#F2F4F7", "url(#hatch-signal)", "#818CF8", "#6366F1", "#4F46E5"][level];
    const label = `${week.week_start ?? ""}: ${count} commits`;
    return `<rect x="${x}" y="${y}" width="${cell}" height="${barHeight}" fill="${fill}" rx="1">
              <title>${escapeHtml(label)}</title></rect>`;
  }).join("");

  const first = weeks[0]?.week_start?.slice(0, 10) ?? "";
  const last = weeks.at(-1)?.week_start?.slice(0, 10) ?? "";

  return svg(`0 0 ${width} ${height}`, `
    ${bars}
    <line x1="0" y1="57" x2="${width}" y2="57" stroke="#E4E7EC"></line>
    <text x="0" y="72" font-family="Inter, system-ui, sans-serif" font-size="10.5" fill="#667085">${escapeHtml(first)}</text>
    <text x="${width}" y="72" text-anchor="end" font-family="Inter, system-ui, sans-serif" font-size="10.5"
          fill="#667085">${escapeHtml(last)} · peak ${max}/wk</text>`);
}

/* ── Commits per month ─────────────────────────────────────────────────── */

export function monthArea(commitsPerMonth) {
  const entries = Object.entries(commitsPerMonth || {}).sort(([a], [b]) => a.localeCompare(b));
  if (entries.length < 2) return `<p class="field__note">Not enough monthly history to plot.</p>`;

  const width = 400;
  const height = 130;
  const padLeft = 30;
  const padBottom = 22;
  const max = Math.max(...entries.map(([, value]) => value), 1);
  const stepX = (width - padLeft - 6) / (entries.length - 1);
  const scaleY = (value) => height - padBottom - (value / max) * (height - padBottom - 12);

  const points = entries.map(([, value], index) => `${padLeft + index * stepX},${scaleY(value)}`);
  const area = `${padLeft},${height - padBottom} ${points.join(" ")} ${padLeft + (entries.length - 1) * stepX},${height - padBottom}`;

  const ticks = entries.map(([label], index) => {
    if (index % Math.ceil(entries.length / 6) !== 0) return "";
    return `<text x="${padLeft + index * stepX}" y="${height - 6}" text-anchor="middle"
              font-family="Inter, system-ui, sans-serif" font-size="9.5" fill="#667085">${escapeHtml(label.slice(2))}</text>`;
  }).join("");

  const dots = entries.map(([label, value], index) =>
    `<circle cx="${padLeft + index * stepX}" cy="${scaleY(value)}" r="2.5" fill="#4F46E5">
       <title>${escapeHtml(label)}: ${value} commits</title></circle>`).join("");

  return svg(`0 0 ${width} ${height}`, `
    <line x1="${padLeft}" y1="${height - padBottom}" x2="${width - 4}" y2="${height - padBottom}" stroke="#E4E7EC"></line>
    <line x1="${padLeft}" y1="12" x2="${padLeft}" y2="${height - padBottom}" stroke="#E4E7EC"></line>
    <text x="${padLeft - 6}" y="16" text-anchor="end" font-family="Inter, system-ui, sans-serif" font-size="9.5" fill="#667085">${max}</text>
    <polygon points="${area}" fill="url(#hatch-signal)" opacity=".55"></polygon>
    <polyline points="${points.join(" ")}" fill="none" stroke="#4F46E5" stroke-width="2"></polyline>
    ${dots}${ticks}`);
}

/* ── Job match: overall score dial ──────────────────────────────────────
   Still SVG: a dial is genuinely geometric, and it renders inside a fixed
   200px column so the viewBox never gets stretched. */

export function scoreGauge(score, label) {
  const value = Math.max(0, Math.min(100, Number(score) || 0));
  const size = 200;
  const centre = size / 2;
  const radius = 78;
  const circumference = Math.PI * radius;
  const filled = (value / 100) * circumference;

  // Tick marks at the recommendation-band thresholds in match_engine.py.
  const ticks = [50, 65, 80, 90].map((mark) => {
    const angle = Math.PI * (1 - mark / 100);
    const x1 = centre + Math.cos(angle) * (radius - 12);
    const y1 = centre - Math.sin(angle) * (radius - 12);
    const x2 = centre + Math.cos(angle) * (radius + 12);
    const y2 = centre - Math.sin(angle) * (radius + 12);
    return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#E4E7EC" stroke-width="1.5"/>`;
  }).join("");

  const arc = (stroke, dash) =>
    `<path d="M ${centre - radius} ${centre} A ${radius} ${radius} 0 0 1 ${centre + radius} ${centre}"
       fill="none" stroke="${stroke}" stroke-width="14" stroke-linecap="round"
       ${dash ? `stroke-dasharray="${dash} ${circumference}"` : ""}/>`;

  return svg(`0 0 ${size} ${size * 0.66}`, `
    ${arc("#F2F4F7")}
    ${arc("#4F46E5", filled)}
    ${ticks}
    <text x="${centre}" y="${centre - 14}" text-anchor="middle" font-family="Inter, system-ui, sans-serif"
          font-size="34" font-weight="600" fill="#101828">${value.toFixed(0)}%</text>
    <text x="${centre}" y="${centre + 8}" text-anchor="middle" font-family="Inter, system-ui, sans-serif"
          font-size="12" fill="#475467">${escapeHtml(label || "")}</text>
    <text x="${centre - radius}" y="${centre + 22}" text-anchor="middle" font-family="Inter, system-ui, sans-serif"
          font-size="10" fill="#667085">0</text>
    <text x="${centre + radius}" y="${centre + 22}" text-anchor="middle" font-family="Inter, system-ui, sans-serif"
          font-size="10" fill="#667085">100</text>`);
}

/* ── Job match: score x weight = contribution ───────────────────────────
   Built as HTML rather than SVG. Two reasons, both learned the hard way:
   an SVG with a 460-unit viewBox stretched to a ~1150px card scales its text
   2.5x, and every chart embedding its own <pattern id="..."> put duplicate IDs
   in the document, so `url(#hatch-signal)` resolved to the wrong SVG and the
   hatched series silently vanished. HTML has neither problem, uses the real
   type scale, and reflows on narrow screens for free. */

export function weightedBars(rows) {
  const total = rows.reduce((sum, row) => sum + row.contribution, 0);

  const bars = rows.map((row) => `
    <div class="wbar">
      <div class="wbar__label">${escapeHtml(row.label)}</div>
      <div class="wbar__track" role="img" aria-label="${escapeHtml(row.label)} scores ${row.score.toFixed(0)} out of 100">
        <div class="wbar__fill" style="width:${Math.max(1, Math.min(100, row.score)).toFixed(1)}%"></div>
      </div>
      <div class="wbar__math">
        <span class="wbar__calc">${row.score.toFixed(0)} &times; ${row.weight}%</span>
        <span class="wbar__value">${row.contribution.toFixed(1)}</span>
      </div>
    </div>`).join("");

  // The stack shows how the six contributions actually add up to the total —
  // the same arithmetic as the table, read as proportions.
  const segments = rows.map((row, index) => {
    const share = total > 0 ? (row.contribution / total) * 100 : 0;
    if (share <= 0) return "";
    return `<div class="wstack__seg wstack__seg--${index % 6}" style="width:${share.toFixed(2)}%"
              title="${escapeHtml(row.label)}: ${row.contribution.toFixed(1)} of ${total.toFixed(1)}"></div>`;
  }).join("");

  const legend = rows.map((row, index) => `
    <span class="wstack__key">
      <span class="wstack__swatch wstack__seg--${index % 6}"></span>${escapeHtml(row.label)}
    </span>`).join("");

  return `
    <div class="wchart">
      <div class="wchart__head">
        <span>Component score (of 100)</span>
        <span>Score &times; weight = contribution</span>
      </div>
      ${bars}
      <div class="wstack">
        <div class="wstack__title">Contributions to the ${total.toFixed(1)} total</div>
        <div class="wstack__bar">${segments}</div>
        <div class="wstack__legend">${legend}</div>
      </div>
    </div>`;
}

/* ── Head-to-head grouped bars (compare view) ───────────────────────────── */

export function versusBars(rows, nameA, nameB) {
  const bars = rows.map((row) => {
    // A row may declare its own scale. Sub-scores are 0-100, so 61 must draw
    // as 61% of the track — normalising to the row maximum instead would draw
    // 61 and 100 as identical full-width bars, which is actively misleading.
    const max = row.max ?? Math.max(row.a, row.b, 1);
    const widthA = Math.max(1.5, Math.min(100, (row.a / max) * 100));
    const widthB = Math.max(1.5, Math.min(100, (row.b / max) * 100));
    const leader = row.a === row.b ? "" : (row.a > row.b ? "a" : "b");

    return `
      <div class="vbar">
        <div class="vbar__label">${escapeHtml(row.label)}</div>
        <div class="vbar__group">
          <div class="vbar__line">
            <div class="vbar__track"><div class="vbar__fill vbar__fill--a" style="width:${widthA.toFixed(1)}%"></div></div>
            <span class="vbar__value ${leader === "a" ? "is-leader" : ""}">${escapeHtml(row.aLabel ?? String(row.a))}</span>
          </div>
          <div class="vbar__line">
            <div class="vbar__track"><div class="vbar__fill vbar__fill--b" style="width:${widthB.toFixed(1)}%"></div></div>
            <span class="vbar__value ${leader === "b" ? "is-leader" : ""}">${escapeHtml(row.bLabel ?? String(row.b))}</span>
          </div>
        </div>
      </div>`;
  }).join("");

  return `
    <div class="vchart">
      <div class="vchart__legend">
        <span class="vchart__key"><span class="vchart__swatch vchart__swatch--a"></span>${escapeHtml(nameA)}</span>
        <span class="vchart__key"><span class="vchart__swatch vchart__swatch--b"></span>${escapeHtml(nameB)}</span>
      </div>
      ${bars}
    </div>`;
}
