/* View 04 — job match.
   The interface job here is to keep the arithmetic visible: every headline
   number is shown next to the weighted components that produced it, and every
   skill verdict sits next to the evidence it was drawn from. Unknowns get their
   own visual treatment so they never read as confirmed gaps. */

import { api } from "../api.js";
import { $, clear, el, escapeHtml, toast } from "../ui.js";
import {
  alert, badge, card, emptyState, errorState, icon, setBusy,
  skeletonCard, stat, statGrid, stepList, table,
} from "../components.js";
import { scoreGauge, weightedBars } from "../charts.js";
import { requireAuth } from "../auth-ui.js";

const STATUS_META = {
  strong:  { label: "Strong", variant: "success" },
  partial: { label: "Partial", variant: "accent" },
  weak:    { label: "Weak", variant: "warning" },
  missing: { label: "Not demonstrated", variant: "danger" },
  // Deliberately quiet: an unknown must never read as a failure.
  unknown: { label: "No public evidence", variant: "unknown" },
};

const MATCH_STAGES = [
  "Reading and structuring the résumé",
  "Extracting requirements from the job description",
  "Gathering GitHub evidence",
  "Scoring and explaining the match",
];

const CATEGORY_LABELS = {
  technical_skills: "Technical skills",
  work_experience: "Work experience",
  project_relevance: "Project relevance",
  tools_frameworks: "Tools & frameworks",
  education: "Education",
  engineering_practices: "Engineering practices",
};

let selectedFile = null;

export async function runJobMatch() {
  const username = $("#in-jm-username").value.trim();
  const company = $("#in-jm-company").value.trim();
  const jd = $("#in-jm-jd").value.trim();
  const out = $("#jobmatch-out");

  if (!username || !company || !jd) {
    toast("Fill in the username, company and job description.", "bad");
    return;
  }
  if (!selectedFile) {
    toast("Attach the candidate's resume as a PDF.", "bad");
    return;
  }
  if (jd.length < 40) {
    toast("Paste the full job description — that's too short to analyse.", "bad");
    return;
  }
  if (!requireAuth("Sign in to run a candidate analysis.", runJobMatch)) return;

  const submit = $("#btn-jobmatch");
  setBusy(submit, true, "Analysing…");
  clear(out).append(
    card({
      title: `${username} vs ${company}`,
      subtitle: "Parsing the résumé, the job description and the GitHub profile",
      body: stepList(MATCH_STAGES, 1),
    }),
    skeletonCard({ lines: 3, block: true }),
  );

  try {
    // Built inside the try: if the browser refuses the file for any reason, the
    // user gets an error instead of a button that spins forever.
    const form = new FormData();
    form.append("username", username);
    form.append("company", company);
    form.append("job_description", jd);
    form.append("resume_pdf", selectedFile);

    const report = await api.jobMatch(form);
    clear(out);
    render(out, report);
    toast(`${report.recommendation} — ${report.overall_match}% match`, "good");
  } catch (error) {
    clear(out).append(errorState(
      error.message,
      "Résumés must be text-based PDFs under 2 MB — scanned images cannot be read.",
      { onRetry: runJobMatch },
    ));
    toast(error.message, "bad");
  } finally {
    setBusy(submit, false);
  }
}

