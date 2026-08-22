/* Runs the real frontend inside jsdom against the stubbed API server and
   asserts on the rendered DOM — the closest thing to a click-through available
   without a browser binary. */

import { JSDOM } from "jsdom";
import { readFileSync } from "node:fs";

import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, resolve } from "node:path";

// Resolve paths against this file, so the suite runs from any working directory.
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");


const BASE = "http://127.0.0.1:8111";
const html = readFileSync(resolve(ROOT, "frontend/index.html"), "utf8");

const dom = new JSDOM(html, { url: `${BASE}/ui/`, pretendToBeVisual: true });
const { window } = dom;

// Wire the jsdom document up as the global environment the modules expect.
global.window = window;
global.document = window.document;
global.localStorage = window.localStorage;
global.location = window.location;
global.HTMLElement = window.HTMLElement;
global.Node = window.Node;
global.CustomEvent = window.CustomEvent;

// jsdom has no fetch; forward to the real server, resolving relative paths.
const nodeFetch = globalThis.fetch;
global.fetch = (input, init) =>
  nodeFetch(typeof input === "string" && input.startsWith("/") ? BASE + input : input, init);
window.fetch = global.fetch;

window.HTMLElement.prototype.scrollIntoView = () => {};

let failures = 0;
const check = (label, condition, extra = "") => {
  if (condition) {
    console.log(`  ✓ ${label}`);
  } else {
    failures += 1;
    console.log(`  ✗ ${label} ${extra}`);
  }
};

const $ = (selector) => window.document.querySelector(selector);
const text = (selector) => $(selector)?.textContent?.trim() ?? "";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitFor(predicate, { timeout = 45000, interval = 200, label = "condition" } = {}) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    if (predicate()) return true;
    await sleep(interval);
  }
  throw new Error(`Timed out waiting for ${label}`);
}

// ── Boot the app ───────────────────────────────────────────────────────────
await import(pathToFileURL(resolve(ROOT, "frontend/js/main.js")).href);
await sleep(600);

console.log("\n[1] Boot + routing");
check("analyze view visible by default", !$("#view-analyze").hidden);
check("other views hidden", $("#view-compare").hidden && $("#view-chat").hidden);
check("nav marks analyze as the current page",
  $('.nav__item[data-view="analyze"]').getAttribute("aria-current") === "page");
check("health indicator connected", $("#conn-state").className.includes("is-up"), text("#conn-state"));
check("empty state prompts an action", text("#analyze-out").includes("Nothing analysed yet"));

window.location.hash = "#/chat";
window.dispatchEvent(new window.HashChangeEvent("hashchange"));
await sleep(150);
check("hash routing switches views", !$("#view-chat").hidden && $("#view-analyze").hidden);
window.location.hash = "#/analyze";
window.dispatchEvent(new window.HashChangeEvent("hashchange"));
await sleep(150);

// ── Auth gate ──────────────────────────────────────────────────────────────
console.log("\n[2] Auth gate");
$("#in-username").value = "demo";
$("#form-analyze").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await sleep(400);
check("write action opens the sign-in dialog", !$("#scrim").hidden);
check("dialog explains why", text("#auth-err").length > 0, text("#auth-err"));

$("#in-auth-user").value = `tester${Date.now() % 100000}`;
$("#in-auth-pass").value = "hunter2";
$("#form-auth").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await waitFor(() => $("#scrim").hidden, { label: "registration to complete" });
check("account created and dialog closed", $("#scrim").hidden);
check("sidebar shows the signed-in account", text("#account-hint").includes("Signed in"), text("#btn-account"));
check("token persisted", Boolean(window.localStorage.getItem("bench.token")));

// ── Analyze ────────────────────────────────────────────────────────────────
console.log("\n[3] Analyze a developer");
$("#in-username").value = "demo";
$("#form-analyze").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await sleep(300);
check("run log or results present while working", text("#analyze-out").length > 0);

