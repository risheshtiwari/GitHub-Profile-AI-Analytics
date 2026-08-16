/* View 04 — job match.
   The interface job here is to keep the arithmetic visible: every headline
   number is shown next to the weighted components that produced it, and every
   skill verdict sits next to the evidence it was drawn from. Unknowns get their
   own visual treatment so they never read as confirmed gaps. */

import { api } from "../api.js";
import { $, busyButton, clear, el, empty, escapeHtml, panel, toast } from "../ui.js";
import { scoreGauge, weightedBars } from "../charts.js";
import { requireAuth } from "../auth-ui.js";

const STATUS_META = {
  strong: { label: "Strong", tag: "tag--good" },
  partial: { label: "Partial", tag: "tag--signal" },
  weak: { label: "Weak", tag: "tag--warn" },
  missing: { label: "Not demonstrated", tag: "tag--bad" },
  unknown: { label: "No public evidence", tag: "tag--unknown" },
};

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

  const button = $("#btn-jobmatch");
  busyButton(button, true, "Analysing…");
  clear(out).append(panel("RUN", `${username} vs ${company}`,
    "parsing the resume, the JD, and the GitHub profile",
    el("div", { class: "progress" }, el("i", {}))));

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
    clear(out).append(panel("ERR", "Analysis stopped", null,
      el("p", { class: "prose", text: error.message }),
      el("p", { class: "field__note", text: "Resumes must be text-based PDFs under 2 MB. Scanned images can't be read." })));
    toast(error.message, "bad");
  } finally {
    busyButton(button, false);
  }
}

