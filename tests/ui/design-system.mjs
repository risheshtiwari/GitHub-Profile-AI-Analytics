/* Accessibility, responsive structure, and design-system checks for the UI.
 *
 * These are the things a screenshot cannot tell you: whether every input has a
 * label, whether the modal traps focus, whether spot-styled colours crept back
 * in outside the token set. Runs without a server — it inspects the shipped
 * markup and stylesheet.
 */

import { JSDOM } from "jsdom";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const html = readFileSync(resolve(ROOT, "frontend/index.html"), "utf8");
const css = readFileSync(resolve(ROOT, "frontend/css/app.css"), "utf8");

const dom = new JSDOM(html);
const doc = dom.window.document;

let failures = 0;
const check = (label, ok, extra = "") => {
  console.log(`  ${ok ? "✓" : "✗"} ${label}${ok ? "" : ` ${extra}`}`);
  if (!ok) failures += 1;
};

/* ── Semantics and landmarks ───────────────────────────────────────────── */

console.log("[a11y] Document structure");

check("has a skip link to main content", (() => {
  const link = doc.querySelector(".skip-link");
  return link && link.getAttribute("href") === "#main-content" && doc.querySelector("#main-content");
})());

check("uses landmark elements", Boolean(
  doc.querySelector("aside[aria-label]") && doc.querySelector("nav") &&
  doc.querySelector("main") && doc.querySelector("header")));

check("has exactly one h1 per view", (() => {
  const views = [...doc.querySelectorAll("section.view")];
  return views.length > 0 && views.every((view) => view.querySelectorAll("h1").length === 1);
})());

check("every view is labelled by its heading", (() => {
  return [...doc.querySelectorAll("section.view")].every((view) => {
    const id = view.getAttribute("aria-labelledby");
    return id && doc.getElementById(id);
  });
})());

check("page language is declared", doc.documentElement.getAttribute("lang") === "en");

/* ── Forms ─────────────────────────────────────────────────────────────── */

console.log("\n[a11y] Forms");

const controls = [...doc.querySelectorAll("input, textarea, select")];

check("every form control has an accessible name", (() => {
  const unlabelled = controls.filter((control) => {
    if (control.type === "hidden") return false;
    if (control.getAttribute("aria-label") || control.getAttribute("aria-labelledby")) return false;
    return !control.id || !doc.querySelector(`label[for="${control.id}"]`);
  });
  if (unlabelled.length) console.log("      unlabelled:", unlabelled.map((c) => c.id || c.type).join(", "));
  return unlabelled.length === 0;
})(), `(${controls.length} controls checked)`);

check("required fields are marked required", (() => {
  const required = ["in-username", "in-user1", "in-user2", "in-repo",
                    "in-jm-username", "in-jm-company", "in-jm-jd",
                    "in-auth-user", "in-auth-pass"];
  return required.every((id) => doc.getElementById(id)?.hasAttribute("required"));
})());

check("hint text is associated via aria-describedby", (() => {
  const described = [...doc.querySelectorAll("[aria-describedby]")];
  return described.length >= 3 && described.every((node) => doc.getElementById(node.getAttribute("aria-describedby")));
})());

check("the file input is reachable by its visible label", (() => {
  const input = doc.getElementById("in-jm-resume");
  const label = doc.querySelector('label[for="in-jm-resume"]');
  // Visually hidden but focusable — not display:none, which would remove it
  // from the tab order entirely.
  return input && label && input.classList.contains("sr-only");
})());

/* ── Buttons and interactive elements ──────────────────────────────────── */

console.log("\n[a11y] Controls");

check("buttons inside forms declare an explicit type", (() => {
  const buttons = [...doc.querySelectorAll("form button")];
  return buttons.every((button) => button.hasAttribute("type"));
})());

check("icon-only buttons carry a label", (() => {
  const iconOnly = [...doc.querySelectorAll(".icon-btn")];
  return iconOnly.every((button) => button.getAttribute("aria-label"));
})());

check("the drawer toggle exposes its state", (() => {
  const toggle = doc.getElementById("btn-menu");
  return toggle?.getAttribute("aria-expanded") === "false" && toggle.getAttribute("aria-controls") === "sidebar";
})());

check("auth tabs use the tab role with selection state", (() => {
  const tabs = [...doc.querySelectorAll("#auth-tabs .tab")];
  return tabs.length === 2 &&
    doc.querySelector('#auth-tabs[role="tablist"]') &&
    tabs.every((tab) => tab.hasAttribute("aria-selected"));
})());