function render(out, report) {
  /* Headline ----------------------------------------------------------- */
  out.append(card({
    title: "Verdict",
    subtitle: report.role_title ? `Role: ${report.role_title}` : null,
    body: el("div", { class: "verdict" },
      el("div", { class: "verdict__gauge", html: scoreGauge(report.overall_match, report.recommendation) }),
      el("div", { class: "verdict__side" },
        statGrid([
          stat("Overall match", `${report.overall_match}%`, { iconName: "target" }),
          stat("Confidence", `${report.confidence}%`, { iconName: "shield", meta: "How far the evidence goes" }),
          stat("Recommendation", report.recommendation, { iconName: "gauge" }),
        ]),
        report.explanation
          ? el("p", { class: "prose", style: "margin-top:16px", text: report.explanation })
          : null)),
  }));

  /* Weighted breakdown — the arithmetic, in public ---------------------- */
  const rows = Object.entries(report.score_breakdown).map(([key, block]) => ({
    label: CATEGORY_LABELS[key] || key,
    score: block.score,
    weight: block.weight_percent,
    contribution: block.contribution,
  }));

  const totalRow = el("tr", {},
    el("td", { text: "Overall" }),
    el("td", { class: "num", text: "" }),
    el("td", { class: "num", text: "100%" }),
    el("td", { class: "num", text: String(report.overall_match) }));

  out.append(card({
    title: "How this number was calculated",
    subtitle: "Deterministic — the model does not set the score",
    body: el("div", {},
      el("div", { html: weightedBars(rows) }),
      el("div", { style: "margin-top:16px" },
        table(
          [
            { label: "Component", key: "label" },
            { label: "Score", numeric: true, render: (row) => row.score.toFixed(1) },
            { label: "Weight", numeric: true, render: (row) => `${row.weight}%` },
            { label: "Contribution", numeric: true, render: (row) => row.contribution.toFixed(2) },
          ],
          rows,
          { footer: totalRow, caption: "Component scores multiplied by their weights" })),
      report.confidence_breakdown?.penalties?.length
        ? el("div", { style: "margin-top:20px" },
            el("div", { class: "evidence__head" }, icon("shield", { size: 13 }), `Why confidence is ${report.confidence}%`),
            el("ul", { class: "list-plain" },
              ...report.confidence_breakdown.penalties.map((penalty) =>
                el("li", {},
                  el("span", { class: "list-plain__index", text: `−${penalty.penalty}` }),
                  el("span", { text: penalty.reason })))))
        : null),
  }));

  /* Skill ledger -------------------------------------------------------- */
  const counts = el("div", { class: "tags", style: "margin-bottom:16px" },
    countBadge("strong", report.strong_matches?.length),
    countBadge("partial", report.partial_matches?.length),
    countBadge("weak", report.weak_matches?.length),
    countBadge("missing", report.missing_skills?.length),
    countBadge("unknown", report.unknown_skills?.length));

  const skills = el("div");
  for (const skill of report.skill_analysis || []) {
    const meta = STATUS_META[skill.status] || STATUS_META.unknown;

    const detail = el("div", { class: "skill__detail" },
      el("p", { class: "hint", style: "padding-top:12px", text: skill.rationale }),
      el("div", { class: "evidence" },
        evidenceColumn("Résumé", skill.evidence?.resume, "file-text"),
        evidenceColumn("GitHub", skill.evidence?.github, "github")));

    const row = el("div", { class: "skill" });
    const bar = el("button", {
      class: "skill__bar",
      type: "button",
      "aria-expanded": "false",
      onClick: () => {
        const open = row.classList.toggle("is-open");
        bar.setAttribute("aria-expanded", String(open));
      },
    },
      el("span", { class: "skill__chevron" }, icon("chevron-right", { size: 15 })),
      el("span", { class: "skill__name", text: skill.skill }),
      badge(meta.label, meta.variant),
      el("span", { class: "cell-muted", text: skill.importance.replace(/_/g, " ") }),
      el("span", { class: "skill__score", text: skill.status === "unknown" ? "—" : `${skill.score}` }),
      el("span", { class: "cell-muted", text: `conf: ${skill.confidence}` }));

    row.append(bar, detail);
    skills.append(row);
  }

  out.append(card({
    title: "Skill-by-skill evidence",
    subtitle: "Select any skill to see where it was found",
    body: el("div", {},
      counts,
      skills,
      el("p", { class: "hint", style: "margin-top:16px",
        text: "“No public evidence” means neither source shows the skill either way — it is a verification gap, not a demonstrated gap, and it lowers confidence rather than counting as a failure." })),
  }));

  /* Discrepancies ------------------------------------------------------- */
  if (report.evidence_discrepancies?.length) {
    const list = el("div");
    for (const item of report.evidence_discrepancies) {
      list.append(el("div", { class: `discrepancy discrepancy--${item.type}` },
        el("div", { class: "discrepancy__icon" },
          icon(item.type === "verification_gap" ? "alert-triangle" : "check-circle", { size: 18 })),
        el("div", { style: "min-width:0" },
          el("div", { class: "discrepancy__title" },
            item.skill,
            badge(item.type.replace(/_/g, " "), item.type === "verification_gap" ? "warning" : "success")),
          el("p", { class: "prose", text: item.summary }),
          el("p", { class: "discrepancy__note", text: item.note }))));
    }
    out.append(card({
      title: "Evidence discrepancies",
      subtitle: "Where the two sources disagree",
      body: list,
    }));
  }

  /* Projects ------------------------------------------------------------ */
  if (report.project_analysis?.length) {
    out.append(card({
      title: "Project relevance",
      subtitle: "Semantic similarity plus requirement overlap",
      body: table(
        [
          { label: "Project", render: (project) => el("span", { class: "cell-primary", text: project.project }) },
          { label: "Source", render: (project) => badge(project.source, "neutral") },
          { label: "Matched requirements", render: (project) =>
              (project.matched_requirements || []).length
                ? el("span", { class: "tags" }, ...project.matched_requirements.map((item) => badge(item, "accent")))
                : el("span", { class: "cell-muted", text: "—" }) },
          { label: "Relevance", numeric: true, render: (project) => `${project.relevance}%` },
        ],
        report.project_analysis.slice(0, 12),
        { caption: "Candidate projects ranked against the job description" }),
    }));
  }

  /* Interview questions -------------------------------------------------- */
  if (report.interview_questions?.length) {
    const byCategory = {};
    for (const question of report.interview_questions) {
      (byCategory[question.category] ||= []).push(question);
    }

    const blocks = el("div", { class: "stack", style: "gap:20px" });
    for (const [category, questions] of Object.entries(byCategory)) {
      blocks.append(el("div", {},
        el("div", { class: "evidence__head" }, icon("message-square", { size: 13 }), category.replace(/_/g, " ")),
        el("ul", { class: "list-plain" },
          ...questions.map((question, index) =>
            el("li", {},
              el("span", { class: "list-plain__index", text: String(index + 1) }),
              el("span", {},
                question.question,
                question.why ? el("div", { class: "hint", style: "margin-top:2px", text: question.why }) : null))))));
    }

    out.append(card({
      title: "Interview questions",
      subtitle: "Specific to this candidate and role",
      body: blocks,
    }));
  }

  /* Learning roadmap ----------------------------------------------------- */
  if (report.learning_recommendations?.length) {
    const roadmap = el("div", { class: "stack", style: "gap:20px" });
    for (const item of report.learning_recommendations) {
      roadmap.append(el("div", {},
        el("div", { class: "evidence__head" }, icon("target", { size: 13 }), item.skill),
        item.why ? el("p", { class: "hint", style: "margin-bottom:8px", text: item.why }) : null,
        el("ol", { class: "list-plain" },
          ...(item.steps || []).map((step, index) =>
            el("li", {},
              el("span", { class: "list-plain__index", text: String(index + 1) }),
              el("span", { text: step }))))));
    }

    out.append(card({
      title: "Learning roadmap",
      subtitle: "Based on the least-evidenced requirements",
      body: roadmap,
    }));
  }

  /* Method + disclaimer -------------------------------------------------- */
  out.append(card({
    title: "Method and limitations",
    body: el("div", {},
      el("p", { class: "prose", text: report.methodology?.scoring || "" }),
      el("p", { class: "hint", style: "margin-top:10px", text: report.methodology?.unknown_handling || "" }),
      el("div", { class: "disclaimer" },
        icon("info", { size: 16 }),
        el("span", { text: report.disclaimer }))),
  }));
}

