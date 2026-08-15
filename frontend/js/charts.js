/* Charts.
   A deliberately narrow visual language: two inks (ultramarine + amber), solid
   for the primary series and 45° hatching for the secondary, the way a drawing
   sheet distinguishes materials. No rainbow categorical palettes — with 12
   languages a rainbow tells you nothing, whereas rank + magnitude does. */

import { escapeHtml, fmtNum } from "./ui.js";

const HATCH_DEFS = `
<defs>
  <pattern id="hatch-signal" width="6" height="6" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
    <rect width="6" height="6" fill="#E8EBFE"></rect>
    <line x1="0" y1="0" x2="0" y2="6" stroke="#2B44E8" stroke-width="2.4"></line>
  </pattern>
  <pattern id="hatch-flag" width="6" height="6" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
    <rect width="6" height="6" fill="#FDF0E4"></rect>
    <line x1="0" y1="0" x2="0" y2="6" stroke="#E07C24" stroke-width="2.4"></line>
  </pattern>
</defs>`;

const svg = (viewBox, inner, extra = "") =>
  `<svg viewBox="${viewBox}" width="100%" role="img" preserveAspectRatio="xMidYMid meet" ${extra}>${HATCH_DEFS}${inner}</svg>`;

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
    const fill = index === 0 ? "#2B44E8" : index === 1 ? "#E07C24" : "url(#hatch-signal)";
    return `
      <text x="${labelWidth - 10}" y="${y + 13}" text-anchor="end" font-family="IBM Plex Mono, monospace"
            font-size="11.5" fill="#131A2E">${escapeHtml(name)}</text>
      <rect x="${labelWidth}" y="${y + 3}" width="${trackWidth}" height="13" fill="#F0F3F8"></rect>
      <rect x="${labelWidth}" y="${y + 3}" width="${width}" height="13" fill="${fill}"></rect>
      <text x="${labelWidth + trackWidth + 8}" y="${y + 13}" font-family="IBM Plex Mono, monospace"
            font-size="11" fill="#56617D">${value.toFixed(1)}%</text>`;
  }).join("");

  return svg(`0 0 400 ${height}`, rows, `style="max-height:${height + 10}px"`);
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
    const fill = value >= 60 ? "#2B44E8" : "url(#hatch-signal)";
    return `
      <rect x="${x}" y="${18}" width="${colWidth}" height="${base - 18}" fill="#F0F3F8"></rect>
      <rect x="${x}" y="${y}" width="${colWidth}" height="${barHeight}" fill="${fill}"></rect>
      <text x="${x + colWidth / 2}" y="${y - 5}" text-anchor="middle" font-family="IBM Plex Mono, monospace"
            font-size="11" font-weight="600" fill="#131A2E">${value.toFixed(0)}</text>
      <text x="${x + colWidth / 2}" y="${base + 15}" text-anchor="middle" font-family="IBM Plex Mono, monospace"
            font-size="10" fill="#56617D">${labels[key]}</text>`;
  }).join("");

  const overall = Number(breakdown?.overall_score ?? 0);

  return svg(`0 0 ${width} ${height}`, `
    <line x1="0" y1="${base}" x2="${width}" y2="${base}" stroke="#C9D2E0" stroke-width="1"></line>
    ${columns}
    <text x="0" y="${height - 8}" font-family="IBM Plex Mono, monospace" font-size="10.5" fill="#8A93A8">
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
    const fill = ["#E4E9F1", "url(#hatch-signal)", "#7C8CF0", "#4A5FEC", "#2B44E8"][level];
    const label = `${week.week_start ?? ""}: ${count} commits`;
    return `<rect x="${x}" y="${y}" width="${cell}" height="${barHeight}" fill="${fill}" rx="1">
              <title>${escapeHtml(label)}</title></rect>`;
  }).join("");

  const first = weeks[0]?.week_start?.slice(0, 10) ?? "";
  const last = weeks.at(-1)?.week_start?.slice(0, 10) ?? "";

  return svg(`0 0 ${width} ${height}`, `
    ${bars}
    <line x1="0" y1="57" x2="${width}" y2="57" stroke="#C9D2E0"></line>
    <text x="0" y="72" font-family="IBM Plex Mono, monospace" font-size="10.5" fill="#8A93A8">${escapeHtml(first)}</text>
    <text x="${width}" y="72" text-anchor="end" font-family="IBM Plex Mono, monospace" font-size="10.5"
          fill="#8A93A8">${escapeHtml(last)} · peak ${max}/wk</text>`);
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
              font-family="IBM Plex Mono, monospace" font-size="9.5" fill="#8A93A8">${escapeHtml(label.slice(2))}</text>`;
  }).join("");

  const dots = entries.map(([label, value], index) =>
    `<circle cx="${padLeft + index * stepX}" cy="${scaleY(value)}" r="2.5" fill="#2B44E8">
       <title>${escapeHtml(label)}: ${value} commits</title></circle>`).join("");

  return svg(`0 0 ${width} ${height}`, `
    <line x1="${padLeft}" y1="${height - padBottom}" x2="${width - 4}" y2="${height - padBottom}" stroke="#C9D2E0"></line>
    <line x1="${padLeft}" y1="12" x2="${padLeft}" y2="${height - padBottom}" stroke="#C9D2E0"></line>
    <text x="${padLeft - 6}" y="16" text-anchor="end" font-family="IBM Plex Mono, monospace" font-size="9.5" fill="#8A93A8">${max}</text>
    <polygon points="${area}" fill="url(#hatch-signal)" opacity=".55"></polygon>
    <polyline points="${points.join(" ")}" fill="none" stroke="#2B44E8" stroke-width="2"></polyline>
    ${dots}${ticks}`);
}

