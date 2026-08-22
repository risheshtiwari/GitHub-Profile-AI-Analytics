/* View 01 — analyze a developer.
   POST /analyze does the heavy work, then the read endpoints are fetched in
   parallel and rendered. The run log shows which stage is in flight, because a
   cold analysis can take 40s and a silent spinner reads as a hang. */

import { api } from "../api.js";
import { $, clear, el, escapeHtml, fmtDate, fmtNum, panel, renderMarkdown, toast } from "../ui.js";
import {
  alert, badge, button, card, emptyState, errorState, icon,
  setBusy, skeletonCard, skeletonGrid, stat, statGrid, stepList, table,
} from "../components.js";
import { commitStrip, languageBars, monthArea, scoreColumns } from "../charts.js";
import { requireAuth } from "../auth-ui.js";

const STAGES = [
  "Collecting repositories, languages and commit history",
  "Computing repository, language and activity analytics",
  "Generating skill assessment, résumé summary and questions",
  "Loading results",
];

export async function runAnalysis(username) {
  const out = clear($("#analyze-out"));
  const button = $("#btn-analyze");
  const input = $("#in-username");
  input.value = username;

  if (!requireAuth("Sign in to run an analysis.", () => runAnalysis(username))) return;

  setBusy(button, true, "Analysing…");
  const progress = card({
    title: `Analysing ${username}`,
    subtitle: "This can take up to a minute on a cold cache",
    body: stepList(STAGES, 0),
  });
  out.append(progress, skeletonGrid(4), skeletonCard({ lines: 2, block: true }));

  try {
    await api.analyze(username);
    clear(out).append(card({
      title: `Analysing ${username}`,
      subtitle: "Almost there",
      body: stepList(STAGES, 3),
    }), skeletonGrid(4), skeletonCard({ lines: 2, block: true }));

    const [developer, score, languages, activity, repositories, topProjects, summary, interview] =
      await Promise.all([
        api.developer(username),
        api.score(username).catch(() => null),
        api.languages(username).catch(() => null),
        api.activity(username).catch(() => null),
        api.repositories(username).catch(() => []),
        api.topProjects(username).catch(() => []),
        api.summary(username).catch(() => null),
        api.interview(username).catch(() => null),
      ]);

    clear(out);
    render(out, { developer, score, languages, activity, repositories, topProjects, summary, interview });
    toast(`Analysis complete for ${developer.github_username}`, "good");
  } catch (error) {
    clear(out).append(errorState(
      error.message,
      error.status === 404
        ? "Check the spelling — that GitHub user doesn't exist."
        : "If this is a rate limit, add a GITHUB_TOKEN to your .env and restart the server.",
      { onRetry: () => runAnalysis(username) },
    ));
    toast(error.message, "bad");
  } finally {
    setBusy(button, false);
  }
}

