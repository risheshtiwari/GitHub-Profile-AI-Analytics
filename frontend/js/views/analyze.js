/* View 01 — analyze a developer.
   POST /analyze does the heavy work, then the read endpoints are fetched in
   parallel and rendered. The run log shows which stage is in flight, because a
   cold analysis can take 40s and a silent spinner reads as a hang. */

import { api } from "../api.js";
import { $, busyButton, clear, el, empty, escapeHtml, fmtDate, fmtNum, panel, renderMarkdown, toast } from "../ui.js";
import { commitStrip, languageBars, monthArea, scoreColumns } from "../charts.js";
import { requireAuth } from "../auth-ui.js";

const STAGES = [
  ["collect", "Collecting repositories, languages and commit history"],
  ["analyze", "Computing repository, language and activity analytics"],
  ["ai", "Generating skill assessment, résumé summary and questions"],
  ["read", "Loading results"],
];

function runLog(activeIndex, failedIndex = -1) {
  return el("div", { class: "runlog" },
    ...STAGES.map(([, label], index) => {
      let state = "is-wait";
      if (index === failedIndex) state = "is-fail";
      else if (index < activeIndex) state = "is-done";
      else if (index === activeIndex) state = "is-run";
      return el("div", { class: state, text: label });
    }));
}

export async function runAnalysis(username) {
  const out = clear($("#analyze-out"));
  const button = $("#btn-analyze");
  const input = $("#in-username");
  input.value = username;

  if (!requireAuth("Sign in to run an analysis.", () => runAnalysis(username))) return;

  busyButton(button, true, "Analysing…");
  const progress = panel("RUN", `Analysing ${username}`, "this can take up to a minute", runLog(0));
  out.append(progress);

  try {
    await api.analyze(username);
    clear(progress).append(
      el("div", { class: "panel__head" }, el("h2", { class: "panel__title", text: `Analysing ${username}` })),
      runLog(3));

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
    clear(out).append(
      panel("ERR", "Analysis stopped", null,
        el("p", { class: "prose", text: error.message }),
        el("p", { class: "field__note", text: error.status === 404
          ? "Check the spelling — that GitHub user doesn't exist."
          : "If this is a rate limit, add a GITHUB_TOKEN to your .env and restart." })));
    toast(error.message, "bad");
  } finally {
    busyButton(button, false);
  }
}

