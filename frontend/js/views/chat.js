/* View 03 — chat with a repository.
   The signature of this interface lives here: every assistant answer carries
   numbered citations, and each one expands into the actual retrieved lines with
   real line numbers. Grounding you can check beats grounding you're promised. */

import { api, streamAnswer } from "../api.js";
import { $, clear, el, escapeHtml, fmtBytes, fmtNum, linkCitations, renderMarkdown, toast } from "../ui.js";
import {
  alert, badge, button, card, emptyState, errorState, icon,
  progressBar, setBusy, skeletonCard, stat, statGrid,
} from "../components.js";
import { requireAuth } from "../auth-ui.js";

const state = {
  repo: null,        // IndexStatusOut
  sessionId: null,
  poller: null,
  streaming: true,
};

/* ── Repo panel ────────────────────────────────────────────────────────── */

function statusPill(status) {
  const meta = {
    ready: ["Ready", "success"],
    indexing: ["Indexing", "warning"],
    pending: ["Queued", "warning"],
    failed: ["Failed", "danger"],
  }[status] || [status, "neutral"];
  return badge(meta[0], meta[1], { dot: true });
}

function repoPanel() {
  const repo = state.repo;
  const body = el("div", { class: "stack", style: "gap:16px" });

  body.append(el("div", { class: "row", style: "gap:10px" },
    statusPill(repo.status),
    el("a", {
      class: "repo-title",
      href: `https://github.com/${repo.full_name}`,
      target: "_blank", rel: "noopener",
      text: repo.full_name,
    })));

  if (repo.description) body.append(el("p", { class: "prose", text: repo.description }));

  if (repo.status === "failed") {
    body.append(
      alert(repo.error || "Indexing failed.", { variant: "danger", title: "Could not index this repository" }),
      el("div", {}, button("Try again", {
        variant: "secondary", iconName: "refresh-cw",
        onClick: () => openRepo(repo.full_name, { force: true }),
      })));
    return card({ title: "Repository", body });
  }

  if (repo.status !== "ready") {
    body.append(
      el("p", { class: "hint", text: "Downloading the repository, chunking the source and embedding it. Large repositories take a minute." }),
      progressBar());
    return card({ title: "Repository", body });
  }

  body.append(el("dl", { class: "kv" },
    el("dt", { text: "Branch" }), el("dd", { text: repo.ref || repo.default_branch || "—" }),
    el("dt", { text: "Indexed" }), el("dd", { text: `${fmtNum(repo.file_count)} files · ${fmtNum(repo.chunk_count)} chunks` }),
    el("dt", { text: "Source size" }), el("dd", { text: fmtBytes(repo.total_bytes) }),
    el("dt", { text: "Embedder" }), el("dd", { text: repo.embedding_model || "—" }),
    el("dt", { text: "Stars" }), el("dd", { text: fmtNum(repo.stars) })));

  // If the chunk budget truncated the repo, say so — an answer that can't cite
  // a file because it was never indexed must not look like a confident "no".
  if (repo.coverage?.budget_reached) {
    const notIndexed = repo.coverage.files_not_indexed?.length || 0;
    const partial = repo.coverage.files_partially_indexed?.length || 0;
    body.append(el("div", { class: "coverage-warn" }, alert(
      el("div", {},
        el("div", { text:
          `The chunk budget (${repo.coverage.chunk_budget}) was reached. ${notIndexed} file(s) were not indexed and ${partial} only partially. ` +
          "Questions about those files can't be answered from the index." }),
        el("div", { class: "hint", style: "margin-top:6px", text: "Raise INGEST_MAX_CHUNKS and re-index for full coverage." })),
      { variant: "warning", title: "Partial index" })));
  }

  if (repo.topics?.length) {
    body.append(el("div", { class: "tags" },
      ...repo.topics.slice(0, 8).map((topic) => badge(topic, "neutral"))));
  }

  if (repo.file_tree?.length) {
    const files = repo.file_tree.filter((line) => !line.endsWith("files)"));
    body.append(el("div", {},
      el("div", { class: "evidence__head" }, icon("code", { size: 13 }), "Indexed files"),
      el("pre", { class: "tree", text: files.slice(0, 200).join("\n") })));
  }

  body.append(el("div", {}, button("Re-index", {
    variant: "secondary", size: "sm", iconName: "refresh-cw",
    onClick: () => openRepo(repo.full_name, { force: true }),
  })));

  return card({ title: "Repository", body });
}

/* ── Overview ──────────────────────────────────────────────────────────── */

