/* View 03 — chat with a repository.
   The signature of this interface lives here: every assistant answer carries
   numbered citations, and each one expands into the actual retrieved lines with
   real line numbers. Grounding you can check beats grounding you're promised. */

import { api, streamAnswer } from "../api.js";
import {
  $, busyButton, clear, el, empty, escapeHtml, fmtBytes, fmtNum,
  linkCitations, panel, renderMarkdown, toast,
} from "../ui.js";
import { requireAuth } from "../auth-ui.js";

const state = {
  repo: null,        // IndexStatusOut
  sessionId: null,
  poller: null,
  streaming: true,
};

/* ── Repo panel ────────────────────────────────────────────────────────── */

function statusPill(status) {
  const label = { ready: "ready", indexing: "indexing", pending: "queued", failed: "failed" }[status] || status;
  return el("span", { class: `status status--${status}` }, el("i", {}), label);
}

function repoPanel() {
  const repo = state.repo;
  const body = el("div");

  body.append(
    el("div", { style: "display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px" },
      statusPill(repo.status),
      el("a", { class: "repo-card__name", href: `https://github.com/${repo.full_name}`, target: "_blank",
        rel: "noopener", text: repo.full_name })));

  if (repo.description) body.append(el("p", { class: "repo-card__desc", text: repo.description }));

  if (repo.status === "failed") {
    body.append(
      el("p", { class: "prose", text: repo.error || "Indexing failed." }),
      el("button", { class: "btn btn--quiet", style: "margin-top:10px",
        onClick: () => openRepo(repo.full_name, { force: true }) }, "Try again"));
    return panel("REP", "Repository", null, body);
  }

  if (repo.status !== "ready") {
    body.append(
      el("p", { class: "field__note", text: "Downloading the repository, chunking the source and embedding it. Large repos take a minute." }),
      el("div", { class: "progress" }, el("i", {})));
    return panel("REP", "Repository", null, body);
  }

  body.append(
    el("dl", { class: "kv" },
      el("dt", { text: "Branch" }), el("dd", { text: repo.ref || repo.default_branch || "—" }),
      el("dt", { text: "Indexed" }), el("dd", { text: `${fmtNum(repo.file_count)} files · ${fmtNum(repo.chunk_count)} chunks` }),
      el("dt", { text: "Source" }), el("dd", { text: fmtBytes(repo.total_bytes) }),
      el("dt", { text: "Embedder" }), el("dd", { text: repo.embedding_model || "—" }),
      el("dt", { text: "Stars" }), el("dd", { text: fmtNum(repo.stars) })));

  if (repo.topics?.length) {
    body.append(el("div", { class: "tags", style: "margin-top:12px" },
      ...repo.topics.slice(0, 8).map((topic) => el("span", { class: "tag", text: topic }))));
  }

  if (repo.file_tree?.length) {
    const files = repo.file_tree.filter((line) => !line.endsWith("files)"));
    body.append(
      el("div", { class: "field__label", style: "margin-top:16px", text: "Indexed files" }),
      el("pre", { class: "tree", text: files.slice(0, 200).join("\n") }));
  }

  body.append(el("button", {
    class: "btn btn--quiet", style: "margin-top:14px",
    onClick: () => openRepo(repo.full_name, { force: true }),
  }, "Re-index"));

  return panel("REP", "Repository", null, body);
}

/* ── Overview ──────────────────────────────────────────────────────────── */

