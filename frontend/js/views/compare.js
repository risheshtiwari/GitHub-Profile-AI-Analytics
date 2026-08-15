/* View 02 — compare two developers.
   POST /compare returns dicts keyed by username; everything here is about
   aligning the two on the same axes so the differences are readable. */

import { api } from "../api.js";
import { $, busyButton, clear, el, empty, escapeHtml, panel, toast } from "../ui.js";
import { languageBars, versusBars } from "../charts.js";
import { requireAuth } from "../auth-ui.js";

export async function runCompare(user1, user2) {
  const out = clear($("#compare-out"));
  const button = $("#btn-compare");

  if (!requireAuth("Sign in to run a comparison.", () => runCompare(user1, user2))) return;

  busyButton(button, true, "Comparing…");
  out.append(panel("RUN", `${user1} vs ${user2}`, "running both analyses",
    el("div", { class: "progress" }, el("i", {}))));

  try {
    const result = await api.compare(user1, user2);
    clear(out);
    render(out, result, user1, user2);
    toast("Comparison ready", "good");
  } catch (error) {
    clear(out).append(panel("ERR", "Comparison stopped", null,
      el("p", { class: "prose", text: error.message })));
    toast(error.message, "bad");
  } finally {
    busyButton(button, false);
  }
}

function render(out, result, user1, user2) {
  const scores = result.developer_score || {};
  const [nameA, nameB] = Object.keys(scores).length === 2 ? Object.keys(scores) : [user1, user2];
  const scoreA = scores[nameA] || {};
  const scoreB = scores[nameB] || {};

  /* Verdict ------------------------------------------------------------ */
  out.append(panel("VER", "Verdict", null,
    el("div", { class: "stats" },
      el("div", { class: "stat" },
        el("div", { class: "stat__val", text: (scoreA.overall_score ?? 0).toFixed(1) }),
        el("div", { class: "stat__key", text: nameA })),
      el("div", { class: "stat" },
        el("div", { class: "stat__val", text: (scoreB.overall_score ?? 0).toFixed(1) }),
        el("div", { class: "stat__key", text: nameB }))),
    el("p", { class: "prose", style: "margin-top:14px", text: result.verdict || "" })));

  /* Score axes --------------------------------------------------------- */
  const axes = ["consistency", "popularity", "code_diversity", "documentation", "testing"];
  out.append(panel("AXS", "Score by axis", null,
    el("div", { html: versusBars(
      axes.map((axis) => ({
        label: axis.replace("_", " "),
        a: Number(scoreA[axis] ?? 0),
        b: Number(scoreB[axis] ?? 0),
        aLabel: Number(scoreA[axis] ?? 0).toFixed(0),
        bLabel: Number(scoreB[axis] ?? 0).toFixed(0),
      })), nameA, nameB) })));

  /* Consistency -------------------------------------------------------- */
  const consistency = result.contribution_consistency || {};
  const consA = consistency[nameA] || {};
  const consB = consistency[nameB] || {};
  out.append(panel("CON", "Contribution consistency", null,
    el("div", { html: versusBars([
      { label: "streak (wks)", a: Number(consA.longest_streak_weeks ?? 0), b: Number(consB.longest_streak_weeks ?? 0) },
      { label: "commits/week", a: Number(consA.average_commits_per_week ?? 0), b: Number(consB.average_commits_per_week ?? 0),
        aLabel: Number(consA.average_commits_per_week ?? 0).toFixed(1),
        bLabel: Number(consB.average_commits_per_week ?? 0).toFixed(1) },
    ], nameA, nameB) })));

  /* Languages side by side --------------------------------------------- */
  const languages = result.language_expertise || {};
  const langRow = el("div", { class: "grid-2" });
  for (const name of [nameA, nameB]) {
    langRow.append(panel("LNG", `${name} — languages`, null,
      el("div", { html: languageBars(languages[name] || {}, 6) })));
  }
  out.append(langRow);

  /* Repository quality -------------------------------------------------- */
  const quality = result.repository_quality || {};
  const qualityRow = el("div", { class: "grid-2" });
  for (const name of [nameA, nameB]) {
    const summary = quality[name] || {};
    qualityRow.append(panel("QLT", `${name} — repositories`, null,
      el("dl", { class: "kv" },
        ...Object.entries(summary).flatMap(([key, value]) => [
          el("dt", { text: key.replaceAll("_", " ") }),
          el("dd", { html: formatValue(value) }),
        ]))));
  }
  out.append(qualityRow);
}

function formatValue(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  if (typeof value === "object") return `<span class="repo-lang">${escapeHtml(JSON.stringify(value))}</span>`;
  return escapeHtml(String(value));
}

export function mountCompare() {
  $("#form-compare").addEventListener("submit", (event) => {
    event.preventDefault();
    const user1 = $("#in-user1").value.trim();
    const user2 = $("#in-user2").value.trim();
    if (user1 && user2) runCompare(user1, user2);
  });

  $("#compare-out").append(empty(
    "No comparison yet",
    "Enter two GitHub usernames to line them up on the same axes."));
}
