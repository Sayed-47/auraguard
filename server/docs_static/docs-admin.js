/* AuraGuard /docs admin panel. Token is kept in sessionStorage only. */
"use strict";

const $ = (id) => document.getElementById(id);
let token = sessionStorage.getItem("docsAdminToken") || "";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function toast(message, isError) {
  const node = $("toast");
  node.textContent = message;
  node.classList.toggle("error", Boolean(isError));
  node.classList.add("show");
  clearTimeout(node._timer);
  node._timer = setTimeout(() => node.classList.remove("show"), 2600);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "X-Admin-Token": token, ...(options.body ? { "Content-Type": "application/json" } : {}), ...(options.headers || {}) },
    cache: "no-store",
  });
  if (response.status === 403) {
    showGate("Token rejected — check server/data/docs-config.json.");
    throw new Error("forbidden");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `request failed (${response.status})`);
  return data;
}

function showGate(message) {
  $("gate").classList.remove("hidden");
  $("panel").classList.add("hidden");
  $("gate-status").textContent = message || "";
}

function showPanel() {
  $("gate").classList.add("hidden");
  $("panel").classList.remove("hidden");
}

function isoToLocal(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

function localToIso(value) {
  return value ? new Date(value).toISOString() : null;
}

const REASONS = {
  open: "public right now",
  disabled: "OFF — /docs answers 404",
  not_yet_open: "scheduled — opens at the from date",
  closed: "window ended — /docs answers 404",
};

async function load() {
  const data = await api("/api/docs/admin");
  showPanel();
  $("visibility-status").innerHTML = "";
  $("visibility-status").appendChild(el("strong", null, `Status: ${REASONS[data.visibility_reason] || data.visibility_reason}`));
  $("vis-enabled").checked = data.enabled;
  $("vis-from").value = isoToLocal(data.visible_from);
  $("vis-until").value = isoToLocal(data.visible_until);

  const pitch = data.pitch || {};
  $("p-name").value = pitch.product_name || "";
  $("p-tagline").value = pitch.tagline || "";
  $("p-problem").value = pitch.problem || "";
  $("p-users").value = pitch.users || "";
  $("p-approach").value = pitch.approach || "";
  $("p-features").value = (pitch.features || []).join("\n");
  $("p-repo").value = pitch.repo_url || "";
  $("p-video").value = pitch.video_url || "";

  renderTeam(data.team || []);
}

function renderTeam(team) {
  const list = $("team-list");
  list.replaceChildren();
  if (team.length === 0) {
    list.appendChild(el("p", "hint", "No members yet."));
    return;
  }
  for (const member of team) {
    const card = el("div", "team-edit");
    card.dataset.id = member.id;

    const head = el("div", "team-edit-head");
    if (member.image_url) {
      const img = el("img", "team-photo");
      img.src = member.image_url;
      img.alt = "";
      head.appendChild(img);
    } else {
      head.appendChild(el("div", "team-initials", member.name.split(/\s+/).map((p) => p[0]).join("").slice(0, 2).toUpperCase()));
    }
    const grow = el("div", "grow");
    grow.appendChild(el("div", "team-name", member.name));
    grow.appendChild(el("div", "team-role", member.role || ""));
    head.appendChild(grow);
    const uploadLabel = el("label", "btn btn-small", "Upload photo");
    const upload = el("input");
    upload.type = "file";
    upload.accept = "image/*";
    upload.className = "hidden";
    upload.addEventListener("change", () => uploadImage(member.id, upload));
    uploadLabel.appendChild(upload);
    head.appendChild(uploadLabel);
    const del = el("button", "btn btn-small btn-danger", "Delete");
    del.addEventListener("click", () => deleteMember(member.id));
    head.appendChild(del);
    card.appendChild(head);

    const row = el("div", "field-row");
    const nameField = el("div", "field");
    nameField.appendChild(el("label", null, "Name"));
    const nameInput = el("input");
    nameInput.value = member.name;
    nameField.appendChild(nameInput);
    const roleField = el("div", "field");
    roleField.appendChild(el("label", null, "Role"));
    const roleInput = el("input");
    roleInput.value = member.role || "";
    roleField.appendChild(roleInput);
    row.appendChild(nameField);
    row.appendChild(roleField);
    card.appendChild(row);

    const emailField = el("div", "field");
    emailField.appendChild(el("label", null, "Email"));
    const emailInput = el("input");
    emailInput.type = "email";
    emailInput.value = member.email || "";
    emailField.appendChild(emailInput);
    card.appendChild(emailField);

    const actions = el("div", "admin-actions");
    const save = el("button", "btn btn-small btn-primary", "Save member");
    save.addEventListener("click", async () => {
      try {
        await api(`/api/docs/admin/team/${member.id}`, { method: "PUT", body: JSON.stringify({ name: nameInput.value, role: roleInput.value, email: emailInput.value }) });
        toast("Member saved — public page updates within seconds.");
        load();
      } catch (err) { toast(err.message, true); }
    });
    actions.appendChild(save);
    card.appendChild(actions);
    list.appendChild(card);
  }
}

async function uploadImage(memberId, input) {
  if (!input.files || !input.files[0]) return;
  const form = new FormData();
  form.append("image", input.files[0]);
  try {
    const response = await fetch(`/api/docs/admin/team/${memberId}/image`, { method: "POST", headers: { "X-Admin-Token": token }, body: form });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `upload failed (${response.status})`);
    toast(`Photo resized to ${data.size}×${data.size} and saved.`);
    load();
  } catch (err) { toast(err.message, true); }
}