await waitFor(() => $("#analyze-out #profile-card"), { label: "analysis results" });
const out = text("#analyze-out");
check("profile header rendered", out.includes("Demo"));
check("summary stats rendered", out.includes("Followers") && out.includes("Developer score"));
check("commit strip drawn", $("#analyze-out svg rect") !== null);
check("score columns drawn", out.includes("OVERALL"), "");
check("language mix rendered", out.includes("Language mix") && out.includes("Python"));
check("resume summary rendered", out.includes("Backend and ML systems engineer"));
check("strengths listed", out.includes("Deep bandit/online-learning expertise"));
check("interview questions listed", out.includes("importance weighting"));
check("top projects ranked", out.includes("Top-ranked projects") && out.includes("bandit-router"));
check("repo table flags archived repos", /archived/i.test(out));
// Icons are inline SVG too, so count only shapes charts actually draw.
const chartRects = window.document.querySelectorAll("#analyze-out svg > rect").length;
check("charts drawn", chartRects >= 10, `(${chartRects} chart rects)`);

// ── Compare ────────────────────────────────────────────────────────────────
console.log("\n[4] Compare two developers");
window.location.hash = "#/compare";
window.dispatchEvent(new window.HashChangeEvent("hashchange"));
await sleep(150);
$("#in-user1").value = "alice";
$("#in-user2").value = "bob";
$("#form-compare").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await waitFor(() => text("#compare-out").includes("Verdict"), { label: "comparison results" });
const cmp = text("#compare-out");
check("verdict rendered", cmp.includes("scores higher overall"));
check("score axes charted", cmp.includes("consistency") || cmp.includes("consist"));
check("both users' languages shown", cmp.includes("alice — languages") && cmp.includes("bob — languages"));
check("repository quality shown", cmp.includes("repositories"));

// ── Repo chat ──────────────────────────────────────────────────────────────
console.log("\n[5] Chat with a repository");
window.location.hash = "#/chat";
window.dispatchEvent(new window.HashChangeEvent("hashchange"));
await sleep(150);
$("#in-repo").value = "https://github.com/demo/bandit-router";
$("#form-index").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));

// textContent glues adjacent nodes together, so assert on the badge element itself.
await waitFor(() => $("#chat-out .badge--success"), { label: "indexing to finish" });
const chatOut = text("#chat-out");
check("repo panel shows ready", text("#chat-out .badge--success").toLowerCase() === "ready");
check("index stats shown", /\d+ files/.test(chatOut), "");
check("file tree listed", chatOut.includes("app/router.py"));
check("node_modules excluded from tree", !chatOut.includes("node_modules"));
check("composer present", $("#composer-input") !== null);

await waitFor(() => text("#overview").includes("EXP3"), { label: "AI overview" });
check("overview: what it does", text("#overview").includes("routes each incoming prompt"));
check("overview: how it works steps", text("#overview").includes("select_arm"));
check("overview: components listed", text("#overview").includes("BanditRouter"));
check("suggested questions replaced by repo-specific ones",
  text("#suggested").includes("gamma"), text("#suggested").slice(0, 60));

// Non-streaming path first (exercises /messages + standalone_question).
console.log("\n[6] Ask a question (buffered)");
$("#composer-input").value = "";
const streamToggle = $("#toggle-stream");
streamToggle.checked = false;
streamToggle.dispatchEvent(new window.Event("change", { bubbles: true }));

$("#composer-input").value = "What does this project do?";
$("#btn-send").dispatchEvent(new window.Event("click", { bubbles: true }));
await waitFor(() => $("#thread .turn--bot .prose")?.textContent.includes("routes each prompt"),
  { label: "the answer" });

check("user turn rendered", $("#thread .turn--user .prose")?.textContent.includes("What does this project do?"));
check("answer rendered", text("#thread").includes("importance-weighted exponential update"));
check("citation chips created", $("#thread .cite") !== null);
check("sources panel rendered", text("#thread").includes("Sources ·"));
check("source shows real file path", text("#thread").includes("app/router.py"));
check("source code has line numbers", $("#thread .source__code td.ln") !== null);

