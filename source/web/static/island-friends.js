"use strict";

const csrf = document.querySelector('meta[name="island-csrf"]').content;
const feedback = document.getElementById("island-feedback");

function formatTime(element) {
  const when = new Date(Number(element.dataset.time) * 1000);
  if (!isNaN(when)) {
    element.dateTime = when.toISOString();
    element.textContent = when.toLocaleString(document.documentElement.lang);
  }
}
document.querySelectorAll("time[data-time]").forEach(formatTime);

async function peerAction(action, body = {}) {
  const response = await fetch("/island-peers/" + action, {
    method: "POST", credentials: "same-origin",
    headers: {"Content-Type": "application/json", "X-Island-CSRF": csrf},
    body: JSON.stringify(body)
  });
  if (!response.ok) throw new Error("peer request failed");
  return response.json();
}

async function submitOnce(button, operation) {
  button.disabled = true;
  feedback.hidden = true;
  try {
    await operation();
  } catch {
    feedback.textContent = feedback.dataset.error;
    feedback.hidden = false;
    feedback.scrollIntoView({block:"nearest"});
  } finally {
    button.disabled = false;
  }
}

document.getElementById("invite")?.addEventListener("click", event => {
  submitOnce(event.currentTarget, async () => {
    const data = await peerAction("invite");
    const container = document.getElementById("codes");
    container.replaceChildren();
    for (const candidate of data.codes) {
      const field = document.createElement("input");
      field.readOnly = true;
      field.value = candidate.code;
      field.setAttribute("aria-label", candidate.address);
      field.addEventListener("focus", () => field.select());
      container.append(field);
    }
    document.getElementById("invitations").hidden = false;
  });
});

document.getElementById("join")?.addEventListener("submit", event => {
  event.preventDefault();
  submitOnce(event.currentTarget.querySelector("button"), async () => {
    await peerAction("pair", {code: document.getElementById("pair-code").value.trim()});
    location.assign("/islands/?notice=paired");
  });
});
document.addEventListener("click", event => {
  const button = event.target.closest("[data-forget]");
  if (button) submitOnce(button, async () => {
    await peerAction("forget/" + button.dataset.forget);
    location.assign("/islands/");
  });
});

const upload = document.getElementById("upload");
upload?.querySelector('input[type="file"]').addEventListener("change", event => {
  if (event.currentTarget.files.length) upload.requestSubmit();
});

let refreshing = false;
async function refreshPresence() {
  if (document.hidden || !feedback || refreshing) return;
  refreshing = true;
  try {
    const response = await fetch("/islands/updates", {cache: "no-store"});
    if (!response.ok) return;
    const {revision} = await response.json();
    const list = document.querySelector(".island-list");
    if (list && revision !== list.dataset.revision) {
      const page = await fetch(location.href, {cache:"no-store"});
      if (!page.ok) return;
      const next = new DOMParser().parseFromString(await page.text(), "text/html");
      for (const selector of [".island-list", "#footprints"]) {
        const section = next.querySelector(selector);
        if (section) {
          section.querySelectorAll("time[data-time]").forEach(formatTime);
          document.querySelector(selector).replaceWith(section);
        }
      }
    }
  } catch { /* Cached visits remain available when the peer is unreachable. */ }
  finally { refreshing = false; }
}
if (csrf) {
  refreshPresence();
  setInterval(refreshPresence, 30000);
  document.addEventListener("visibilitychange", refreshPresence);
}