function render(out, data) {
  const { developer, score, languages, activity, repositories, topProjects, summary, interview } = data;

  /* Summary stats — the numbers worth seeing before anything else. */
  out.append(statGrid([
    stat("Developer score", score ? score.overall_score.toFixed(1) : "—", {
      iconName: "gauge", meta: score ? "out of 100" : "not available" }),
    stat("Public repos", fmtNum(developer.public_repos), { iconName: "folder" }),
    stat("Followers", fmtNum(developer.followers), { iconName: "users" }),
    stat("Total stars", fmtNum((repositories || []).reduce((sum, repo) => sum + (repo.stars || 0), 0)), {
      iconName: "star", meta: `${(repositories || []).length} repositories analysed` }),
  ]));

  /* Profile */
  out.append(card({
    id: "profile-card",
    body: el("div", { class: "row", style: "gap:20px;flex-wrap:nowrap;align-items:flex-start" },
      developer.avatar_url
        ? el("img", {
            src: developer.avatar_url, alt: "",
            width: "64", height: "64",
            style: "border-radius:10px;border:1px solid var(--border);flex:none;background:var(--gray-100)",
          })
        : null,
      el("div", { style: "min-width:0;flex:1" },
        el("h2", { text: developer.name || developer.github_username }),
        el("a", {
          href: `https://github.com/${developer.github_username}`,
          target: "_blank", rel: "noopener",
          class: "cell-muted",
          style: "display:inline-flex;align-items:center;gap:6px;margin-top:2px",
        }, icon("github", { size: 14 }), `@${developer.github_username}`, icon("external-link", { size: 12 })),
        developer.bio ? el("p", { class: "prose", style: "margin-top:10px", text: developer.bio }) : null,
        el("p", { class: "hint", style: "margin-top:10px", text: `Last analysed ${fmtDate(developer.updated_at)}` })),
    ),
  }));

  /* Commit activity */
  if (activity?.commits_per_week?.length) {
    out.append(card({
      title: "Commit activity",
      subtitle: `${activity.longest_streak_weeks}-week longest streak · ${activity.average_commits_per_week.toFixed(1)} commits/week average`,
      body: el("div", {},
        el("div", { html: commitStrip(activity.commits_per_week) }),
        activity.inactive_periods?.length
          ? el("p", { class: "hint", style: "margin-top:12px",
              text: `${activity.inactive_periods.length} inactive period(s) detected in the last year.` })
          : null),
    }));
  }

  /* Score + languages side by side */
  const row = el("div", { class: "grid" });

  if (score) {
    row.append(card({
      title: "Developer score",
      subtitle: `${score.overall_score.toFixed(1)} / 100`,
      body: el("div", {},
        el("div", { html: scoreColumns(score) }),
        el("p", { class: "hint", style: "margin-top:12px",
          text: "Composite of five sub-scores; weights are defined in services/scoring.py." })),
    }));
  }

  if (languages?.distribution_percent) {
    const ratio = languages.backend_frontend_ratio || {};
    row.append(card({
      title: "Language mix",
      subtitle: languages.primary_language ? `Primary: ${languages.primary_language}` : null,
      body: el("div", {},
        el("div", { html: languageBars(languages.distribution_percent) }),
        el("dl", { class: "kv", style: "margin-top:16px" },
          el("dt", { text: "Diversity score" }), el("dd", { text: (languages.language_diversity_score ?? 0).toFixed(2) }),
          el("dt", { text: "Backend" }), el("dd", { text: `${(ratio.backend_percent ?? 0).toFixed(1)}%` }),
          el("dt", { text: "Frontend" }), el("dd", { text: `${(ratio.frontend_percent ?? 0).toFixed(1)}%` })),
        languages.ai_ml_ecosystem_detected?.length
          ? el("div", { class: "tags", style: "margin-top:16px" },
              ...languages.ai_ml_ecosystem_detected.map((item) => badge(item, "accent")))
          : null),
    }));
  }
  if (row.children.length) out.append(row);

  /* Monthly trend */
  if (activity?.commits_per_month && Object.keys(activity.commits_per_month).length > 1) {
    out.append(card({
      title: "Commits per month",
      body: el("div", { html: monthArea(activity.commits_per_month) }),
    }));
  }

  /* AI insight */
  if (summary) {
    const insight = el("div", { class: "grid" });

    insight.append(card({
      title: "Résumé summary",
      subtitle: "AI-generated",
      body: el("div", {},
        el("div", { class: "prose", html: renderMarkdown(summary.summary || "Not available.") }),
        summary.likely_expertise?.length
          ? el("div", { class: "tags", style: "margin-top:16px" },
              ...summary.likely_expertise.map((item) => badge(item, "accent")))
          : null),
    }));

    const lists = el("div", { class: "stack", style: "gap:20px" });
    if (summary.strengths?.length) lists.append(bulletBlock("Strengths", summary.strengths, "check-circle"));
    if (summary.weaknesses?.length) lists.append(bulletBlock("Gaps", summary.weaknesses, "alert-triangle"));
    if (summary.suggested_learning?.length) lists.append(bulletBlock("Suggested next", summary.suggested_learning, "target"));
    insight.append(card({ title: "Skill assessment", body: lists }));

    out.append(insight);
  }

  if (interview?.questions?.length) {
    out.append(card({
      title: "Interview questions",
      subtitle: "Personalised to this profile",
      body: el("ol", { class: "list-plain" },
        ...interview.questions.map((question, index) =>
          el("li", {},
            el("span", { class: "list-plain__index", text: String(index + 1) }),
            el("span", { text: question })))),
    }));
  }

  /* Top projects */
  if (topProjects?.length) {
    out.append(card({
      title: "Top-ranked projects",
      subtitle: "0.4·stars + 0.2·forks + 0.2·recency + 0.2·documentation",
      body: table(
        [
          { label: "#", render: (project) => String(project.rank) },
          { label: "Project", render: (project) => el("a", {
              class: "cell-primary",
              href: `https://github.com/${project.full_name}`,
              target: "_blank", rel: "noopener", text: project.name }) },
          { label: "Score", numeric: true, render: (project) => project.project_score.toFixed(1) },
          { label: "Stars", numeric: true, render: (project) => fmtNum(project.stars) },
          { label: "Forks", numeric: true, render: (project) => fmtNum(project.forks) },
        ],
        topProjects.slice(0, 10),
        { caption: "Repositories ranked by weighted project score" }),
    }));
  }

  /* All repositories */
  if (repositories?.length) {
    out.append(card({
      title: "All analysed repositories",
      subtitle: `${repositories.length} repositories`,
      body: table(
        [
          { label: "Repository", render: (repo) => el("span", { class: "row", style: "gap:8px" },
              el("a", { class: "cell-primary", href: `https://github.com/${repo.full_name}`,
                        target: "_blank", rel: "noopener", text: repo.name }),
              repo.is_archived ? badge("Archived", "neutral") : null) },
          { label: "Language", render: (repo) => el("span", { class: "cell-muted", text: repo.primary_language || "—" }) },
          { label: "Stars", numeric: true, render: (repo) => fmtNum(repo.stars) },
          { label: "Forks", numeric: true, render: (repo) => fmtNum(repo.forks) },
          { label: "Docs", render: (repo) => el("span", { class: "row", style: "gap:6px" },
              repo.has_readme ? badge("README", "success") : null,
              repo.has_license ? badge("LICENSE", "neutral") : null,
              !repo.has_readme && !repo.has_license ? el("span", { class: "cell-muted", text: "—" }) : null) },
          { label: "Pushed", numeric: true, render: (repo) => fmtDate(repo.pushed_at) },
        ],
        repositories,
        { caption: "Every repository included in the analysis" }),
    }));
  }
}

function bulletBlock(title, items, iconName) {
  return el("div", {},
    el("div", { class: "evidence__head" }, icon(iconName, { size: 13 }), title),
    el("ul", { class: "list-plain" },
      ...items.map((item, index) =>
        el("li", {},
          el("span", { class: "list-plain__index", text: String(index + 1) }),
          el("span", { text: item })))));
}

export function mountAnalyze() {
  $("#form-analyze").addEventListener("submit", (event) => {
    event.preventDefault();
    const username = $("#in-username").value.trim();
    if (!username) {
      $("#in-username").setAttribute("aria-invalid", "true");
      toast("Enter a GitHub username first.", "bad");
      return;
    }
    $("#in-username").removeAttribute("aria-invalid");
    runAnalysis(username);
  });

  for (const chip of document.querySelectorAll("[data-sample]")) {
    chip.addEventListener("click", () => runAnalysis(chip.dataset.sample));
  }

  $("#analyze-out").append(emptyState(
    "Nothing analysed yet",
    "Enter a GitHub username above to pull their repositories and build a profile.",
    { iconName: "bar-chart" }));
}
