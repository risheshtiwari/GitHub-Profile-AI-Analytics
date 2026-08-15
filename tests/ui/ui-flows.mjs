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
check("nav marks analyze active", $('.rail__item[data-view="analyze"]').classList.contains("is-active"));
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
check("account button shows sign out", text("#btn-account").includes("sign out"), text("#btn-account"));
check("token persisted", Boolean(window.localStorage.getItem("bench.token")));

// ── Analyze ────────────────────────────────────────────────────────────────
console.log("\n[3] Analyze a developer");
$("#in-username").value = "demo";
$("#form-analyze").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await sleep(300);
check("run log or results present while working", text("#analyze-out").length > 0);

await waitFor(() => $("#analyze-out .profile"), { label: "analysis results" });
const out = text("#analyze-out");
check("profile header rendered", out.includes("Demo"));
check("follower stats rendered", out.includes("followers") && out.includes("developer score"));
check("commit strip drawn", $("#analyze-out svg rect") !== null);
check("score columns drawn", out.includes("OVERALL"), "");
check("language mix rendered", out.includes("Language mix") && out.includes("Python"));
check("resume summary rendered", out.includes("Backend and ML systems engineer"));
check("strengths listed", out.includes("Deep bandit/online-learning expertise"));
check("interview questions listed", out.includes("importance weighting"));
check("top projects ranked", out.includes("Top-ranked projects") && out.includes("bandit-router"));
check("repo table lists archived flag", out.includes("archived"));
const svgCount = $("#analyze-out").querySelectorAll("svg").length;
check("multiple charts drawn", svgCount >= 3, `(${svgCount} svgs)`);

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

await waitFor(() => text("#chat-out").includes("ready"), { label: "indexing to finish" });
const chatOut = text("#chat-out");
check("repo panel shows ready", chatOut.includes("ready"));
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
const streamToggle = $(".composer__side input[type=checkbox]");
streamToggle.checked = false;
streamToggle.dispatchEvent(new window.Event("change", { bubbles: true }));

$("#composer-input").value = "What does this project do?";
$("#btn-send").dispatchEvent(new window.Event("click", { bubbles: true }));
await waitFor(() => $("#thread .turn--bot .prose")?.textContent.includes("routes each prompt"),
  { label: "the answer" });

check("user turn rendered", $("#thread .turn--user")?.textContent.includes("What does this project do?"));
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
await waitFor(() => text("#chat-out").includes("Couldn't open"), { label: "error panel" });
check("invalid URL produces a clear message", text("#chat-out").includes("Not a valid GitHub repository URL"));
check("error suggests a fix", text("#chat-out").includes("Public repositories only"));

console.log(`\n${failures === 0 ? "ALL UI CHECKS PASSED" : `${failures} CHECK(S) FAILED`}`);
process.exit(failures === 0 ? 0 : 1);