function render(out, data) {
  const { developer, score, languages, activity, repositories, topProjects, summary, interview } = data;

  /* Profile ------------------------------------------------------------ */
  out.append(panel("PRO", null, null,
    el("div", { class: "profile" },
      developer.avatar_url && el("img", { class: "profile__avatar", src: developer.avatar_url, alt: "" }),
      el("div", { class: "profile__body" },
        el("h2", { class: "profile__name", text: developer.name || developer.github_username }),
        el("div", { class: "profile__handle" },
          el("a", { href: `https://github.com/${developer.github_username}`, target: "_blank", rel: "noopener",
            text: `@${developer.github_username}` })),
        developer.bio && el("p", { class: "profile__bio", text: developer.bio }),
        el("div", { class: "stats" },
          stat(fmtNum(developer.followers), "followers"),
          stat(fmtNum(developer.following), "following"),
          stat(fmtNum(developer.public_repos), "public repos"),
          stat(developer.score != null ? developer.score.toFixed(1) : "—", "developer score"),
          stat(fmtDate(developer.updated_at), "analysed"))))));

  /* Commit strip — the characteristic artefact of a GitHub profile ------ */
  if (activity?.commits_per_week?.length) {
    out.append(panel("ACT", "Commit activity", 
      `${activity.longest_streak_weeks} week streak · ${activity.average_commits_per_week.toFixed(1)} commits/week avg`,
      el("div", { html: commitStrip(activity.commits_per_week) }),
      activity.inactive_periods?.length
        ? el("p", { class: "field__note", text: `${activity.inactive_periods.length} inactive period(s) detected in the last year.` })
        : null));
  }

  /* Score + languages -------------------------------------------------- */
  const row = el("div", { class: "grid-2" });
  if (score) {
    row.append(panel("SCR", "Developer score", `${score.overall_score.toFixed(1)} / 100`,
      el("div", { html: scoreColumns(score) }),
      el("p", { class: "field__note", text: "Composite of five sub-scores; weights are defined in services/scoring.py." })));
  }
  if (languages?.distribution_percent) {
    const ratio = languages.backend_frontend_ratio || {};
    row.append(panel("LNG", "Language mix", languages.primary_language ? `primary: ${languages.primary_language}` : null,
      el("div", { html: languageBars(languages.distribution_percent) }),
      el("dl", { class: "kv" },
        el("dt", { text: "Diversity" }), el("dd", { text: (languages.language_diversity_score ?? 0).toFixed(2) }),
        el("dt", { text: "Backend" }), el("dd", { text: `${(ratio.backend_percent ?? 0).toFixed(1)}%` }),
        el("dt", { text: "Frontend" }), el("dd", { text: `${(ratio.frontend_percent ?? 0).toFixed(1)}%` })),
      languages.ai_ml_ecosystem_detected?.length
        ? el("div", { class: "tags", style: "margin-top:12px" },
            ...languages.ai_ml_ecosystem_detected.map((item) => el("span", { class: "tag tag--flag", text: item })))
        : null));
  }
  if (row.children.length) out.append(row);

  /* Monthly trend ------------------------------------------------------ */
  if (activity?.commits_per_month && Object.keys(activity.commits_per_month).length > 1) {
    out.append(panel("TRD", "Commits per month", null, el("div", { html: monthArea(activity.commits_per_month) })));
  }

  /* AI insight --------------------------------------------------------- */
  if (summary) {
    const insight = el("div", { class: "grid-2" });
    insight.append(panel("SUM", "Résumé summary", "AI-generated",
      el("div", { class: "prose", html: renderMarkdown(summary.summary || "Not available.") }),
      summary.likely_expertise?.length
        ? el("div", { class: "tags", style: "margin-top:12px" },
            ...summary.likely_expertise.map((item) => el("span", { class: "tag tag--signal", text: item })))
        : null));

    const lists = el("div");
    if (summary.strengths?.length) lists.append(bulletBlock("Strengths", summary.strengths));
    if (summary.weaknesses?.length) lists.append(bulletBlock("Gaps", summary.weaknesses));
    if (summary.suggested_learning?.length) lists.append(bulletBlock("Suggested next", summary.suggested_learning));
    insight.append(panel("SKL", "Skill assessment", null, lists));
    out.append(insight);
  }

  if (interview?.questions?.length) {
    out.append(panel("INT", "Interview questions", "personalised to this profile",
      el("ol", { class: "list" },
        ...interview.questions.map((question, index) =>
          el("li", {},
            el("span", { class: "list__ord", text: String(index + 1).padStart(2, "0") }),
            el("span", { text: question }))))));
  }

  /* Repositories ------------------------------------------------------- */
  if (topProjects?.length) {
    out.append(panel("TOP", "Top-ranked projects", "0.4·stars + 0.2·forks + 0.2·recency + 0.2·docs",
      table(
        ["#", "Project", "Score", "Stars", "Forks"],
        topProjects.slice(0, 10).map((project) => [
          { value: String(project.rank).padStart(2, "0"), mono: true },
          { html: `<a class="repo-name" href="https://github.com/${escapeHtml(project.full_name)}" target="_blank" rel="noopener">${escapeHtml(project.name)}</a>` },
          { value: project.project_score.toFixed(1), num: true },
          { value: fmtNum(project.stars), num: true },
          { value: fmtNum(project.forks), num: true },
        ]))));
  }

  if (repositories?.length) {
    out.append(panel("REP", "All analysed repositories", `${repositories.length} repos`,
      table(
        ["Repository", "Language", "Stars", "Forks", "Docs", "Pushed"],
        repositories.map((repo) => [
          { html: `<a class="repo-name" href="https://github.com/${escapeHtml(repo.full_name)}" target="_blank" rel="noopener">${escapeHtml(repo.name)}</a>${repo.is_archived ? ' <span class="tag">archived</span>' : ""}` },
          { html: `<span class="repo-lang">${escapeHtml(repo.primary_language || "—")}</span>` },
          { value: fmtNum(repo.stars), num: true },
          { value: fmtNum(repo.forks), num: true },
          { html: `<span class="repo-lang">${repo.has_readme ? "README" : "—"}${repo.has_license ? " · LICENSE" : ""}</span>` },
          { value: fmtDate(repo.pushed_at), num: true },
        ]))));
  }
}

function stat(value, key) {
  return el("div", { class: "stat" },
    el("div", { class: "stat__val", text: value }),
    el("div", { class: "stat__key", text: key }));
}

function bulletBlock(title, items) {
  return el("div", { style: "margin-bottom:14px" },
    el("div", { class: "field__label", text: title }),
    el("ul", { class: "list" },
      ...items.map((item, index) =>
        el("li", {},
          el("span", { class: "list__ord", text: String(index + 1).padStart(2, "0") }),
          el("span", { text: item })))));
}

function table(headers, rows) {
  const head = el("tr", {}, ...headers.map((header, index) =>
    el("th", { class: index > 1 ? "num" : "", text: header })));
  const body = rows.map((cells) =>
    el("tr", {}, ...cells.map((cell) =>
      el("td", { class: cell.num || cell.mono ? "num" : "", html: cell.html, text: cell.html ? undefined : cell.value }))));
  return el("div", { style: "overflow-x:auto" },
    el("table", { class: "data" }, el("thead", {}, head), el("tbody", {}, ...body)));
}

export function mountAnalyze() {
  $("#form-analyze").addEventListener("submit", (event) => {
    event.preventDefault();
    const username = $("#in-username").value.trim();
    if (username) runAnalysis(username);
  });

  for (const chip of document.querySelectorAll("[data-sample]")) {
    chip.addEventListener("click", () => runAnalysis(chip.dataset.sample));
  }

  $("#analyze-out").append(empty(
    "Nothing analysed yet",
    "Enter a GitHub username above to pull their repositories and build a profile."));
}
