/* View 02 — compare two developers.
   POST /compare returns dicts keyed by username; the job here is aligning the
   two on identical axes so differences are readable at a glance. */

import { api } from "../api.js";
import { $, clear, el, escapeHtml, toast } from "../ui.js";
import {
  badge, card, emptyState, errorState, icon, setBusy, skeletonCard, stat, statGrid,
} from "../components.js";
import { languageBars, versusBars } from "../charts.js";
import { requireAuth } from "../auth-ui.js";

export async function runCompare(user1, user2) {
  const out = clear($("#compare-out"));
  const button = $("#btn-compare");

  if (!requireAuth("Sign in to run a comparison.", () => runCompare(user1, user2))) return;

  setBusy(button, true, "Comparing…");
  out.append(
    card({
      title: `${user1} vs ${user2}`,
      subtitle: "Running both analyses — up to a minute on a cold cache",
      body: el("div", { class: "progress" }, el("i", {})),
    }),
    skeletonCard({ lines: 2, block: true }),
  );

  try {
    const result = await api.compare(user1, user2);
    clear(out);
    render(out, result, user1, user2);
    toast("Comparison ready", "good");
  } catch (error) {
    clear(out).append(errorState(
      error.message,
      "Both usernames must exist on GitHub and be publicly visible.",
      { onRetry: () => runCompare(user1, user2) },
    ));
    toast(error.message, "bad");
  } finally {
    setBusy(button, false);
  }
}

function render(out, result, user1, user2) {
  const scores = result.developer_score || {};
  const [nameA, nameB] = Object.keys(scores).length === 2 ? Object.keys(scores) : [user1, user2];
  const scoreA = scores[nameA] || {};
  const scoreB = scores[nameB] || {};

  const overallA = Number(scoreA.overall_score ?? 0);
  const overallB = Number(scoreB.overall_score ?? 0);

  /* Headline */
  out.append(statGrid([
    stat(nameA, overallA.toFixed(1), {
      iconName: "gauge",
      meta: overallA >= overallB ? "Higher composite score" : `${(overallB - overallA).toFixed(1)} behind`,
    }),
    stat(nameB, overallB.toFixed(1), {
      iconName: "gauge",
      meta: overallB >= overallA ? "Higher composite score" : `${(overallA - overallB).toFixed(1)} behind`,
    }),
  ]));

  if (result.verdict) {
    out.append(card({
      title: "Verdict",
      body: el("p", { class: "prose", text: result.verdict }),
    }));
  }

  /* Score axes */
  const axes = ["consistency", "popularity", "code_diversity", "documentation", "testing"];
  out.append(card({
    title: "Score by axis",
    subtitle: "Each sub-score, side by side",
    body: el("div", {
      html: versusBars(
        axes.map((axis) => ({
          label: axis.replace(/_/g, " "),
          a: Number(scoreA[axis] ?? 0),
          b: Number(scoreB[axis] ?? 0),
          max: 100,   // sub-scores share a fixed 0-100 scale
          aLabel: Number(scoreA[axis] ?? 0).toFixed(0),
          bLabel: Number(scoreB[axis] ?? 0).toFixed(0),
        })), nameA, nameB),
    }),
  }));

  /* Consistency */
  const consistency = result.contribution_consistency || {};
  const consA = consistency[nameA] || {};
  const consB = consistency[nameB] || {};
  out.append(card({
    title: "Contribution consistency",
    body: el("div", {
      html: versusBars([
        { label: "streak (weeks)", a: Number(consA.longest_streak_weeks ?? 0), b: Number(consB.longest_streak_weeks ?? 0) },
        {
          label: "commits/week",
          a: Number(consA.average_commits_per_week ?? 0),
          b: Number(consB.average_commits_per_week ?? 0),
          aLabel: Number(consA.average_commits_per_week ?? 0).toFixed(1),
          bLabel: Number(consB.average_commits_per_week ?? 0).toFixed(1),
        },
      ], nameA, nameB),
    }),
  }));

  /* Languages */
  const languages = result.language_expertise || {};
  const langRow = el("div", { class: "grid" });
  for (const name of [nameA, nameB]) {
    langRow.append(card({
      title: `${name} — languages`,
      body: el("div", { html: languageBars(languages[name] || {}, 6) }),
    }));
  }
  out.append(langRow);

  /* Repository quality */
  const quality = result.repository_quality || {};
  const qualityRow = el("div", { class: "grid" });
  for (const name of [nameA, nameB]) {
    const summary = quality[name] || {};
    qualityRow.append(card({
      title: `${name} — repositories`,
      body: el("dl", { class: "kv" },
        ...Object.entries(summary).flatMap(([key, value]) => [
          el("dt", { text: key.replace(/_/g, " ") }),
          el("dd", { text: formatValue(value) }),
        ])),
    }));
  }
  out.append(qualityRow);
}

function formatValue(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function mountCompare() {
  $("#form-compare").addEventListener("submit", (event) => {
    event.preventDefault();
    const user1 = $("#in-user1").value.trim();
    const user2 = $("#in-user2").value.trim();

    if (!user1 || !user2) {
      for (const id of ["#in-user1", "#in-user2"]) {
        if (!$(id).value.trim()) $(id).setAttribute("aria-invalid", "true");
      }
      toast("Enter both usernames to compare.", "bad");
      return;
    }
    if (user1.toLowerCase() === user2.toLowerCase()) {
      toast("Enter two different usernames.", "bad");
      return;
    }

    $("#in-user1").removeAttribute("aria-invalid");
    $("#in-user2").removeAttribute("aria-invalid");
    runCompare(user1, user2);
  });

  $("#compare-out").append(emptyState(
    "No comparison yet",
    "Enter two GitHub usernames to line them up on the same axes.",
    { iconName: "git-compare" }));
}