async function deleteMember(memberId) {
  if (!confirm("Remove this team member and their photo?")) return;
  try {
    await api(`/api/docs/admin/team/${memberId}`, { method: "DELETE" });
    toast("Member removed.");
    load();
  } catch (err) { toast(err.message, true); }
}

$("token-save").addEventListener("click", async () => {
  token = $("token-input").value.trim();
  sessionStorage.setItem("docsAdminToken", token);
  try { await load(); toast("Unlocked."); } catch { /* gate already shown */ }
});
$("token-input").addEventListener("keydown", (event) => { if (event.key === "Enter") $("token-save").click(); });

$("vis-save").addEventListener("click", async () => {
  try {
    const result = await api("/api/docs/admin", {
      method: "PUT",
      body: JSON.stringify({
        enabled: $("vis-enabled").checked,
        visible_from: localToIso($("vis-from").value),
        visible_until: localToIso($("vis-until").value),
      }),
    });
    toast(`Saved — ${REASONS[result.reason] || result.reason}.`);
    load();
  } catch (err) { toast(err.message, true); }
});

$("pitch-save").addEventListener("click", async () => {
  try {
    await api("/api/docs/admin", {
      method: "PUT",
      body: JSON.stringify({
        pitch: {
          product_name: $("p-name").value,
          tagline: $("p-tagline").value,
          problem: $("p-problem").value,
          users: $("p-users").value,
          approach: $("p-approach").value,
          features: $("p-features").value.split("\n").map((line) => line.trim()).filter(Boolean),
          repo_url: $("p-repo").value,
          video_url: $("p-video").value,
        },
      }),
    });
    toast("Pitch saved — public page updates within seconds.");
  } catch (err) { toast(err.message, true); }
});

$("team-add").addEventListener("click", async () => {
  try {
    await api("/api/docs/admin/team", { method: "POST", body: JSON.stringify({ name: $("t-name").value, role: $("t-role").value, email: $("t-email").value }) });
    $("t-name").value = $("t-role").value = $("t-email").value = "";
    toast("Member added.");
    load();
  } catch (err) { toast(err.message, true); }
});

if (token) {
  $("token-input").value = token;
  load().catch(() => { /* gate shown on 403; other errors keep the gate too */ showGate(); });
} else {
  showGate("Enter the admin token to manage the docs page.");
}
