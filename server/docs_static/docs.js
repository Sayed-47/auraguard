/* AuraGuard live /docs page. All dynamic text is written with textContent so
   admin-editable content can never inject markup. */
"use strict";

const $ = (id) => document.getElementById(id);

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function relTime(iso) {
  if (!iso) return "—";
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `${Math.floor(seconds)}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function toneForStatus(status) {
  if (status === "connected") return "green";
  if (status === "stale" || status === "waiting") return "amber";
  return "red";
}

function stateForStatus(status) {
  if (status === "connected") return "up";
  if (status === "stale" || status === "waiting") return "warn";
  return "down";
}

function renderPitch(payload) {
  const pitch = payload.pitch || {};
  $("product-name").textContent = pitch.product_name || "AuraGuard";
  document.title = `${pitch.product_name || "AuraGuard"} — Live Docs`;
  $("tagline").textContent = pitch.tagline || "";
  $("pitch-problem").textContent = pitch.problem || "";
  $("pitch-users").textContent = pitch.users || "";
  $("pitch-approach").textContent = pitch.approach || "";
  for (const id of ["repo-link", "footer-repo"]) {
    const link = $(id);
    if (pitch.repo_url) { link.href = pitch.repo_url; link.classList.remove("hidden"); }
    else link.classList.add("hidden");
  }
  const wrap = $("video-wrap");
  if (pitch.video_url) {
    const video = $("pitch-video");
    const src = video.getAttribute("src");
    if (src !== pitch.video_url) video.src = pitch.video_url;
    wrap.classList.remove("hidden");
  } else wrap.classList.add("hidden");

  const grid = $("feature-grid");
  grid.replaceChildren();
  (pitch.features || []).forEach((feature, index) => {
    const card = el("div", "feature-card");
    card.appendChild(el("span", "feature-num", String(index + 1)));
    card.appendChild(el("p", null, feature));
    grid.appendChild(card);
  });

  const team = $("team-grid");
  team.replaceChildren();
  if (!payload.team || payload.team.length === 0) {
    team.appendChild(el("p", "team-empty", "Team members are added through the admin panel."));
  }
  for (const member of payload.team || []) {
    const card = el("div", "team-card");
    if (member.image_url) {
      const img = el("img", "team-photo");
      img.src = member.image_url;
      img.alt = `Photo of ${member.name}`;
      card.appendChild(img);
    } else {
      const initials = member.name.split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase();
      card.appendChild(el("div", "team-initials", initials));
    }
    card.appendChild(el("div", "team-name", member.name));
    if (member.role) card.appendChild(el("div", "team-role", member.role));
    if (member.email) {
      const mail = el("a", "team-email", member.email);
      mail.href = `mailto:${member.email}`;
      card.appendChild(mail);
    }
    team.appendChild(card);
  }
}

function renderLive(live) {
  const pill = $("status-pill");
  const status = (live.connection && live.connection.status) || "offline";
  pill.dataset.tone = toneForStatus(status);
  $("status-text").textContent = status === "connected" ? "receiver live" : status;

  const chips = $("hero-chips");
  chips.replaceChildren(
    el("span", "chip", `protocol ${live.protocol}`),
    Object.assign(el("span", "chip", `link ${status}`), { dataset: { tone: toneForStatus(status) } }),
    el("span", "chip", `${live.event_total} events stored`),
  );
  if (live.receiver && live.receiver.armed !== null && live.receiver.armed !== undefined) {
    chips.appendChild(el("span", "chip", live.receiver.armed ? "armed" : "disarmed"));
  }

  // Flow diagram node states.
  const nodeState = stateForStatus(status);
  const serialState = live.connection && live.connection.serial ? "up" : "down";
  const states = { sensors: nodeState, esp32: nodeState, ble: nodeState, uno: serialState, gateway: "up", dashboard: "up" };
  document.querySelectorAll(".flow-node").forEach((node) => {
    node.dataset.state = states[node.dataset.node] || "warn";
  });

  // Counters.
  const counters = $("counter-grid");
  counters.replaceChildren();
  const addCounter = (value, label, tone) => {
    const card = el("div", "counter");
    if (tone) card.dataset.tone = tone;
    card.appendChild(el("div", "counter-value", String(value)));
    card.appendChild(el("div", "counter-label", label));
    counters.appendChild(card);
  };
  if (live.receiver) {
    const c = live.receiver.counters || {};
    addCounter(c.fall_reports ?? 0, "fall reports", "critical");
    addCounter(c.cry_episodes ?? 0, "cry episodes", "warning");
    addCounter(c.wander_reports ?? 0, "wander warnings", "warning");
    addCounter(c.acknowledgments ?? 0, "acknowledgments");
  }
  addCounter(live.event_total, "events this session");
  addCounter((live.diagnostics && live.diagnostics.invalid_packets) ?? 0, "invalid packets rejected");

  // Events.
  const list = $("event-list");
  list.replaceChildren();
  const events = live.recent_events || [];
  if (events.length === 0) {
    list.appendChild(el("li", "event-empty", "No events yet — the gateway records receiver events here as they happen."));
  }
  for (const event of events) {
    const item = el("li");
    const dot = el("span", "event-sev");
    dot.dataset.sev = event.severity;
    item.appendChild(dot);
    const body = el("span");
    body.appendChild(el("span", "event-title", event.title));
    body.appendChild(document.createTextNode(` — ${event.detail}`));
    item.appendChild(body);
    item.appendChild(el("span", "event-time", relTime(event.timestamp)));
    list.appendChild(item);
  }

  // Session facts.
  const info = $("session-info");
  info.replaceChildren();
  const rows = [
    ["protocol", live.protocol],
    ["link status", status],
    ["serial port", (live.connection && live.connection.port) || "not configured"],
    ["session started", live.session_started_at ? new Date(live.session_started_at).toLocaleString() : "—"],
    ["uptime", live.session_started_at ? relTime(live.session_started_at).replace(" ago", "") : "—"],
    ["server", live.server ? `${live.server.title} ${live.server.version}` : "—"],
    ["data generated", live.generated_at ? new Date(live.generated_at).toLocaleTimeString() : "—"],
  ];
  if (live.diagnostics && live.diagnostics.last_error) rows.push(["last diagnostic", live.diagnostics.last_error]);
  for (const [key, value] of rows) {
    info.appendChild(el("dt", null, key));
    info.appendChild(el("dd", null, value));
  }

  // Models.
  const models = $("model-grid");
  models.replaceChildren();
  for (const model of live.ai_models || []) {
    const card = el("div", "model-card");
    const head = el("h3", null, `${model.id} classifier`);
    head.appendChild(el("span", "model-kind", model.kind || "model"));
    card.appendChild(head);
    const classes = el("div", "model-classes");
    for (const name of model.classes || []) classes.appendChild(el("span", "model-class", name));
    card.appendChild(classes);
    card.appendChild(el("p", "model-meta", `${model.n_classes} classes · ${model.n_features} physics features · weights v${model.version} · runs on the ESP32`));
    if (model.feature_names && model.feature_names.length) {
      card.appendChild(el("p", "model-features", model.feature_names.join(" · ")));
    }
    models.appendChild(card);
  }
  if ((live.ai_models || []).length === 0) {
    models.appendChild(el("p", "team-empty", "No AI weight files found in server/ai/weights."));
  }

  // API table.
  const apiBody = $("api-table").querySelector("tbody");
  apiBody.replaceChildren();
  for (const route of live.api_routes || []) {
    const tr = el("tr");
    const method = el("td", "method", route.path === "/ws" ? "WS" : route.methods.join(" "));
    method.dataset.m = route.path === "/ws" ? "WS" : route.methods[0];
    tr.appendChild(method);
    tr.appendChild(el("td", "path", route.path));
    tr.appendChild(el("td", null, route.summary || ""));
    apiBody.appendChild(tr);
  }

  // Stack table.
  const stackBody = $("stack-table").querySelector("tbody");
  stackBody.replaceChildren();
  for (const row of live.tech_stack || []) {
    const tr = el("tr");
    tr.appendChild(el("td", null, row.layer));
    tr.appendChild(el("td", null, row.detail));
    stackBody.appendChild(tr);
  }

  // Doc library.
  const docs = $("doc-list");
  docs.replaceChildren();
  for (const doc of live.docs_library || []) {
    const item = el("li");
    const link = el("a", null, doc.path);
    link.href = doc.url;
    link.target = "_blank";
    link.rel = "noopener";
    item.appendChild(link);
    item.appendChild(el("span", null, doc.title));
    docs.appendChild(item);
  }
}

async function refreshFull() {
  try {
    const response = await fetch("/api/docs", { cache: "no-store" });
    if (!response.ok) return;
    const payload = await response.json();
    renderPitch(payload);
    renderLive(payload.live);
  } catch { /* keep the last good render */ }
}

async function refreshLive() {
  try {
    const response = await fetch("/api/docs/live", { cache: "no-store" });
    if (!response.ok) return;
    renderLive(await response.json());
  } catch { /* keep the last good render */ }
}

refreshFull();
setInterval(refreshLive, 4000);
setInterval(refreshFull, 20000);