async function loadOverview(host) {
  const [owner, name] = state.repo.full_name.split("/");
  clear(host).append(el("p", { class: "field__note" },
    el("span", { class: "spinner spinner--ink" }), "Reading the codebase…"));

  try {
    const overview = await api.overview(owner, name);
    clear(host);

    if (overview.what_it_does) host.append(el("p", { class: "prose", text: overview.what_it_does }));

    if (overview.how_it_works?.length) {
      host.append(
        el("div", { class: "field__label", style: "margin-top:14px", text: "How it works" }),
        el("ol", { class: "list" },
          ...overview.how_it_works.map((step, index) =>
            el("li", {},
              el("span", { class: "list__ord", text: String(index + 1).padStart(2, "0") }),
              el("span", { text: step })))));
    }

    if (overview.architecture?.length) {
      host.append(
        el("div", { class: "field__label", style: "margin-top:14px", text: "Components" }),
        el("dl", { class: "kv" },
          ...overview.architecture.flatMap((component) => [
            el("dt", { text: component.component }),
            el("dd", {}, component.responsibility,
              component.path ? el("span", { class: "repo-lang", text: ` · ${component.path}` }) : null),
          ])));
    }

    if (overview.tech_stack?.length) {
      host.append(
        el("div", { class: "field__label", style: "margin-top:14px", text: "Stack" }),
        el("div", { class: "tags" },
          ...overview.tech_stack.map((item) => el("span", { class: "tag tag--signal", text: item }))));
    }

    if (overview.entry_points?.length) {
      host.append(
        el("div", { class: "field__label", style: "margin-top:14px", text: "Start reading here" }),
        el("div", { class: "tags" },
          ...overview.entry_points.map((path) => el("span", { class: "tag", text: path }))));
    }

    if (overview.suggested_questions?.length) {
      const suggested = $("#suggested");
      if (suggested) {
        clear(suggested).append(
          ...overview.suggested_questions.map((question) =>
            el("button", { text: question, onClick: () => ask(question) })));
      }
    }
  } catch (error) {
    clear(host).append(
      el("p", { class: "prose", text: error.message }),
      el("button", { class: "btn btn--quiet", style: "margin-top:10px",
        onClick: () => loadOverview(host) }, "Retry"));
  }
}

/* ── Thread rendering ──────────────────────────────────────────────────── */

function citationSources(citations) {
  if (!citations?.length) return null;

  const wrap = el("div", { class: "sources" },
    el("div", { class: "sources__head", text: `Sources · ${citations.length} retrieved` }));

  for (const citation of citations) {
    const lines = (citation.content || "").split("\n");
    const codeRows = lines.map((line, index) =>
      `<tr><td class="ln">${citation.start_line + index}</td><td class="src">${escapeHtml(line) || "&nbsp;"}</td></tr>`).join("");

    const source = el("div", { class: "source", "data-cite": citation.n });
    const code = el("div", { class: "source__code",
      html: `<table>${codeRows}</table>` });

    source.append(
      el("button", { class: "source__bar", onClick: () => source.classList.toggle("is-open") },
        el("span", { class: "source__n", text: `[${citation.n}]` }),
        el("span", { class: "source__path", text: citation.path }),
        citation.symbol ? el("span", { class: "repo-lang", text: citation.symbol }) : null,
        el("span", { class: "source__lines", text: `${citation.start_line}–${citation.end_line}` })),
      code);
    wrap.append(source);
  }
  return wrap;
}