async function loadOverview(host) {
  const [owner, name] = state.repo.full_name.split("/");
  clear(host).append(el("div", { class: "stack", style: "gap:10px" },
    el("div", { class: "row", style: "gap:8px" },
      el("span", { class: "spinner" }),
      el("span", { class: "hint", text: "Reading the codebase…" })),
    el("div", { class: "skeleton skeleton--text", style: "width:92%" }),
    el("div", { class: "skeleton skeleton--text", style: "width:78%" }),
    el("div", { class: "skeleton skeleton--text", style: "width:85%" })));

  try {
    const overview = await api.overview(owner, name);
    clear(host);

    if (overview.what_it_does) host.append(el("p", { class: "prose", text: overview.what_it_does }));

    if (overview.how_it_works?.length) {
      host.append(
        el("div", { class: "evidence__head", style: "margin-top:16px" }, icon("activity", { size: 13 }), "How it works"),
        el("ol", { class: "list-plain" },
          ...overview.how_it_works.map((step, index) =>
            el("li", {},
              el("span", { class: "list-plain__index", text: String(index + 1) }),
              el("span", { text: step })))));
    }

    if (overview.architecture?.length) {
      host.append(
        el("div", { class: "evidence__head", style: "margin-top:16px" }, icon("folder", { size: 13 }), "Components"),
        el("ul", { class: "list-plain" },
          ...overview.architecture.map((component) =>
            el("li", { style: "display:block" },
              el("div", { class: "cell-primary", text: component.component }),
              el("div", { class: "hint" }, component.responsibility,
                component.path ? el("code", { style: "margin-left:6px", text: component.path }) : null)))));
    }

    if (overview.tech_stack?.length) {
      host.append(
        el("div", { class: "evidence__head", style: "margin-top:16px" }, icon("code", { size: 13 }), "Stack"),
        el("div", { class: "tags" }, ...overview.tech_stack.map((item) => badge(item, "accent"))));
    }

    if (overview.entry_points?.length) {
      host.append(
        el("div", { class: "evidence__head", style: "margin-top:16px" }, icon("file-text", { size: 13 }), "Start reading here"),
        el("div", { class: "tags" }, ...overview.entry_points.map((path) => badge(path, "neutral"))));
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
      alert(error.message, { variant: "danger", title: "Overview unavailable" }),
      el("div", { style: "margin-top:12px" },
        button("Retry", { variant: "secondary", size: "sm", iconName: "refresh-cw", onClick: () => loadOverview(host) })));
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

    const bar = el("button", {
      class: "source__bar",
      type: "button",
      "aria-expanded": "false",
      title: `${citation.path} lines ${citation.start_line}–${citation.end_line}`,
      onClick: () => {
        const open = source.classList.toggle("is-open");
        bar.setAttribute("aria-expanded", String(open));
      },
    },
      el("span", { class: "source__chevron" }, icon("chevron-right", { size: 14 })),
      el("span", { class: "source__n", text: `[${citation.n}]` }),
      el("span", { class: "source__path", text: citation.path }),
      citation.symbol ? el("span", { class: "cell-muted", text: citation.symbol }) : null,
      el("span", { class: "source__lines", text: `${citation.start_line}–${citation.end_line}` }));

    source.append(bar, code);
    wrap.append(source);
  }
  return wrap;
}

function turn(role, content, { citations, rewrite, question } = {}) {
  const body = el("div", { class: "turn__body" });

  if (role === "user") {
    body.append(el("div", { class: "prose", text: content }));
  } else {
    // Only worth showing when the follow-up actually needed resolving —
    // echoing back an unchanged question is noise.
    if (rewrite && question && rewrite.trim() !== question.trim()) {
      body.append(el("div", { class: "rewrite" },
        icon("search", { size: 13 }), el("b", {}, "Searched for: "), rewrite));
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

  const isUser = role === "user";
  const avatar = el("div", { class: "turn__avatar" });
  if (isUser) avatar.textContent = "You".slice(0, 1);
  else avatar.append(icon("bot", { size: 15 }));

  return el("div", { class: `turn turn--${isUser ? "user" : "bot"}` },
    avatar,
    el("div", { class: "turn__body" },
      el("div", { class: "turn__who", text: isUser ? "You" : "Repository" }),
      body));
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
    el("div", { class: "turn__avatar" }, icon("bot", { size: 15 })),
    el("div", { class: "turn__body" },
      el("div", { class: "turn__who", text: "Repository" }),
      el("div", { class: "prose", style: "display:flex;align-items:center;gap:8px" },
        el("span", { class: "spinner" }),
        el("span", { class: "hint", text: "Searching the codebase…" }))));
  thread.append(pending);
  scrollToEnd();
  setBusy(send, true, "Asking…");

  if (state.streaming) {
    let citations = [];
    let answer = "";
    let started = false;

    await streamAnswer(state.sessionId, question, {
      onCitations: (data) => {
        citations = data;
        const body = pending.querySelector(".turn__body");
        clear(body).append(
          el("div", { class: "turn__who", text: "Repository" }),
          el("div", { class: "prose" }, el("span", { class: "caret" })));
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
        setBusy(send, false);
        scrollToEnd();
      },
      onError: (error) => {
        pending.replaceWith(turn("bot", `That didn't work: ${error.message}`));
        setBusy(send, false);
        toast(error.message, "bad");
      },
    });
    setBusy(send, false);
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
    setBusy(send, false);
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
    clear(host).append(el("p", { class: "hint", text: "Sign in to keep a history of your conversations." }));
    return;
  }

  const mine = sessions.filter((session) => session.repository === state.repo?.full_name);
  clear(host);

  if (!mine.length) {
    host.append(el("p", { class: "hint", text: "No conversations on this repository yet." }));
    return;
  }

  for (const session of mine) {
    const remove = button("", {
      variant: "ghost", size: "icon",
      iconName: "trash",
      title: `Delete "${session.title || "Untitled"}"`,
      onClick: async () => {
        // Destructive and irreversible, so confirm first.
        if (!window.confirm(`Delete this conversation? Its ${session.message_count} message(s) will be lost.`)) return;
        try {
          await api.deleteSession(session.id);
          toast("Conversation deleted", "info");
        } catch (error) {
          toast(error.message, "bad");
          return;
        }
        if (state.sessionId === session.id) {
          state.sessionId = null;
          clear(threadHost()).append(emptyThread());
        }
        refreshSessions();
      },
    });
    remove.classList.add("btn--icon");

    host.append(el("div", { class: "session-row" },
      el("button", {
        class: `session${session.id === state.sessionId ? " is-active" : ""}`,
        type: "button",
        "aria-current": session.id === state.sessionId ? "true" : null,
        onClick: () => loadSession(session.id),
      },
        el("span", { class: "session__label", text: session.title || "Untitled" }),
        el("span", { class: "session__meta", text: String(session.message_count) })),
      remove));
  }
}

async function loadSession(sessionId) {
  state.sessionId = sessionId;
  const thread = clear(threadHost());
  thread.append(el("div", { class: "row", style: "gap:8px" },
    el("span", { class: "spinner" }), el("span", { class: "hint", text: "Loading conversation…" })));

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
    clear(thread).append(alert(error.message, { variant: "danger", title: "Could not load that conversation" }));
  }
}

