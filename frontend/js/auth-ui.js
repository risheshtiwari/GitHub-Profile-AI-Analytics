/* Account dialog: register / sign in, and the "you need an account" prompt
   that write actions call before they start work. */

import { api, auth } from "./api.js";
import { $, el, toast } from "./ui.js";
import { icon, setBusy } from "./components.js";

let mode = "register";
let pendingAction = null;   // what the user was trying to do when we interrupted

let lastFocused = null;

export function openAuth(message, retry = null) {
  pendingAction = retry;
  const error = $("#auth-err");
  error.hidden = true;

  if (message) {
    // A reason for the interruption, not an error — styled as a hint.
    error.replaceChildren(icon("info", { size: 14 }), document.createTextNode(message));
    error.hidden = false;
    error.style.color = "var(--text-tertiary)";
  }

  lastFocused = document.activeElement;
  $("#scrim").hidden = false;
  $("#in-auth-user").focus();
}

export function closeAuth() {
  $("#scrim").hidden = true;
  pendingAction = null;
  // Return focus to whatever opened the dialog, so keyboard users aren't dumped
  // at the top of the document.
  if (lastFocused?.isConnected) lastFocused.focus();
  lastFocused = null;
}

/**
 * Returns true if signed in. Otherwise opens the dialog and returns false —
 * pass `retry` and the interrupted action runs itself once they're signed in,
 * so nobody has to click the same button twice.
 */
export function requireAuth(message, retry = null) {
  if (auth.signedIn) return true;
  openAuth(message || "Sign in to continue.", retry);
  return false;
}

export function refreshAccountButton() {
  const button = $("#btn-account");
  const avatar = $("#account-avatar");
  const name = $("#account-name");
  const hint = $("#account-hint");
  const iconSlot = $("#account-icon");

  if (auth.signedIn) {
    avatar.textContent = auth.username.slice(0, 2).toUpperCase();
    name.textContent = auth.username;
    hint.textContent = "Signed in";
    button.title = "Sign out";
    iconSlot.replaceChildren(icon("log-out", { size: 15, label: "Sign out" }));
  } else {
    avatar.textContent = "?";
    name.textContent = "Not signed in";
    hint.textContent = "Sign in to run analyses";
    button.title = "Create an account or sign in";
    iconSlot.replaceChildren(icon("log-in", { size: 15, label: "Sign in" }));
  }
}

function setMode(next) {
  mode = next;
  for (const tab of document.querySelectorAll("#auth-tabs .tab")) {
    tab.setAttribute("aria-selected", String(tab.dataset.mode === next));
  }
  $("#btn-auth-submit").textContent = next === "register" ? "Create account" : "Sign in";
  $("#in-auth-pass").setAttribute("autocomplete", next === "register" ? "new-password" : "current-password");
}

/** Keeps Tab cycling inside the dialog while it is open. */
function trapFocus(event) {
  if (event.key !== "Tab" || $("#scrim").hidden) return;
  const focusable = $("#auth-modal").querySelectorAll(
    'button, input, [href], select, textarea, [tabindex]:not([tabindex="-1"])');
  if (!focusable.length) return;

  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

export function mountAuth() {
  refreshAccountButton();

  $("#btn-account").addEventListener("click", () => {
    if (auth.signedIn) {
      auth.clear();
      refreshAccountButton();
      toast("Signed out", "info");
    } else {
      openAuth();
    }
  });

  for (const tab of document.querySelectorAll("#auth-tabs .tab")) {
    tab.addEventListener("click", () => setMode(tab.dataset.mode));
  }

  $("#btn-auth-cancel").addEventListener("click", closeAuth);

  $("#scrim").addEventListener("click", (event) => {
    if (event.target.id === "scrim") closeAuth();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("#scrim").hidden) closeAuth();
    trapFocus(event);
  });

  $("#form-auth").addEventListener("submit", async (event) => {
    event.preventDefault();
    const username = $("#in-auth-user").value.trim();
    const password = $("#in-auth-pass").value;
    const error = $("#auth-err");
    const submit = $("#btn-auth-submit");

    error.hidden = true;
    setBusy(submit, true, mode === "register" ? "Creating…" : "Signing in…");

    try {
      const result = mode === "register"
        ? await api.register(username, password)
        : await api.login(username, password);
      auth.set(result.access_token, username);
      refreshAccountButton();

      $("#in-auth-user").removeAttribute("aria-invalid");
      const resume = pendingAction;
      closeAuth();   // clears pendingAction, so grab it first
      toast(mode === "register" ? `Account created — welcome, ${username}` : `Signed in as ${username}`, "good");
      resume?.();
    } catch (apiError) {
      const message = apiError.status === 400 && mode === "register"
        ? "That username is taken. Switch to Sign in, or pick another."
        : apiError.message;
      error.style.color = "var(--danger-600)";
      error.replaceChildren(icon("alert-circle", { size: 14 }), document.createTextNode(message));
      error.hidden = false;
      $("#in-auth-user").setAttribute("aria-invalid", "true");
    } finally {
      setBusy(submit, false);
    }
  });

  setMode("register");
}