function turn(role, content, { citations, rewrite, question } = {}) {
  const body = el("div", { class: "turn__body" });

  if (role === "user") {
    body.textContent = content;
  } else {
    // Only worth showing when the follow-up actually needed resolving —
    // echoing back an unchanged question is noise.
    if (rewrite && question && rewrite.trim() !== question.trim()) {
      body.append(el("div", { class: "rewrite" }, el("b", {}, "Searched for: "), rewrite));
    }
    const prose = el("div", { class: "prose" });
    prose.innerHTML = linkCitations(renderMarkdown(content), citations?.length || 0);
    body.append(prose);

    const sources = citationSources(citations);
    if (sources) body.append(sources);

    // Clicking [n] in the prose opens that source.
    prose.addEventListener("click", (event) => {
      const chip = event.target.closest(".cite");
      if (!chip) return;
      const target = body.querySelector(`.source[data-cite="${chip.dataset.cite}"]`);
      if (!target) return;
      target.classList.add("is-open");
      target.scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
  }

  return el("div", { class: `turn turn--${role === "user" ? "user" : "bot"}` },
    el("div", { class: "turn__who", text: role === "user" ? "you" : "repo" }),
    body);
}

function threadHost() {
  return $("#thread");
}

function scrollToEnd() {
  const thread = threadHost();
  if (thread) thread.lastElementChild?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

/* ── Asking ────────────────────────────────────────────────────────────── */

async function ask(question) {
  if (!question?.trim()) return;
  if (!requireAuth("Sign in to ask questions.", () => ask(question))) return;
  if (state.repo?.status !== "ready") {
    toast("The repository is still indexing.", "bad");
    return;
  }

  const thread = threadHost();
  const box = $("#composer-input");
  const send = $("#btn-send");
  if (box) box.value = "";

  thread.querySelector(".empty")?.remove();
  thread.append(turn("user", question));
  scrollToEnd();

  // Open a session lazily, so a user can land on the view and just start typing.
  if (!state.sessionId) {
    try {
      const session = await api.createSession(state.repo.full_name);
      state.sessionId = session.id;
      await refreshSessions();
    } catch (error) {
      thread.append(turn("bot", `Couldn't open a chat session: ${error.message}`));
      return;
    }
  }

  const pending = el("div", { class: "turn turn--bot" },
    el("div", { class: "turn__who", text: "repo" }),
    el("div", { class: "turn__body" },
      el("div", { class: "prose" },
        el("span", { class: "spinner spinner--ink" }),
        el("span", { class: "repo-lang", text: "searching the codebase…" }))));
  thread.append(pending);
  scrollToEnd();
  busyButton(send, true, "Asking…");

  if (state.streaming) {
    let citations = [];
    let answer = "";
    let started = false;

    await streamAnswer(state.sessionId, question, {
      onCitations: (data) => {
        citations = data;
        const body = pending.querySelector(".turn__body");
        clear(body).append(el("div", { class: "prose" }, el("span", { class: "caret" })));
        const sources = citationSources(citations);
        if (sources) body.append(sources);
      },
      onToken: (token) => {
        started = true;
        answer += token;
        const prose = pending.querySelector(".prose");
        if (prose) prose.innerHTML = `${renderMarkdown(answer)}<span class="caret"></span>`;
        scrollToEnd();
      },
      onDone: () => {
        if (!started && !answer) return;
        pending.replaceWith(turn("bot", answer, { citations }));
        busyButton(send, false);
        scrollToEnd();
      },
      onError: (error) => {
        pending.replaceWith(turn("bot", `That didn't work: ${error.message}`));
        busyButton(send, false);
        toast(error.message, "bad");
      },
    });
    busyButton(send, false);
    return;
  }

  try {
    const result = await api.askInSession(state.sessionId, question);
    pending.replaceWith(turn("bot", result.answer, {
      citations: result.citations,
      rewrite: result.standalone_question,
      question,
    }));
  } catch (error) {
    pending.replaceWith(turn("bot", `That didn't work: ${error.message}`));
    toast(error.message, "bad");
  } finally {
    busyButton(send, false);
    scrollToEnd();
  }
}

/* ── Sessions ──────────────────────────────────────────────────────────── */

async function refreshSessions() {
  const host = $("#sessions");
  if (!host) return;

  let sessions = [];
  try {
    sessions = await api.listSessions();
  } catch {
    clear(host).append(el("p", { class: "field__note", text: "Sign in to keep a history of your conversations." }));
    return;
  }

  const mine = sessions.filter((session) => session.repository === state.repo?.full_name);
  clear(host);

  if (!mine.length) {
    host.append(el("p", { class: "field__note", text: "No conversations on this repo yet." }));
    return;
  }

  for (const session of mine) {
    host.append(el("div", { style: "display:flex;align-items:center;gap:4px" },
      el("button", {
        class: `session${session.id === state.sessionId ? " is-active" : ""}`,
        onClick: () => loadSession(session.id),
      },
        el("span", { style: "overflow:hidden;text-overflow:ellipsis;white-space:nowrap",
          text: session.title || "Untitled" }),
        el("span", { class: "session__meta", text: `${session.message_count}` })),
      el("button", {
        class: "chip", title: "Delete conversation",
        onClick: async () => {
          await api.deleteSession(session.id).catch(() => {});
          if (state.sessionId === session.id) {
            state.sessionId = null;
            clear(threadHost()).append(emptyThread());
          }
          refreshSessions();
        },
      }, "✕")));
  }
}

async function loadSession(sessionId) {
  state.sessionId = sessionId;
  const thread = clear(threadHost());
  thread.append(el("p", { class: "field__note" }, el("span", { class: "spinner spinner--ink" }), "Loading…"));

  try {
    const messages = await api.transcript(sessionId);
    clear(thread);
    if (!messages.length) thread.append(emptyThread());
    for (const message of messages) {
      thread.append(turn(message.role, message.content, { citations: message.citations }));
    }
    await refreshSessions();
    scrollToEnd();
  } catch (error) {
    clear(thread).append(el("p", { class: "prose", text: error.message }));
  }
}

function emptyThread() {
  return empty("Ask the first question",
    "Try “what does this project do?”, then follow up with “how does that part actually work?”");
}

/* ── Opening a repo ────────────────────────────────────────────────────── */

function stopPolling() {
  if (state.poller) {
    clearInterval(state.poller);
    state.poller = null;
  }
}

async function pollUntilReady(owner, name) {
  stopPolling();
  state.poller = setInterval(async () => {
    try {
      const status = await api.indexStatus(owner, name);
      state.repo = status;
      renderChat({ keepThread: true });
      if (status.status === "ready") {
        stopPolling();
        toast(`${status.full_name} is ready — ask it anything.`, "good");
        const overviewHost = $("#overview");
        if (overviewHost) loadOverview(overviewHost);
        refreshSessions();
      } else if (status.status === "failed") {
        stopPolling();
        toast(status.error || "Indexing failed.", "bad");
      }
    } catch {
      stopPolling();
    }
  }, 2500);
}

export async function openRepo(repoUrl, { force = false } = {}) {
  if (!requireAuth("Sign in to index a repository.", () => openRepo(repoUrl, { force }))) return;

  const button = $("#btn-index");
  $("#in-repo").value = repoUrl;
  busyButton(button, true, "Opening…");
  stopPolling();
  state.sessionId = null;

  try {
    const status = await api.indexRepo(repoUrl, { force });
    state.repo = status;
    renderChat();

    const [owner, name] = status.full_name.split("/");
    if (status.status === "ready") {
      loadOverview($("#overview"));
      refreshSessions();
    } else {
      pollUntilReady(owner, name);
    }
  } catch (error) {
    clear($("#chat-out")).append(
      panel("ERR", "Couldn't open that repository", null,
        el("p", { class: "prose", text: error.message }),
        el("p", { class: "field__note", text: "Public repositories only. Check the URL, or add a GITHUB_TOKEN to your .env if you're rate limited." })));
    toast(error.message, "bad");
  } finally {
    busyButton(button, false);
  }
}

/* ── Layout ────────────────────────────────────────────────────────────── */

function renderChat({ keepThread = false } = {}) {
  const out = $("#chat-out");
  const existingThread = keepThread ? $("#thread") : null;
  const preserved = existingThread ? [...existingThread.childNodes] : null;

  clear(out);

  const left = el("div");
  left.append(repoPanel());
  left.append(panel("SES", "Conversations", null, el("div", { class: "sessions", id: "sessions" })));

  const right = el("div");
  right.append(panel("OVR", "What this repo is", "AI brief", el("div", { id: "overview" },
    el("p", { class: "field__note", text: state.repo.status === "ready" ? "Loading…" : "Available once indexing finishes." }))));

  const thread = el("div", { class: "thread", id: "thread" });
  if (preserved?.length) thread.append(...preserved);
  else thread.append(emptyThread());

  const composer = el("div", { class: "composer" },
    el("textarea", {
      id: "composer-input",
      placeholder: "Ask what the code does, how a feature works, where something is handled…",
      onKeydown: (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          ask(event.target.value);
        }
      },
    }),
    el("div", { class: "composer__side" },
      el("button", { class: "btn btn--solid", id: "btn-send",
        onClick: () => ask($("#composer-input").value) }, "Ask"),
      el("label", { class: "composer__hint", style: "display:flex;gap:5px;align-items:center;cursor:pointer" },
        el("input", { type: "checkbox", checked: state.streaming ? true : null,
          onChange: (event) => { state.streaming = event.target.checked; } }),
        "stream")));

  right.append(panel("ASK", "Conversation",
    state.repo.status === "ready" ? "follow-up questions keep their context" : "waiting for the index",
    el("div", { class: "field__label", text: "Suggested questions" }),
    el("div", { class: "suggested", id: "suggested" },
      ...defaultQuestions().map((question) => el("button", { text: question, onClick: () => ask(question) }))),
    el("div", { style: "height:18px" }),
    thread,
    composer));

  out.append(el("div", { class: "chat-layout" }, left, right));
}

function defaultQuestions() {
  return [
    "What does this project do, and who is it for?",
    "Walk me through what happens on a typical request, end to end.",
    "How is the code organised — what are the main components?",
    "Where is configuration read, and what can be tuned?",
  ];
}

export function mountChat() {
  $("#form-index").addEventListener("submit", (event) => {
    event.preventDefault();
    const url = $("#in-repo").value.trim();
    if (url) openRepo(url);
  });

  for (const chip of document.querySelectorAll("[data-repo]")) {
    chip.addEventListener("click", () => openRepo(chip.dataset.repo));
  }

  $("#chat-out").append(empty(
    "No repository open",
    "Paste a GitHub repository URL above. It gets downloaded, chunked and embedded, then you can ask it questions."));
}