function render(out, report) {
  /* Headline ----------------------------------------------------------- */
  out.append(panel("FIT", "Verdict", report.role_title ? `role: ${report.role_title}` : null,
    el("div", { class: "verdict" },
      el("div", { html: scoreGauge(report.overall_match, report.recommendation) }),
      el("div", { class: "verdict__side" },
        el("div", { class: "stats" },
          stat(`${report.overall_match}%`, "overall match"),
          stat(`${report.confidence}%`, "confidence"),
          stat(report.recommendation, "recommendation")),
        report.explanation ? el("p", { class: "prose", style: "margin-top:14px", text: report.explanation }) : null))));

  /* Weighted breakdown — the arithmetic, in public ---------------------- */
  const rows = Object.entries(report.score_breakdown).map(([key, block]) => ({
    label: CATEGORY_LABELS[key] || key,
    score: block.score,
    weight: block.weight_percent,
    contribution: block.contribution,
  }));

  out.append(panel("CAL", "How this number was calculated",
    "deterministic — the model does not set the score",
    el("div", { html: weightedBars(rows) }),
    el("div", { style: "overflow-x:auto;margin-top:12px" },
      el("table", { class: "data" },
        el("thead", {}, el("tr", {},
          el("th", { text: "Component" }), el("th", { class: "num", text: "Score" }),
          el("th", { class: "num", text: "Weight" }), el("th", { class: "num", text: "Contribution" }))),
        el("tbody", {},
          ...rows.map((row) => el("tr", {},
            el("td", { text: row.label }),
            el("td", { class: "num", text: `${row.score}` }),
            el("td", { class: "num", text: `${row.weight}%` }),
            el("td", { class: "num", text: row.contribution.toFixed(2) }))),
          el("tr", { style: "font-weight:600" },
            el("td", { text: "Overall" }), el("td", { class: "num", text: "" }),
            el("td", { class: "num", text: "100%" }),
            el("td", { class: "num", text: `${report.overall_match}` }))))),
    report.confidence_breakdown?.penalties?.length
      ? el("div", {},
          el("div", { class: "field__label", style: "margin-top:16px", text: `Why confidence is ${report.confidence}%` }),
          el("ul", { class: "list" },
            ...report.confidence_breakdown.penalties.map((penalty, index) =>
              el("li", {},
                el("span", { class: "list__ord", text: `−${penalty.penalty}` }),
                el("span", { text: penalty.reason })))))
      : null));

  /* Skill ledger -------------------------------------------------------- */
  const counts = el("div", { class: "tags", style: "margin-bottom:14px" },
    countTag("strong", report.strong_matches?.length),
    countTag("partial", report.partial_matches?.length),
    countTag("weak", report.weak_matches?.length),
    countTag("missing", report.missing_skills?.length),
    countTag("unknown", report.unknown_skills?.length));

  const skills = el("div");
  for (const skill of report.skill_analysis || []) {
    const meta = STATUS_META[skill.status] || STATUS_META.unknown;
    const body = el("div", { class: "skill__detail" },
      el("p", { class: "field__note", style: "margin-top:0", text: skill.rationale }));

    const evidenceGrid = el("div", { class: "evidence" });
    evidenceGrid.append(evidenceColumn("Resume", skill.evidence?.resume));
    evidenceGrid.append(evidenceColumn("GitHub", skill.evidence?.github));
    body.append(evidenceGrid);

    const row = el("div", { class: "skill" });
    row.append(
      el("button", {
        class: "skill__bar",
        onClick: () => row.classList.toggle("is-open"),
      },
        el("span", { class: "skill__name", text: skill.skill }),
        el("span", { class: `tag ${meta.tag}`, text: meta.label }),
        el("span", { class: "repo-lang", text: skill.importance.replace("_", " ") }),
        el("span", { class: "skill__score", text: skill.status === "unknown" ? "—" : `${skill.score}` }),
        el("span", { class: "repo-lang", text: `conf: ${skill.confidence}` })),
      body);
    skills.append(row);
  }

  out.append(panel("SKL", "Skill-by-skill evidence", "click any skill to see where it was found",
    counts, skills,
    el("p", { class: "field__note", style: "margin-top:14px",
      text: "“No public evidence” means neither source shows the skill either way — it is a verification gap, not a demonstrated gap, and it lowers confidence rather than counting as a failure." })));

  /* Discrepancies ------------------------------------------------------- */
  if (report.evidence_discrepancies?.length) {
    const list = el("div");
    for (const item of report.evidence_discrepancies) {
      list.append(el("div", { class: `discrepancy discrepancy--${item.type}` },
        el("div", { class: "discrepancy__head" },
          el("span", { class: "discrepancy__icon", text: item.type === "verification_gap" ? "⚠" : "＋" }),
          el("strong", { text: item.skill }),
          el("span", { class: "repo-lang", text: item.type.replace("_", " ") })),
        el("p", { class: "prose", text: item.summary }),
        el("p", { class: "field__note", text: item.note })));
    }
    out.append(panel("DIS", "Evidence discrepancies", "differences between the two sources", list));
  }

  /* Projects ------------------------------------------------------------ */
  if (report.project_analysis?.length) {
    out.append(panel("PRJ", "Project relevance", "semantic similarity + requirement overlap",
      el("div", { style: "overflow-x:auto" },
        el("table", { class: "data" },
          el("thead", {}, el("tr", {},
            el("th", { text: "Project" }), el("th", { text: "Source" }),
            el("th", { text: "Matched requirements" }), el("th", { class: "num", text: "Relevance" }))),
          el("tbody", {},
            ...report.project_analysis.slice(0, 12).map((project) => el("tr", {},
              el("td", { class: "repo-name", text: project.project }),
              el("td", { html: `<span class="repo-lang">${escapeHtml(project.source)}</span>` }),
              el("td", { html: (project.matched_requirements || []).length
                ? project.matched_requirements.map((r) => `<span class="tag">${escapeHtml(r)}</span>`).join(" ")
                : '<span class="repo-lang">—</span>' }),
              el("td", { class: "num", text: `${project.relevance}%` }))))))));
  }

  /* Interview questions -------------------------------------------------- */
  if (report.interview_questions?.length) {
    const byCategory = {};
    for (const question of report.interview_questions) {
      (byCategory[question.category] ||= []).push(question);
    }
    const blocks = el("div");
    for (const [category, questions] of Object.entries(byCategory)) {
      blocks.append(
        el("div", { class: "field__label", style: "margin-top:14px", text: category.replace("_", " ") }),
        el("ul", { class: "list" },
          ...questions.map((question, index) =>
            el("li", {},
              el("span", { class: "list__ord", text: String(index + 1).padStart(2, "0") }),
              el("span", {}, question.question,
                question.why ? el("span", { class: "repo-lang", text: ` — ${question.why}` }) : null)))));
    }
    out.append(panel("INT", "Interview questions", "specific to this candidate and role", blocks));
  }

  /* Learning roadmap ----------------------------------------------------- */
  if (report.learning_recommendations?.length) {
    const roadmap = el("div");
    for (const item of report.learning_recommendations) {
      roadmap.append(
        el("div", { class: "field__label", style: "margin-top:14px", text: item.skill }),
        item.why ? el("p", { class: "field__note", style: "margin:0 0 6px", text: item.why }) : null,
        el("ol", { class: "list" },
          ...(item.steps || []).map((step, index) =>
            el("li", {},
              el("span", { class: "list__ord", text: String(index + 1).padStart(2, "0") }),
              el("span", { text: step })))));
    }
    out.append(panel("LRN", "Learning roadmap", "based on the weakest evidenced requirements", roadmap));
  }

  /* Method + disclaimer -------------------------------------------------- */
  out.append(panel("MET", "Method and limitations", null,
    el("p", { class: "prose", text: report.methodology?.scoring || "" }),
    el("p", { class: "field__note", text: report.methodology?.unknown_handling || "" }),
    el("p", { class: "disclaimer", text: report.disclaimer })));
}

function stat(value, key) {
  return el("div", { class: "stat" },
    el("div", { class: "stat__val", text: value }),
    el("div", { class: "stat__key", text: key }));
}

function countTag(status, count) {
  const meta = STATUS_META[status];
  return el("span", { class: `tag ${meta.tag}`, text: `${count || 0} ${meta.label.toLowerCase()}` });
}

function evidenceColumn(title, items) {
  return el("div", {},
    el("div", { class: "field__label", text: title }),
    items?.length
      ? el("ul", { class: "evidence__list" }, ...items.map((item) => el("li", { text: item })))
      : el("p", { class: "field__note", style: "margin:0", text: "No evidence found in this source." }));
}

export function mountJobMatch() {
  const fileInput = $("#in-jm-resume");
  const fileLabel = $("#jm-file-label");

  fileInput.addEventListener("change", () => {
    selectedFile = fileInput.files?.[0] || null;
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

  $("#jobmatch-out").append(empty(
    "No analysis yet",
    "Give a GitHub username, the company, the job description and a resume PDF."));
}