function countBadge(status, count) {
  const meta = STATUS_META[status];
  return badge(`${count || 0} ${meta.label.toLowerCase()}`, meta.variant);
}

function evidenceColumn(title, items, iconName) {
  return el("div", { class: "evidence__col" },
    el("div", { class: "evidence__head" }, icon(iconName, { size: 13 }), title),
    items?.length
      ? el("ul", { class: "evidence__list" }, ...items.map((item) => el("li", { text: item })))
      : el("p", { class: "hint", text: "No evidence found in this source." }));
}

export function mountJobMatch() {
  const fileInput = $("#in-jm-resume");
  const fileLabel = $("#jm-file-label");
  const drop = $("#jm-filedrop");

  fileInput.addEventListener("change", () => {
    selectedFile = fileInput.files?.[0] || null;
    drop.classList.toggle("has-file", Boolean(selectedFile));

    if (!selectedFile) {
      fileLabel.textContent = "No file chosen";
      return;
    }
    const sizeMb = selectedFile.size / 1_000_000;
    fileLabel.textContent = `${selectedFile.name} (${sizeMb.toFixed(2)} MB)`;
    if (sizeMb > 2) toast("That PDF is over the 2 MB limit.", "bad");
  });

  $("#form-jobmatch").addEventListener("submit", (event) => {
    event.preventDefault();
    runJobMatch();
  });

  $("#jobmatch-out").append(emptyState(
    "No analysis yet",
    "Give a GitHub username, the company, the job description and a résumé PDF.",
    { iconName: "clipboard-check" }));
}