/* ── Head-to-head bars for /compare ────────────────────────────────────── */

export function versusBars(rows, nameA, nameB) {
  const width = 400;
  const rowHeight = 46;
  const height = rows.length * rowHeight + 26;
  const labelWidth = 118;
  const trackWidth = width - labelWidth - 52;

  const body = rows.map((row, index) => {
    const y = index * rowHeight + 22;
    const max = Math.max(row.a, row.b, 1);
    const widthA = Math.max(2, (row.a / max) * trackWidth);
    const widthB = Math.max(2, (row.b / max) * trackWidth);
    return `
      <text x="${labelWidth - 10}" y="${y + 12}" text-anchor="end" font-family="IBM Plex Mono, monospace"
            font-size="11" fill="#131A2E">${escapeHtml(row.label)}</text>
      <rect x="${labelWidth}" y="${y + 1}" width="${widthA}" height="12" fill="#2B44E8"></rect>
      <text x="${labelWidth + widthA + 7}" y="${y + 11}" font-family="IBM Plex Mono, monospace"
            font-size="10.5" fill="#56617D">${escapeHtml(row.aLabel ?? fmtNum(row.a))}</text>
      <rect x="${labelWidth}" y="${y + 17}" width="${widthB}" height="12" fill="url(#hatch-flag)"></rect>
      <text x="${labelWidth + widthB + 7}" y="${y + 27}" font-family="IBM Plex Mono, monospace"
            font-size="10.5" fill="#56617D">${escapeHtml(row.bLabel ?? fmtNum(row.b))}</text>`;
  }).join("");

  return svg(`0 0 ${width} ${height}`, `
    <rect x="0" y="2" width="9" height="9" fill="#2B44E8"></rect>
    <text x="14" y="10" font-family="IBM Plex Mono, monospace" font-size="10.5" fill="#131A2E">${escapeHtml(nameA)}</text>
    <rect x="${labelWidth + 4}" y="2" width="9" height="9" fill="url(#hatch-flag)"></rect>
    <text x="${labelWidth + 18}" y="10" font-family="IBM Plex Mono, monospace" font-size="10.5" fill="#131A2E">${escapeHtml(nameB)}</text>
    ${body}`);
}
