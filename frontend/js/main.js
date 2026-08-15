/* Entry point: hash router + health indicator. */

import { api } from "./api.js";
import { $ } from "./ui.js";
import { mountAuth } from "./auth-ui.js";
import { mountAnalyze } from "./views/analyze.js";
import { mountCompare } from "./views/compare.js";
import { mountChat } from "./views/chat.js";

const VIEWS = ["analyze", "compare", "chat"];

function show(view) {
  const active = VIEWS.includes(view) ? view : "analyze";
  for (const name of VIEWS) {
    $(`#view-${name}`).hidden = name !== active;
  }
  for (const item of document.querySelectorAll(".rail__item")) {
    item.classList.toggle("is-active", item.dataset.view === active);
  }
  document.title = {
    analyze: "Analyze a developer · Bench",
    compare: "Compare developers · Bench",
    chat: "Chat with a repository · Bench",
  }[active];
}

function route() {
  show((location.hash || "#/analyze").replace(/^#\//, ""));
}

async function checkHealth() {
  const indicator = $("#conn-state");
  try {
    await api.health();
    indicator.className = "conn is-up";
    indicator.innerHTML = "<i></i>API connected";
  } catch {
    indicator.className = "conn is-down";
    indicator.innerHTML = "<i></i>API unreachable";
  }
}

mountAuth();
mountAnalyze();
mountCompare();
mountChat();

window.addEventListener("hashchange", route);
route();
checkHealth();