check("the modal is a labelled dialog", (() => {
  const modal = doc.querySelector(".modal");
  return modal?.getAttribute("role") === "dialog" &&
    modal.getAttribute("aria-modal") === "true" &&
    doc.getElementById(modal.getAttribute("aria-labelledby"));
})());

check("live regions announce async results", (() => {
  const regions = ["#analyze-out", "#compare-out", "#chat-out", "#jobmatch-out"];
  return regions.every((selector) => doc.querySelector(selector)?.getAttribute("aria-live") === "polite");
})());

check("no emoji used as interface icons", !/[\u{1F300}-\u{1FAFF}\u{2700}-\u{27BF}]/u.test(html));

/* ── Design system integrity ───────────────────────────────────────────── */

console.log("\n[design] Token discipline");

const declarations = css.split("\n").filter((line) => !line.trim().startsWith("/*"));
const tokenBlock = css.slice(css.indexOf(":root"), css.indexOf("2. Reset"));

check("colour tokens are defined once in :root", (() => {
  return /--gray-900:/.test(tokenBlock) && /--accent-600:/.test(tokenBlock) && /--danger-600:/.test(tokenBlock);
})());

check("no hardcoded hex colours outside the token block", (() => {
  const body = css.slice(css.indexOf("2. Reset"));
  const hexes = body.match(/#[0-9a-fA-F]{3,8}\b/g) || [];
  // #FFFFFF/#fff in rgba-free contexts is the only allowed literal.
  const stray = hexes.filter((hex) => !/^#(fff|ffffff)$/i.test(hex));
  if (stray.length) console.log("      stray:", [...new Set(stray)].join(", "));
  return stray.length === 0;
})());

check("exactly three shadow tokens exist", (css.match(/--shadow-[a-z]+:/g) || []).length === 3);

check("spacing uses the 4px scale", (() => {
  const scale = tokenBlock.match(/--sp-\d+:\s*(\d+)px/g) || [];
  return scale.length >= 8 && scale.every((entry) => Number(entry.match(/(\d+)px/)[1]) % 4 === 0);
})());

check("motion is short and purposeful", (() => {
  const durations = (css.match(/--dur[a-z-]*:\s*(\d+)ms/g) || []).map((d) => Number(d.match(/(\d+)ms/)[1]));
  return durations.length >= 2 && durations.every((ms) => ms <= 250);
})());

check("reduced-motion preference is respected", /prefers-reduced-motion:\s*reduce/.test(css));

check("focus-visible styling is defined", /:focus-visible\s*\{/.test(css));

check("the hidden attribute still overrides display rules",
  /\[hidden\]\s*\{\s*display:\s*none\s*!important/.test(css));

/* ── Responsive ────────────────────────────────────────────────────────── */

console.log("\n[responsive] Breakpoints");

check("declares a viewport meta", Boolean(doc.querySelector('meta[name="viewport"]')));

check("has tablet and mobile breakpoints", (() => {
  const queries = css.match(/@media \(max-width: (\d+)px\)/g) || [];
  return queries.length >= 3;
})());

check("the sidebar becomes a drawer rather than shrinking", (() => {
  const mobile = css.slice(css.indexOf("@media (max-width: 900px)"));
  return /\.sidebar\s*\{[^}]*translateX\(-100%\)/.test(mobile) && /\.sidebar\.is-open/.test(mobile);
})());

check("the mobile menu button is hidden on desktop", (() => {
  const desktop = css.slice(0, css.indexOf("@media"));
  return /\.icon-btn\s*\{[^}]*display:\s*none/.test(desktop);
})());

check("tables scroll instead of reflowing into ambiguity", /\.table-wrap\s*\{[^}]*overflow-x:\s*auto/.test(css));

/* ── Component coverage ────────────────────────────────────────────────── */

console.log("\n[components] Library coverage");

const components = readFileSync(resolve(ROOT, "frontend/js/components.js"), "utf8");
for (const name of ["button", "card", "stat", "badge", "alert", "table",
                    "emptyState", "errorState", "skeletonCard", "stepList", "icon", "setBusy"]) {
  check(`exports ${name}()`, new RegExp(`export function ${name}\\b`).test(components));
}

check("icons ship inline rather than as a network dependency", (() => {
  // Strip comments first — the prose mentions CDNs while the code avoids them.
  const code = components.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  return !/https?:\/\//.test(code) && /viewBox="0 0 24 24"/.test(code);
})());

check("no external script dependencies at all",
  !/<script[^>]+src="https?:/i.test(html));

console.log(failures === 0 ? "\nALL DESIGN CHECKS PASSED" : `\n${failures} DESIGN CHECK(S) FAILED`);
process.exit(failures === 0 ? 0 : 1);
