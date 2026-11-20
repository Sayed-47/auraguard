/* AuraGuard · live receiver dashboard. */
'use strict';

/* Icons: Lucide (https://lucide.dev), ISC License (c) Lucide Contributors.
   Semantic key names are kept stable; paths are the upstream Lucide set:
   baby (baby unit), radio-receiver (room receiver), audio-waveform (sound),
   triangle-alert (fall), bluetooth-off (link down), bell-off (muted), etc. */
const paths = {
  home: '<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"/><path d="M3 10a2 2 0 0 1 .709-1.528l7-6a2 2 0 0 1 2.582 0l7 6A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  signal: '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>',
  history: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
  settings: '<path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915"/><circle cx="12" cy="12" r="3"/>',
  moon: '<path d="M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 8.268c.344-.215.825-.004.803.401"/>',
  bluetooth: '<path d="m7 7 10 10-5 5V2l5 5L7 17"/>',
  cpu: '<path d="M10 16c.5.3 1.2.5 2 .5s1.5-.2 2-.5"/><path d="M15 12h.01"/><path d="M19.38 6.813A9 9 0 0 1 20.8 10.2a2 2 0 0 1 0 3.6 9 9 0 0 1-17.6 0 2 2 0 0 1 0-3.6A9 9 0 0 1 12 3c2 0 3.5 1.1 3.5 2.5s-.9 2.5-2 2.5c-.8 0-1.5-.4-1.5-1"/><path d="M9 12h.01"/>',
  base: '<path d="M5 16v2"/><path d="M19 16v2"/><rect width="20" height="8" x="2" y="8" rx="2"/><path d="M18 12h.01"/>',
  sound: '<path d="M2 13a2 2 0 0 0 2-2V7a2 2 0 0 1 4 0v13a2 2 0 0 0 4 0V4a2 2 0 0 1 4 0v13a2 2 0 0 0 4 0v-4a2 2 0 0 1 2-2"/>',
  warning: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
  calendar: '<path d="M8 2v3"/><path d="M16 2v3"/><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/>',
  shield: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
  mute: '<path d="M10.268 21a2 2 0 0 0 3.464 0"/><path d="M17 17H4a1 1 0 0 1-.74-1.673C4.59 13.956 6 12.499 6 8a6 6 0 0 1 .258-1.742"/><path d="m2 2 20 20"/><path d="M8.668 3.01A6 6 0 0 1 18 8c0 2.687.77 4.653 1.707 6.05"/>',
  pause: '<rect x="14" y="3" width="5" height="18" rx="1"/><rect x="5" y="3" width="5" height="18" rx="1"/>',
  off: '<path d="m17 17-5 5V12l-5 5"/><path d="m2 2 20 20"/><path d="M14.5 9.5 17 7l-5-5v4.5"/>',
  link: '<path d="M9 17H7A5 5 0 0 1 7 7h2"/><path d="M15 7h2a5 5 0 1 1 0 10h-2"/><line x1="8" x2="16" y1="12" y2="12"/>',
  arrow: '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
  download: '<path d="M12 15V3"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/>',
  search: '<path d="m21 21-4.34-4.34"/><circle cx="11" cy="11" r="8"/>',
  close: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  refresh: '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>'
};
const icon = (name, size = 18) => `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.signal}</svg>`;
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
const setText = (id, value) => {const element = $(id); if (element && element.textContent !== String(value)) element.textContent = String(value);};
function readStore(key) {try {return JSON.parse(localStorage.getItem(key));} catch {return null;}}
function savePreferences() {try {localStorage.setItem('auraguard.preferences', JSON.stringify(preferences));} catch {}}
const saved = readStore('auraguard.preferences');
const preferences = {room: typeof saved?.room === 'string' ? saved.room.slice(0, 40) : 'Baby’s room', theme: saved?.theme === 'dark' ? 'dark' : 'light', hour12: saved?.hour12 !== false};
const validViews = ['home', 'telemetry', 'history', 'settings'];
const state = {
  view: validViews.includes(location.hash.slice(1)) ? location.hash.slice(1) : 'home',
  snapshot: ReceiverProfile.empty(), connected: false, receivedAt: 0, backendUrl: '',
  ws: null, reconnectTimer: null, generation: 0, connecting: false, lastError: '',
  events: [], eventsFingerprint: '', filter: 'all', search: '', browserSound: false, audio: null, toastTimer: null
};
const live = () => ReceiverProfile.view(state.snapshot, state.connected, state.receivedAt);
const pill = (label, color = 'gray') => `<span class="pill ${color}"><span class="dot"></span>${esc(label)}</span>`;
function setPill(id, label, color) {const element = $(id), markup = pill(label, color); if (element && element.innerHTML !== markup) element.innerHTML = markup;}
function timeString(value, seconds = false) {
  if (!value || !Number.isFinite(Date.parse(value))) return '—';
  return new Date(value).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', ...(seconds ? {second:'2-digit'} : {}), hour12:preferences.hour12});
}
function shortAge(milliseconds) {
  if (milliseconds === null) return '—';
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  return seconds < 60 ? `${seconds}s` : seconds < 3600 ? `${Math.floor(seconds / 60)}m` : `${Math.floor(seconds / 3600)}h`;
}
function eventIcon(type) {return icon(({fall:'warning', cry:'sound', connection:'bluetooth', system:'shield'})[type], 17);}
function brand() {
  return `<span class="brand-mark"><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" opacity=".3"/><g transform="translate(4.8 4.8) scale(0.6)" stroke-width="3.33"><path d="M10 16c.5.3 1.2.5 2 .5s1.5-.2 2-.5"/><path d="M15 12h.01"/><path d="M19.38 6.813A9 9 0 0 1 20.8 10.2a2 2 0 0 1 0 3.6 9 9 0 0 1-17.6 0 2 2 0 0 1 0-3.6A9 9 0 0 1 12 3c2 0 3.5 1.1 3.5 2.5s-.9 2.5-2 2.5c-.8 0-1.5-.4-1.5-1"/><path d="M9 12h.01"/></g></svg></span><span class="brand-name">auraguard<span>.</span></span>`;
}
function navLinks() {
  return [['home','home','Overview'], ['telemetry','signal','Live feed'], ['history','history','History'], ['settings','settings','Settings']].map(([view, symbol, label]) => `<a class="nav-link ${state.view === view ? 'active' : ''}" href="#${view}" data-view="${view}" ${state.view === view ? 'aria-current="page"' : ''}>${icon(symbol, 18)}<span>${label}</span></a>`).join('');
}
function renderShell() {
  $('app').innerHTML = `<div class="shell"><header class="site-header"><div class="header-inner"><a class="brand" href="#home" data-view="home" aria-label="AuraGuard home">${brand()}</a><nav class="desktop-nav" aria-label="Main navigation">${navLinks()}</nav><div class="top-actions"><span class="header-pill" id="header-source"><span class="dot"></span><span id="header-label">Waiting</span></span><button class="icon-button" data-action="theme" aria-label="Toggle night view" title="Toggle night view">${icon('moon', 19)}</button></div></div></header><main class="content" id="main" tabindex="-1"><div id="view"></div><footer class="footer"><span>AuraGuard <span class="footer-dot">·</span> Baby monitoring</span><span id="footer-status">Waiting for a local connection</span></footer></main></div><nav class="mobile-nav" aria-label="Mobile navigation">${navLinks()}</nav>`;
  renderView();
}
function heading(title, label, action = '') {
  return `<div class="page-heading"><div><div class="eyebrow">${esc(label)}</div><h1>${title}</h1></div><div class="heading-actions">${action || `<span class="date-label">${icon('calendar', 16)}${new Date().toLocaleDateString([], {day:'numeric', month:'long'})}</span><button class="btn" data-action="setup" aria-label="Connection">${icon('link', 16)}<span>Connection</span></button>`}</div></div>`;
}
function hero() {
  return `<section class="monitor-hero alert-waiting" id="hero-card" aria-labelledby="hero-title"><div class="hero-top"><span class="hero-status"><span class="dot"></span><span id="hero-status">Ready to connect</span></span><span class="hero-update" id="hero-stamp">Live monitor</span></div><div class="hero-content"><div class="hero-copy"><h2 id="hero-title" role="status" aria-live="polite">Waiting for receiver.</h2><p id="hero-detail">Connect the room receiver to begin monitoring.</p></div><div class="status-symbol" id="hero-symbol" aria-hidden="true">${icon('link', 42)}</div></div><div class="hero-bottom"><span class="hero-note" id="hero-annotation">No device connected</span><button class="btn btn-dark" id="hero-connect" data-action="setup">${icon('link', 15)}Connect receiver</button><button class="btn btn-dark hidden" id="hero-history" data-view="history">View activity ${icon('arrow', 15)}</button></div></section>`;
}
function devices() {
  return `<section class="card devices-card"><div class="card-head"><h2>Devices</h2><button class="icon-button" data-view="settings" aria-label="Connection settings">${icon('settings', 17)}</button></div><div class="device-row"><span class="device-icon">${icon('cpu', 24)}</span><div class="device-info"><strong>Baby unit</strong><small>ESP32 · Motion & sound</small></div><span id="baby-pill">${pill('Waiting')}</span></div><div class="device-bridge"><span></span>${icon('bluetooth', 13)}Bluetooth</div><div class="device-row"><span class="device-icon receiver">${icon('base', 24)}</span><div class="device-info"><strong>Room receiver</strong><small>Arduino Uno · USB</small></div><span id="receiver-pill">${pill('Waiting')}</span></div><div class="device-meta"><span>Gateway</span><span id="gateway-label">Not connected</span></div></section>`;
}
function metrics() {
  return `<div class="metric-grid">${[['shield','Monitoring','metric-armed'], ['warning','Fall alert','metric-fall'], ['sound','Sound alert','metric-cry'], ['clock','Last signal','metric-age']].map(([symbol, label, id]) => `<section class="metric"><div class="metric-top">${icon(symbol, 17)}<span>${label}</span></div><div class="metric-value" id="${id}">—</div><div class="metric-caption" id="${id}-caption">Waiting for receiver</div></section>`).join('')}</div>`;
}
function home() {
  return heading(`<span data-room>${esc(preferences.room)}</span>`, 'LIVE MONITOR') + `<div class="top-grid">${hero()}${devices()}</div>` + metrics() + `<section class="card activity-card"><div class="card-head"><h2>Recent activity</h2><a class="text-link" href="#history" data-view="history">View all ${icon('arrow', 14)}</a></div><div id="recent-events"></div></section>`;
}
function specRow(label, id, initial = '—') {return `<div class="spec-row"><span>${label}</span><strong id="${id}">${initial}</strong></div>`;}
function telemetry() {
  return heading('Live feed', 'RECEIVER STATUS') + `<div class="section-grid"><section class="card section-card"><div class="card-head"><h2>Receiver state</h2><span id="feed-pill">${pill('Waiting')}</span></div><div class="spec-list">${specRow('Monitoring','feed-armed')}${specRow('Fall alert','feed-fall')}${specRow('Sound alert','feed-cry')}${specRow('Alarm sound','feed-mute')}${specRow('Baby link','feed-baby')}${specRow('Last signal','feed-age')}</div><div class="card-note">ACK and ARM are controlled on the receiver.</div></section><section class="card section-card"><h2>This session</h2><div class="session-counters"><div><strong id="count-fall">—</strong><span>Fall reports</span></div><div><strong id="count-cry">—</strong><span>Sound alerts</span></div><div><strong id="count-ack">—</strong><span>Acknowledgments</span></div></div><div class="spec-list">${specRow('Session started','session-start')}${specRow('Latest status','last-status')}${specRow('Serial port','feed-port')}</div></section></div><section class="card section-card raw-card"><div class="card-head"><h2>Latest receiver message</h2><span class="mono subtle">9600 baud</span></div><pre class="receiver-line" id="receiver-line">Waiting for receiver…</pre><p class="small-note" id="feed-error"></p></section>`;
}
function historyView() {
  return heading('Activity history','RECORDED EVENTS',`<button class="btn" data-action="export">${icon('download',15)}Export CSV</button>`) + `<div class="log-toolbar"><div class="filter-pills" aria-label="Filter events">${[['all','All events'],['fall','Falls'],['cry','Sound'],['connection','Connection'],['system','Receiver']].map(([key,label]) => `<button class="filter-pill ${state.filter === key ? 'active' : ''}" data-filter="${key}" aria-pressed="${state.filter === key}">${label}</button>`).join('')}</div><label class="search-field">${icon('search',16)}<input type="search" id="event-search" value="${esc(state.search)}" placeholder="Search events" aria-label="Search events"></label></div><div id="history-list"></div><div class="history-count" id="history-count"></div>`;
}
function settings() {
  return heading('Settings','YOUR MONITOR') + `<div class="section-grid"><section class="card section-card"><h2>Connection</h2><div class="spec-list">${specRow('Local gateway','settings-gateway')}${specRow('Room receiver','settings-receiver')}${specRow('Baby unit','settings-baby')}${specRow('Serial port','settings-port')}${specRow('Baud rate','settings-baud','9600')}</div><div class="card-actions"><button class="btn btn-primary" data-action="setup">${icon('link',15)}Connection setup</button><button class="btn" data-action="reconnect">${icon('refresh',15)}Reconnect</button></div><p class="small-note" id="settings-error"></p></section><section class="card section-card"><h2>Preferences</h2><form id="preferences-form"><div class="field"><label for="room-name">Room name</label><input id="room-name" name="room" maxlength="40" value="${esc(preferences.room)}" required></div><div class="setting-row"><span class="setting-label"><strong>Night view</strong></span><button class="switch" type="button" role="switch" aria-label="Night view" aria-checked="${preferences.theme === 'dark'}" data-action="theme" id="theme-switch"><span></span></button></div><div class="setting-row"><span class="setting-label"><strong>Browser alert sound</strong><small>This open tab only</small></span><button class="switch" type="button" role="switch" aria-label="Browser alert sound" aria-checked="${state.browserSound}" data-action="sound"><span></span></button></div><div class="field"><label for="time-format">Time format</label><select id="time-format"><option value="true" ${preferences.hour12 ? 'selected' : ''}>12-hour clock</option><option value="false" ${!preferences.hour12 ? 'selected' : ''}>24-hour clock</option></select></div><div class="form-footer"><span class="small-note">Saved in this browser</span><button class="btn btn-primary" type="submit">Save preferences</button></div></form></section></div><div class="download-strip"><span>${icon('download',16)}Dashboard, gateway & firmware</span><a class="text-link" href="./downloads/auraguard-project.zip" download>Download project ${icon('arrow',14)}</a></div>`;
}
function renderView() {
  $('view').innerHTML = ({home,telemetry,history:historyView,settings})[state.view](); state.eventsFingerprint = ''; paint();
  document.querySelectorAll('.desktop-nav, .mobile-nav').forEach(nav => {nav.innerHTML = navLinks();});
}
function navigate(view) {
  if (!validViews.includes(view)) view = 'home'; state.view = view;
  if (location.hash !== `#${view}`) window.history.replaceState(null,'',`#${view}`);
  renderView(); window.scrollTo({top:0,behavior:'instant'}); $('main').focus({preventScroll:true});
}