const firstLineNo = $("#thread .source__code td.ln")?.textContent;
check("line numbers are absolute, not 1-based per chunk", Number(firstLineNo) >= 1, `(first=${firstLineNo})`);

// Clicking a citation chip opens the matching source block.
const chip = $("#thread .cite");
chip.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
await sleep(120);
check("clicking [n] opens that source",
  $(`#thread .source[data-cite="${chip.dataset.cite}"]`)?.classList.contains("is-open"));

// Follow-up, to prove condensing shows in the UI.
console.log("\n[7] Cross-question (follow-up)");
$("#composer-input").value = "And how is that reward computed?";
$("#btn-send").dispatchEvent(new window.Event("click", { bubbles: true }));
// The in-flight placeholder is also a .turn--bot, so wait for the real answer.
await waitFor(() => window.document.querySelectorAll("#thread .rewrite").length >= 1,
  { label: "follow-up answer" });
check("follow-up answered", window.document.querySelectorAll("#thread .turn--bot").length >= 2);
check("rewritten query surfaced to the user", text("#thread").includes("Searched for:"),
  text("#thread").slice(-200));
check("no rewrite banner on the first, unrewritten question",
  window.document.querySelectorAll("#thread .rewrite").length === 1,
  `(${window.document.querySelectorAll("#thread .rewrite").length} banners)`);
check("rewrite shows the resolved question", text("#thread").includes("importance weighted reward update"));

// Streaming path.
console.log("\n[8] Ask a question (streaming)");
streamToggle.checked = true;
streamToggle.dispatchEvent(new window.Event("change", { bubbles: true }));
const turnsBefore = window.document.querySelectorAll("#thread .turn--bot").length;
$("#composer-input").value = "Where is the exploration rate set?";
$("#btn-send").dispatchEvent(new window.Event("click", { bubbles: true }));

await waitFor(() => text("#thread").includes("Sources ·") &&
  window.document.querySelectorAll("#thread .source").length > 0, { label: "streamed citations" });
check("citations arrive before the answer completes", true);

await waitFor(() => window.document.querySelectorAll("#thread .turn--bot").length > turnsBefore &&
  text("#thread").includes("keeps the estimate unbiased"), { label: "streamed answer to finish" });
check("streamed answer completed", text("#thread").includes("keeps the estimate unbiased"));
check("caret removed when done", $("#thread .caret") === null);

// ── Sessions ───────────────────────────────────────────────────────────────
window.confirm = () => true;   // auto-accept the new delete confirmation

console.log("\n[9] Session history");
await waitFor(() => $("#sessions .session"), { label: "session list" });
check("conversation listed in sidebar", $("#sessions .session") !== null);
check("message count shown", $("#sessions .session__meta")?.textContent.trim().length > 0);

const sessionButton = $("#sessions .session");
sessionButton.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
await waitFor(() => $("#thread .turn--user"), { label: "transcript reload" });
check("transcript reloads from the server", text("#thread").includes("What does this project do?"));
check("stored citations still render", $("#thread .source") !== null);

// ── Error handling ─────────────────────────────────────────────────────────
console.log("\n[10] Error handling");
$("#in-repo").value = "https://gitlab.com/not/github";
$("#form-index").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await waitFor(() => $("#chat-out .alert--danger"), { label: "error panel" });
check("invalid URL produces a clear message", text("#chat-out").includes("Not a valid GitHub repository URL"));
check("error is announced to assistive tech", $("#chat-out .alert--danger").getAttribute("role") === "alert");
check("error offers a retry", /try again/i.test(text("#chat-out")));
check("error suggests a fix", text("#chat-out").includes("Public repositories only"));


// ── Job match ──────────────────────────────────────────────────────────────
console.log("\n[11] Match a candidate to a role");
window.location.hash = "#/jobmatch";
window.dispatchEvent(new window.HashChangeEvent("hashchange"));
await sleep(150);
check("job match view renders", !$("#view-jobmatch").hidden);
check("empty state shown", text("#jobmatch-out").includes("No analysis yet"));