function emptyThread() {
  return emptyState(
    "Ask the first question",
    "Try “what does this project do?”, then follow up with “how does that part actually work?”",
    { iconName: "message-square" });
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
  setBusy(button, true, "Opening…");
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
    clear($("#chat-out")).append(errorState(
      error.message,
      "Public repositories only. Check the URL, or add a GITHUB_TOKEN to your .env if you are rate limited.",
      { onRetry: () => openRepo(repoUrl, { force }) },
    ));
    toast(error.message, "bad");
  } finally {
    setBusy(button, false);
  }
}

/* ── Layout ────────────────────────────────────────────────────────────── */

function renderChat({ keepThread = false } = {}) {
  const out = $("#chat-out");
  const existingThread = keepThread ? $("#thread") : null;
  const preserved = existingThread ? [...existingThread.childNodes] : null;

  clear(out);

  const left = el("div", { class: "stack" });
  left.append(repoPanel());
  left.append(card({ title: "Conversations", body: el("div", { class: "sessions", id: "sessions" }) }));

  const right = el("div", { class: "stack" });

  right.append(card({
    title: "What this repository is",
    subtitle: "AI brief",
    body: el("div", { id: "overview" },
      el("p", { class: "hint", text: state.repo.status === "ready" ? "Loading…" : "Available once indexing finishes." })),
  }));

  const thread = el("div", { class: "thread", id: "thread" });
  if (preserved?.length) thread.append(...preserved);
  else thread.append(emptyThread());

  const streamToggle = el("input", {
    type: "checkbox",
    id: "toggle-stream",
    checked: state.streaming ? true : null,
    onChange: (event) => { state.streaming = event.target.checked; },
  });

  const sendButton = button("Ask", {
    variant: "primary", id: "btn-send", iconName: "send",
    onClick: () => ask($("#composer-input").value),
  });

  const composer = el("div", { class: "composer" },
    el("div", { class: "composer__box" },
      el("label", { class: "sr-only", for: "composer-input" }, "Your question about this repository"),
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
      el("div", { class: "composer__bar" },
        sendButton,
        el("span", { class: "composer__side" },
          el("label", { class: "checkbox", title: "Stream the answer token by token" },
            streamToggle, "Stream")),
        el("span", { class: "composer__hint", text: "Enter to send · Shift+Enter for a new line" }))));

  right.append(card({
    title: "Conversation",
    subtitle: state.repo.status === "ready"
      ? "Follow-up questions keep their context"
      : "Waiting for the index to finish",
    body: el("div", {},
      el("div", { class: "evidence__head" }, icon("sparkles", { size: 13 }), "Suggested questions"),
      el("div", { class: "suggested", id: "suggested" },
        ...defaultQuestions().map((question) =>
          el("button", { type: "button", text: question, onClick: () => ask(question) }))),
      el("div", { style: "height:20px" }),
      thread,
      composer),
  }));

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
    if (!url) {
      $("#in-repo").setAttribute("aria-invalid", "true");
      toast("Enter a repository URL first.", "bad");
      return;
    }
    $("#in-repo").removeAttribute("aria-invalid");
    openRepo(url);
  });

  for (const chip of document.querySelectorAll("[data-repo]")) {
    chip.addEventListener("click", () => openRepo(chip.dataset.repo));
  }

  $("#chat-out").append(emptyState(
    "No repository open",
    "Paste a GitHub repository URL above. It gets downloaded, chunked and embedded, then you can ask it questions.",
    { iconName: "folder" }));
}
