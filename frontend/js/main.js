/* Entry point: icon hydration, hash router, mobile drawer, health indicator. */

import { api } from "./api.js";
import { $, el } from "./ui.js";
import { icon } from "./components.js";
import { mountAuth } from "./auth-ui.js";
import { mountAnalyze } from "./views/analyze.js";
import { mountCompare } from "./views/compare.js";
import { mountChat } from "./views/chat.js";
import { mountJobMatch } from "./views/jobmatch.js";

const VIEWS = ["analyze", "compare", "chat", "jobmatch"];

const TITLES = {
  analyze: "Analyze",
  compare: "Compare",
  chat: "Repo chat",
  jobmatch: "Job match",
};

/* Static markup declares icons as `<span data-icon="name">`; this swaps in the
   real SVG once, so the HTML stays readable and the icon set stays in one file. */
function hydrateIcons(scope = document) {
  for (const slot of scope.querySelectorAll("[data-icon]")) {
    slot.replaceChildren(icon(slot.dataset.icon, { size: slot.dataset.iconSize ? Number(slot.dataset.iconSize) : 17 }));
    delete slot.dataset.icon;
  }
}

/* ── Mobile drawer ─────────────────────────────────────────────────────── */

let scrimNode = null;

function closeDrawer() {
  $("#sidebar").classList.remove("is-open");
  $("#btn-menu").setAttribute("aria-expanded", "false");
  scrimNode?.remove();
  scrimNode = null;
}

function openDrawer() {
  $("#sidebar").classList.add("is-open");
  $("#btn-menu").setAttribute("aria-expanded", "true");
  scrimNode = el("div", { class: "sidebar-scrim", onClick: closeDrawer });
  document.body.append(scrimNode);
}

function toggleDrawer() {
  if ($("#sidebar").classList.contains("is-open")) closeDrawer();
  else openDrawer();
}

/* ── Routing ───────────────────────────────────────────────────────────── */

function show(view) {
  const active = VIEWS.includes(view) ? view : "analyze";

  for (const name of VIEWS) $(`#view-${name}`).hidden = name !== active;

  for (const item of document.querySelectorAll(".nav__item[data-view]")) {
    const isActive = item.dataset.view === active;
    if (isActive) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  }

  $("#topbar-title").textContent = TITLES[active];
  document.title = `${document.querySelector(`.nav__item[data-view="${active}"]`)?.dataset.title || TITLES[active]} · Bench`;

  closeDrawer();
  // Scroll position is per-page; landing mid-page after switching views is jarring.
  if (typeof window.scrollTo === "function") {
    try {
      window.scrollTo({ top: 0, behavior: "instant" });
    } catch {
      /* Non-browser environments (jsdom) don't implement scrollTo. */
    }
  }
}

function route() {
  show((location.hash || "#/analyze").replace(/^#\//, ""));
}

/* ── Health ────────────────────────────────────────────────────────────── */

async function checkHealth() {
  const indicator = $("#conn-state");
  try {
    await api.health();
    indicator.className = "status-dot is-up";
    indicator.replaceChildren(el("i", {}), document.createTextNode("API connected"));
  } catch {
    indicator.className = "status-dot is-down";
    indicator.replaceChildren(el("i", {}), document.createTextNode("API unreachable"));
    indicator.title = "The backend isn't responding. Is the server running?";
  }
}

/* ── Boot ──────────────────────────────────────────────────────────────── */

hydrateIcons();
mountAuth();
mountAnalyze();
mountCompare();
mountChat();
mountJobMatch();

$("#btn-menu").addEventListener("click", toggleDrawer);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && scrimNode) closeDrawer();
});

window.addEventListener("hashchange", route);
route();
checkHealth();

export { hydrateIcons };