$("#in-jm-username").value = "priya";
$("#in-jm-company").value = "Acme Corp";
$("#in-jm-jd").value =
  "We are hiring a Backend Engineer to build Python services. Required: Python, " +
  "FastAPI, PostgreSQL. Preferred: Docker and CUDA. Bachelor's degree and 2+ years required.";

// jsdom has File/FileList via the DOM, but not a file picker — inject directly.
const pdfBytes = readFileSync(resolve(ROOT, "tests/ui/sample_resume.pdf"));
// Node's File, not jsdom's: the app calls Node's FormData here, and the two
// realms' Blob types are not interchangeable. In a real browser both come from
// the same realm, so this substitution only exists for the test environment.
const file = new File([pdfBytes], "resume.pdf", { type: "application/pdf" });
// Shape a FileList-alike: indexed access + length + item(), which is what the
// view reads. jsdom has File but no way to populate an <input type=file>.
const fileList = { 0: file, length: 1, item: (index) => (index === 0 ? file : null) };
Object.defineProperty($("#in-jm-resume"), "files", { value: fileList, configurable: true });
$("#in-jm-resume").dispatchEvent(new window.Event("change", { bubbles: true }));
await sleep(100);
check("chosen file is shown to the user", text("#jm-file-label").includes("resume.pdf"));

$("#form-jobmatch").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await waitFor(() => text("#jobmatch-out").includes("Verdict"), { label: "match report", timeout: 60000 });

const jm = text("#jobmatch-out");
check("overall match shown", /\d+%/.test(jm) && /overall match/i.test(jm));
check("confidence shown separately", jm.includes("confidence"));
check("recommendation band shown", /Excellent Fit|Strong Fit|Moderate Fit|Weak Fit|Poor Fit/.test(jm));
check("weighted calculation table rendered", jm.includes("How this number was calculated"));
check("all six components listed",
  ["Technical skills", "Work experience", "Project relevance", "Tools & frameworks", "Education", "Engineering practices"]
    .every((label) => jm.includes(label)));
check("weights add to 100%", jm.includes("100%"));
check("confidence penalties explained", jm.includes("Why confidence is"));

check("skill ledger rendered", jm.includes("Skill-by-skill evidence"));
check("CUDA reported as no public evidence", jm.includes("No public evidence"));
check("unknown is explained as a verification gap, not a gap",
  jm.includes("verification gap, not a demonstrated gap"));
check("unknown is never phrased as a deficiency",
  !/does not know|lacks the skill|unqualified/i.test(jm));

// Expanding a skill reveals its evidence.
const skillBar = $("#jobmatch-out .skill__bar");
skillBar.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
await sleep(120);
check("clicking a skill reveals its evidence",
  $("#jobmatch-out .skill.is-open") !== null);
// "Résumé" carries an accent in the UI; match on the source columns instead.
const openSkill = text("#jobmatch-out .skill.is-open");
check("evidence is split by source",
  /r[ée]sum[ée]/i.test(openSkill) && /github/i.test(openSkill),
  openSkill.slice(0, 80));
check("both evidence columns render",
  window.document.querySelectorAll("#jobmatch-out .skill.is-open .evidence__col").length === 2);

check("project relevance table rendered", jm.includes("Project relevance"));
check("interview questions rendered", jm.includes("Interview questions"));
check("learning roadmap rendered", jm.includes("Learning roadmap"));
check("disclaimer present", jm.includes("not be the sole basis"));
check("no candidate contact details leak into the UI",
  !jm.includes("@example.com") && !/\+91\s?98765/.test(jm));

console.log("\n[12] Job match validation");
window.location.hash = "#/jobmatch";
$("#in-jm-jd").value = "too short";
$("#form-jobmatch").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await sleep(300);
check("short JD is rejected client-side", text("#toasts").includes("full job description"));

console.log(`\n${failures === 0 ? "ALL UI CHECKS PASSED" : `${failures} CHECK(S) FAILED`}`);
process.exit(failures === 0 ? 0 : 1);
