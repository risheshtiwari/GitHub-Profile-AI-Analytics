/* Account dialog: register / sign in, and the "you need an account" prompt
   that write actions call before they start work. */

import { api, auth } from "./api.js";
import { $, toast } from "./ui.js";

let mode = "register";
let pendingAction = null;   // what the user was trying to do when we interrupted

export function openAuth(message, retry = null) {
  pendingAction = retry;
  const error = $("#auth-err");
  error.hidden = true;
  if (message) {
    error.textContent = message;
    error.hidden = false;
    error.style.color = "var(--ink-2)";
  }
  $("#scrim").hidden = false;
  $("#in-auth-user").focus();
}

export function closeAuth() {
  $("#scrim").hidden = true;
  pendingAction = null;
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
  if (auth.signedIn) {
    button.textContent = `${auth.username} · sign out`;
    button.title = "Sign out";
  } else {
    button.textContent = "Sign in";
    button.title = "Create an account or sign in";
  }
}

function setMode(next) {
  mode = next;
  for (const tab of document.querySelectorAll("#auth-tabs .tab")) {
    tab.classList.toggle("is-active", tab.dataset.mode === next);
  }
  $("#btn-auth-submit").textContent = next === "register" ? "Create account" : "Sign in";
  $("#in-auth-pass").setAttribute("autocomplete", next === "register" ? "new-password" : "current-password");
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
  });

  $("#form-auth").addEventListener("submit", async (event) => {
    event.preventDefault();
    const username = $("#in-auth-user").value.trim();
    const password = $("#in-auth-pass").value;
    const error = $("#auth-err");
    const submit = $("#btn-auth-submit");

    error.hidden = true;
    submit.disabled = true;

    try {
      const result = mode === "register"
        ? await api.register(username, password)
        : await api.login(username, password);
      auth.set(result.access_token, username);
      refreshAccountButton();

      const resume = pendingAction;
      closeAuth();   // clears pendingAction, so grab it first
      toast(mode === "register" ? `Account created — welcome, ${username}` : `Signed in as ${username}`, "good");
      resume?.();
    } catch (apiError) {
      error.style.color = "var(--danger)";
      error.textContent = apiError.status === 400 && mode === "register"
        ? "That username is taken. Switch to Sign in, or pick another."
        : apiError.message;
      error.hidden = false;
    } finally {
      submit.disabled = false;
    }
  });

  setMode("register");
}
