/* Regression guard for the "sign-in dialog can't be dismissed" bug.
 *
 * jsdom's getComputedStyle does not model author-vs-UA precedence the way a
 * browser does — it reported display:none for an element that a real browser
 * renders as display:flex, which is exactly how the bug slipped through. So
 * this test does the cascade itself: for every element that JS toggles via the
 * `hidden` attribute, check whether any author rule sets `display` on it, and
 * whether that rule is neutralised.
 *
 * In a browser, author `.scrim { display: flex }` beats UA `[hidden] { display:
 * none }`. Only an author-level `[hidden] { display: none !important }` wins.
 */

import { JSDOM } from "jsdom";
import { readFileSync } from "node:fs";

import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

// Resolve paths against this file, so the suite runs from any working directory.
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");


const css = readFileSync(resolve(ROOT, "frontend/css/app.css"), "utf8");
const html = readFileSync(resolve(ROOT, "frontend/index.html"), "utf8");

let failures = 0;
const check = (label, ok, extra = "") => {
  console.log(`  ${ok ? "✓" : "✗"} ${label}${ok ? "" : ` ${extra}`}`);
  if (!ok) failures += 1;
};

/* Strip comments and at-rule bodies, then collect selector -> declarations. */
const stripped = css.replace(/\/\*[\s\S]*?\*\//g, "");
const rules = [];
const ruleRe = /([^{}]+)\{([^{}]*)\}/g;
let match;
while ((match = ruleRe.exec(stripped)) !== null) {
  const selector = match[1].trim();
  if (!selector || selector.startsWith("@") || selector.startsWith(":root")) continue;
  rules.push({ selector, body: match[2] });
}

const displayRules = rules.filter((rule) => /(^|[;{\s])display\s*:/.test(rule.body));

console.log("[cascade] hidden-attribute override");

const override = displayRules.find(
  (rule) => rule.selector === "[hidden]" && /display\s*:\s*none\s*!important/.test(rule.body),
);
check("stylesheet forces [hidden] to win over author display rules", Boolean(override));

/* Which elements does the app actually toggle with `hidden`? */
const dom = new JSDOM(html);
const doc = dom.window.document;
const toggled = ["#scrim", "#view-analyze", "#view-compare", "#view-chat", "#auth-err"];

for (const selector of toggled) {
  const node = doc.querySelector(selector);
  if (!node) {
    check(`${selector} exists in the markup`, false);
    continue;
  }

  // Author rules that set display and match this element.
  const conflicting = displayRules.filter((rule) => {
    if (rule.selector === "[hidden]") return false;
    return rule.selector.split(",").some((part) => {
      const clean = part.trim().replace(/::?[a-z-]+(\([^)]*\))?/g, "");
      if (!clean || clean.includes(" ") || clean.includes(">")) return false;
      try {
        return node.matches(clean) && !/display\s*:\s*none/.test(rule.body);
      } catch {
        return false;
      }
    });
  });

  const safe = conflicting.length === 0 || Boolean(override);
  check(
    `${selector} is genuinely hidden when hidden is set`,
    safe,
    conflicting.length ? `— conflicts with: ${conflicting.map((r) => r.selector).join(", ")}` : "",
  );
}

/* The specific historical failure, spelled out. */
const scrimRule = displayRules.find((rule) => rule.selector === ".scrim");
check(
  ".scrim still uses display:flex when visible (layout intact)",
  Boolean(scrimRule) && /display\s*:\s*flex/.test(scrimRule.body),
);
check("...and is still overridden when hidden", Boolean(override));

console.log(failures === 0 ? "\nCASCADE CHECKS PASSED" : `\n${failures} CASCADE CHECK(S) FAILED`);
process.exit(failures === 0 ? 0 : 1);