const heroCopy = {
  waiting: ['Ready to connect','Waiting for receiver.','Connect the room receiver to begin monitoring.','link'],
  disconnected: ['Gateway disconnected','Connection interrupted.','Reconnecting to your local gateway.','off'],
  stale: ['Receiver unavailable','Waiting for an update.','Check the receiver’s USB connection.','off'],
  pairing: ['Receiver online','Waiting for baby unit.','The room receiver is ready for a Bluetooth connection.','bluetooth'],
  delayed: ['Signal delayed','Waiting for a signal.','The receiver is online. Baby-unit data is delayed.','bluetooth'],
  offline: ['Baby unit disconnected','Connection lost.','Check the baby unit and Bluetooth link.','off'],
  paused: ['Monitoring disarmed','Monitoring is paused.','Use ARM on the receiver to resume alarms.','pause'],
  fall: ['Fall alert','Possible fall reported.','Check the baby unit. Use ACK on the receiver to clear the alert.','warning'],
  cry: ['Sound alert','Sustained sound reported.','The receiver’s sound alert is active.','sound'],
  muted: ['Receiver acknowledged','Alarm sound is muted.','The receiver’s temporary mute is active.','mute'],
  normal: ['Monitoring active','Connected and monitoring.','No active alerts reported by the receiver.','shield'],
  observing: ['Receiving live data','Receiver is online.','Waiting for the full receiver state.','signal']
};
function paintHero(v) {
  if (!$('hero-card')) return;
  const copy = heroCopy[v.status], tone = v.status === 'normal' ? 'normal' : v.status === 'fall' ? 'fall' : ['cry','muted','delayed'].includes(v.status) ? 'cry' : 'waiting';
  $('hero-card').className = `monitor-hero alert-${tone}`;
  setText('hero-status',copy[0]); setText('hero-title',copy[1]); setText('hero-detail',copy[2]); setText('hero-stamp',v.fresh ? 'Live receiver' : 'Live monitor');
  const symbol = $('hero-symbol'); if (symbol.dataset.symbol !== copy[3]) {symbol.dataset.symbol = copy[3]; symbol.innerHTML = icon(copy[3],42);}
  setText('hero-annotation',v.muted > 0 ? `Room alarm muted · ${v.muted}s` : v.fresh ? `Last status ${timeString(state.snapshot.receiver.last_status_at,true)}` : v.gateway ? 'Local gateway connected' : state.lastError || 'No device connected');
  $('hero-connect').classList.toggle('hidden',v.fresh); $('hero-history').classList.toggle('hidden',!v.fresh);
}
function recentEvents() {
  const events = state.events.slice(0,4);
  return events.length ? `<div class="recent-list">${events.map(e => `<div class="event-mini"><span class="event-icon ${e.type}">${eventIcon(e.type)}</span><div class="event-mini-body"><strong>${esc(e.title)}</strong><small>${({fall:'Fall report',cry:'Sound alert',connection:'Connection',system:'Receiver'})[e.type]}</small></div><time datetime="${esc(e.timestamp)}">${timeString(e.timestamp)}</time></div>`).join('')}</div>` : `<div class="empty"><span class="empty-symbol">${icon('history',26)}</span><strong>No activity yet</strong><p>Events will appear when your receiver is connected.</p></div>`;
}
function paintHistory() {
  if (!$('history-list')) return;
  const query = state.search.trim().toLowerCase(), events = state.events.filter(e => (state.filter === 'all' || e.type === state.filter) && `${e.title} ${e.detail}`.toLowerCase().includes(query)), groups = new Map();
  for (const event of events) {const day = new Date(event.timestamp).toLocaleDateString([],{weekday:'long',month:'short',day:'numeric'}); if (!groups.has(day)) groups.set(day,[]); groups.get(day).push(event);}
  $('history-list').innerHTML = events.length ? [...groups].map(([day,rows]) => `<div class="timeline-group-label">${esc(day)}</div><section class="card timeline-group">${rows.map(e => `<article class="timeline-row"><span class="event-icon ${e.type}">${eventIcon(e.type)}</span><div class="timeline-content"><div class="timeline-top"><h2>${esc(e.title)}</h2><time datetime="${esc(e.timestamp)}">${timeString(e.timestamp,true)}</time></div><p>${esc(e.detail)}</p>${e.acknowledged && ['cry','fall'].includes(e.type) ? '<span class="ack-label">Acknowledged on receiver</span>' : ''}</div></article>`).join('')}</section>`).join('') : `<section class="card empty"><span class="empty-symbol">${icon('history',26)}</span><strong>${query || state.filter !== 'all' ? 'No matching events' : 'No events recorded'}</strong><p>${query || state.filter !== 'all' ? 'Try another search or filter.' : 'Your receiver activity will appear here.'}</p></section>`;
  setText('history-count',`${events.length} ${events.length === 1 ? 'event' : 'events'}${state.events.length !== events.length ? ` · ${state.events.length} total` : ''}`);
}
function paint() {
  const d = state.snapshot, r = d.receiver, v = live();
  const receiverLabel = v.fresh ? 'Online' : v.gateway && d.connection.serial ? 'Waiting' : state.receivedAt && !v.gateway ? 'Unknown' : 'Not connected';
  const babyLabel = v.baby ? 'Connected' : !v.fresh ? 'Waiting' : d.connection.status === 'waiting' ? 'Waiting' : 'No signal';
  const armedLabel = v.armed === true ? 'Armed' : v.armed === false ? 'Disarmed' : '—';
  const fallLabel = v.fall === true ? 'Active' : v.fall === false ? 'Clear' : v.fresh ? 'Unconfirmed' : '—';
  const cryLabel = v.cry === true ? 'Active' : v.cry === false ? 'Clear' : '—';
  const muteLabel = v.muted === null ? 'Unconfirmed' : v.muted > 0 ? `Muted · ${v.muted}s` : 'Not muted';
  setText('header-label',v.fresh ? 'Live' : v.gateway ? 'Gateway online' : state.receivedAt ? 'Disconnected' : 'Waiting');
  $('header-source').dataset.tone = v.fresh ? 'green' : state.receivedAt && !v.gateway ? 'red' : 'gray';
  setText('footer-status',v.gateway ? 'Connected to local gateway' : 'Waiting for a local connection'); paintHero(v);
  setPill('baby-pill',babyLabel,v.baby ? 'green' : v.fresh && babyLabel === 'No signal' ? 'amber' : 'gray');
  setPill('receiver-pill',receiverLabel,v.fresh ? 'green' : 'gray'); setPill('feed-pill',receiverLabel,v.fresh ? 'green' : 'gray'); setText('gateway-label',v.gateway ? 'Connected' : 'Not connected');
  for (const [key,value,caption,tone] of [
    ['armed',armedLabel,v.armed === false ? 'Alarms paused' : 'Room receiver',v.armed === true ? 'green' : ''],
    ['fall',fallLabel,v.fall === null && v.fresh ? 'Not yet reported' : 'Receiver state',v.fall === true ? 'red' : ''],
    ['cry',cryLabel,'Receiver state',v.cry === true ? 'amber' : ''],
    ['age',shortAge(v.age),'Reported signal age','']
  ]) {setText(`metric-${key}`,value); setText(`metric-${key}-caption`,caption); if ($(`metric-${key}`)) $(`metric-${key}`).dataset.tone = tone;}
  for (const [key,value] of Object.entries({armed:armedLabel,fall:fallLabel,cry:cryLabel,mute:v.fresh ? muteLabel : '—',baby:babyLabel,age:v.age === null ? '—' : `~${shortAge(v.age)} ago`,port:d.connection.port || 'Not connected'})) setText(`feed-${key}`,value);
  const hasSession = state.receivedAt > 0;
  setText('count-fall',hasSession ? r.counters.fall_reports : '—'); setText('count-cry',hasSession ? r.counters.cry_episodes : '—'); setText('count-ack',hasSession ? r.counters.acknowledgments : '—');
  setText('session-start',timeString(r.session_started_at)); setText('last-status',timeString(r.last_status_at,true)); setText('receiver-line',r.last_line || 'Waiting for receiver…');
  const error = state.lastError || d.diagnostics.last_error || ''; setText('feed-error',error); setText('settings-error',error);
  setText('settings-gateway',v.gateway ? 'Connected' : 'Not connected'); setText('settings-receiver',receiverLabel); setText('settings-baby',babyLabel); setText('settings-port',d.connection.port || 'Not connected');
  document.querySelectorAll('[data-room]').forEach(element => {element.textContent = preferences.room;});
  const fingerprint = state.events.map(e => `${e.id}:${e.acknowledged}`).join('|') || 'empty';
  if (state.eventsFingerprint !== fingerprint || state.eventsFingerprint === '') {if ($('recent-events')) $('recent-events').innerHTML = recentEvents(); paintHistory(); state.eventsFingerprint = fingerprint || 'empty';}
}
function toast(message) {setText('toast',message); $('toast').classList.add('show'); clearTimeout(state.toastTimer); state.toastTimer = setTimeout(() => $('toast').classList.remove('show'),4300);}
function beep() {
  if (!state.browserSound) return;
  try {
    state.audio ||= new (window.AudioContext || window.webkitAudioContext)(); state.audio.resume();
    const oscillator = state.audio.createOscillator(), gain = state.audio.createGain(); oscillator.connect(gain); gain.connect(state.audio.destination); oscillator.frequency.value = 660;
    gain.gain.setValueAtTime(.035,state.audio.currentTime); gain.gain.exponentialRampToValueAtTime(.001,state.audio.currentTime + .45); oscillator.start(); oscillator.stop(state.audio.currentTime + .45);
  } catch {toast('Alert audio is unavailable in this browser.');}
}
function switchTheme() {preferences.theme = preferences.theme === 'dark' ? 'light' : 'dark'; document.documentElement.dataset.theme = preferences.theme; savePreferences(); $('theme-switch')?.setAttribute('aria-checked',preferences.theme === 'dark');}
function setupDialog() {
  const element = $('dialog');
  element.innerHTML = `<div class="dialog-head"><div><div class="eyebrow">LOCAL CONNECTION</div><h2 id="dialog-title">Connect your receiver</h2></div><button class="icon-button" data-action="close-dialog" aria-label="Close dialog">${icon('close',18)}</button></div><div class="dialog-body"><ol class="setup-steps"><li><strong>Connect the Arduino Uno by USB.</strong><p>Close Arduino Serial Monitor before starting the gateway.</p></li><li><strong>Start the gateway.</strong><p>Run these commands in the downloaded project folder. Replace COM4 with your Uno’s port.</p><pre class="code-block">python -m pip install -r server/requirements.txt\npython server/app.py --list-ports\npython server/app.py --port COM4 --baud 9600</pre></li><li><strong>Open the local dashboard.</strong><p><a href="http://127.0.0.1:8000" target="_blank" rel="noopener">http://127.0.0.1:8000 ${icon('arrow',12)}</a></p></li></ol><p class="small-note">The supplied firmware works unchanged. Use the local dashboard on the receiver’s computer for live data.</p><div class="dialog-actions"><a class="btn" href="./downloads/auraguard-project.zip" download>${icon('download',14)}Download project</a><button class="btn btn-primary" data-action="close-dialog">Done</button></div></div>`;
  if (!element.open) element.showModal();
}
function mergeEvents(previous,current) {const map = new Map(previous.map(e => [e.id,e])); for (const event of current) map.set(event.id,event); return [...map.values()].sort((a,b) => Date.parse(b.timestamp) - Date.parse(a.timestamp)).slice(0,2000);}
function receive(raw,initial = false) {
  const fresh = ReceiverProfile.normalize(raw);
  const sessionChanged = state.snapshot.receiver.session_started_at && state.snapshot.receiver.session_started_at !== fresh.receiver.session_started_at;
  if (sessionChanged) state.events = [];
  const prior = new Set(state.events.map(e => e.id));
  state.snapshot = fresh; state.receivedAt = Date.now(); state.connected = true; state.lastError = ''; state.events = mergeEvents(state.events,fresh.events);
  if (!initial && !sessionChanged && fresh.events.some(e => !prior.has(e.id) && !e.acknowledged && ['fall','cry'].includes(e.type) && ['warning','critical'].includes(e.severity))) beep(); paint();
}
async function refreshEvents(generation) {
  try {const response = await fetch(`${state.backendUrl}/api/events?limit=2000`,{cache:'no-store',signal:AbortSignal.timeout(5000)}); if (!response.ok) return; const events = ReceiverProfile.cleanEvents(await response.json()); if (generation !== state.generation) return; state.events = mergeEvents(state.events,events); paint();} catch { /* Snapshots still include recent events. */ }
}
function closeTransport() {clearTimeout(state.reconnectTimer); state.reconnectTimer = null; if (state.ws) {state.ws.onclose = null; state.ws.onerror = null; state.ws.close(); state.ws = null;}}
function scheduleReconnect(generation) {clearTimeout(state.reconnectTimer); state.reconnectTimer = setTimeout(() => {if (generation === state.generation) connectGateway(true);},3000);}
function openSocket(generation) {
  const url = new URL('/ws',state.backendUrl); url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'; const socket = new WebSocket(url); state.ws = socket;
  socket.onmessage = event => {if (generation !== state.generation || state.ws !== socket) return; try {receive(JSON.parse(event.data));} catch (error) {state.lastError = error.message; state.connected = false; paint(); socket.close();}};
  socket.onclose = () => {if (generation !== state.generation || state.ws !== socket) return; state.connected = false; paint(); scheduleReconnect(generation);};
  socket.onerror = () => {if (state.ws === socket) {state.connected = false; paint();}};
}
async function connectGateway(quiet = false) {
  if (!state.backendUrl) {setupDialog(); return;}
  const generation = ++state.generation; closeTransport(); state.connecting = true;
  try {
    const response = await fetch(`${state.backendUrl}/api/status`,{cache:'no-store',signal:AbortSignal.timeout(4500)}); if (!response.ok) throw new Error('Local gateway unavailable.'); const raw = await response.json(); if (generation !== state.generation) return;
    receive(raw,true); openSocket(generation); refreshEvents(generation); if (!quiet) toast('Connected to the local gateway.');
  } catch (error) {if (generation !== state.generation) return; state.connected = false; state.lastError = error.message; paint(); scheduleReconnect(generation); if (!quiet) toast(error.message);}
  finally {if (generation === state.generation) state.connecting = false;}
}
function exportEvents() {
  if (!state.events.length) {toast('No events to export yet.'); return;}
  const cell = value => {let text = String(value ?? ''); if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`; return `"${text.replaceAll('"','""')}"`;};
  const rows = [['timestamp','type','severity','title','detail','acknowledged'],...state.events.map(e => [e.timestamp,e.type,e.severity,e.title,e.detail,e.acknowledged])];
  const url = URL.createObjectURL(new Blob([rows.map(row => row.map(cell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'})); const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'auraguard-events.csv'; document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url),2000); toast('Event history exported.');
}
document.addEventListener('click',event => {
  const nav = event.target.closest('[data-view]'); if (nav) {event.preventDefault(); navigate(nav.dataset.view); return;}
  const filter = event.target.closest('[data-filter]'); if (filter) {state.filter = filter.dataset.filter; document.querySelectorAll('[data-filter]').forEach(button => {const active = button.dataset.filter === state.filter; button.classList.toggle('active',active); button.setAttribute('aria-pressed',active);}); paintHistory(); return;}
  const action = event.target.closest('[data-action]'); if (!action || action.disabled) return;
  switch (action.dataset.action) {case 'setup': setupDialog(); break; case 'close-dialog': $('dialog').close(); break; case 'theme': switchTheme(); break; case 'sound': state.browserSound = !state.browserSound; action.setAttribute('aria-checked',state.browserSound); if (state.browserSound) beep(); break; case 'export': exportEvents(); break; case 'reconnect': connectGateway(); break;}
});
document.addEventListener('input',event => {if (event.target.id === 'event-search') {state.search = event.target.value; paintHistory();}});
document.addEventListener('submit',event => {if (event.target.id !== 'preferences-form') return; event.preventDefault(); preferences.room = $('room-name').value.trim() || 'Baby’s room'; preferences.hour12 = $('time-format').value === 'true'; savePreferences(); state.eventsFingerprint = ''; paint(); toast('Preferences saved.');});
window.addEventListener('hashchange',() => {const view = location.hash.slice(1); if (view !== state.view) navigate(view);});
document.addEventListener('visibilitychange',() => {if (!document.hidden) {paint(); if (state.backendUrl && !state.connected && !state.connecting) connectGateway(true);}});
document.documentElement.dataset.theme = preferences.theme; renderShell();
setInterval(() => {if (state.connected && Date.now() - state.receivedAt >= 6000) {state.connected = false; if (state.ws) state.ws.close();} paint();},1000);
const localHost = /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname) || /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(location.hostname) || location.hostname.endsWith('.local');
if (localHost && location.hostname !== 'terminal.local') {state.backendUrl = location.origin; connectGateway(true);}
