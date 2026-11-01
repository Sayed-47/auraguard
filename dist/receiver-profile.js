/* Presentation model for the supplied Arduino Uno receiver. No generated data. */
'use strict';

const ReceiverProfile = (() => {
  const timestamp = value => typeof value === 'string' && Number.isFinite(Date.parse(value)) ? value : null;
  const flag = value => typeof value === 'boolean' ? value : null;
  const count = value => Number.isSafeInteger(value) && value >= 0 ? value : 0;
  const text = (value, limit = 240) => typeof value === 'string' ? value.slice(0, limit) : '';

  function empty() {
    return {
      type: 'snapshot', mode: 'live', protocol: 'uno-room-v1', timestamp: null,
      connection: {serial: false, bluetooth: false, status: 'waiting', last_seen: null, base_last_seen: null, wearable_age_ms: null, port: null},
      receiver: {fresh: false, status: 'waiting', armed: null, fall_active: null, cry_active: null, link_lost: null, muted_until: null, mute_known: false, last_status_at: null, last_line: null, session_started_at: null, counters: {fall_reports: 0, cry_episodes: 0, acknowledgments: 0}},
      events: [], diagnostics: {last_error: null}
    };
  }

  function normalize(raw) {
    if (raw?.type !== 'snapshot' || raw.mode !== 'live') throw new Error('A live AuraGuard gateway is required.');
    if (raw.protocol !== 'uno-room-v1' || !raw.receiver || !raw.connection) throw new Error('Start the gateway with --protocol uno-room-v1.');
    const r = raw.receiver, c = raw.connection;
    return {
      type: 'snapshot', mode: 'live', protocol: 'uno-room-v1', timestamp: timestamp(raw.timestamp),
      connection: {
        serial: c.serial === true, bluetooth: c.bluetooth === true,
        status: ['waiting', 'connected', 'stale', 'offline'].includes(c.status) ? c.status : 'waiting',
        last_seen: timestamp(c.last_seen), base_last_seen: timestamp(c.base_last_seen),
        wearable_age_ms: typeof c.wearable_age_ms === 'number' && Number.isFinite(c.wearable_age_ms) && c.wearable_age_ms >= 0 ? c.wearable_age_ms : null,
        port: text(c.port, 160) || null
      },
      receiver: {
        fresh: r.fresh === true,
        status: ['waiting', 'connected', 'stale', 'offline'].includes(r.status) ? r.status : 'waiting',
        armed: flag(r.armed), fall_active: flag(r.fall_active), cry_active: flag(r.cry_active), link_lost: flag(r.link_lost),
        muted_until: timestamp(r.muted_until), mute_known: r.mute_known === true,
        last_status_at: timestamp(r.last_status_at), last_line: text(r.last_line, 512) || null,
        session_started_at: timestamp(r.session_started_at),
        counters: {fall_reports: count(r.counters?.fall_reports), cry_episodes: count(r.counters?.cry_episodes), acknowledgments: count(r.counters?.acknowledgments)}
      },
      events: cleanEvents(raw.events),
      diagnostics: {last_error: text(raw.diagnostics?.last_error) || null}
    };
  }

  function cleanEvents(events) {
    return Array.isArray(events) ? events.filter(e => e && typeof e.id === 'string' && typeof e.title === 'string' && timestamp(e.timestamp)).slice(0, 2000).map(e => ({
      id: text(e.id, 100), type: ['fall', 'cry', 'connection', 'system'].includes(e.type) ? e.type : 'system',
      title: text(e.title, 160), detail: text(e.detail, 600), timestamp: e.timestamp,
      severity: ['info', 'warning', 'critical'].includes(e.severity) ? e.severity : 'info', acknowledged: e.acknowledged === true
    })) : [];
  }

  function view(snapshot, connected, receivedAt, now = Date.now()) {
    const r = snapshot.receiver, c = snapshot.connection;
    const elapsed = receivedAt ? Math.max(0, now - receivedAt) : 0;
    const gateway = connected && receivedAt > 0 && elapsed < 6000;
    const baseAge = snapshot.timestamp && c.base_last_seen ? Math.max(0, Date.parse(snapshot.timestamp) - Date.parse(c.base_last_seen)) + elapsed : Infinity;
    const fresh = gateway && c.serial && r.fresh && baseAge < 5000;
    const age = c.wearable_age_ms === null ? null : c.wearable_age_ms + elapsed;
    const baby = fresh && c.bluetooth && c.status === 'connected' && age !== null && age < 6000;
    const clock = snapshot.timestamp ? Date.parse(snapshot.timestamp) + elapsed : now;
    const muted = fresh && r.mute_known ? (r.muted_until ? Math.max(0, Math.ceil((Date.parse(r.muted_until) - clock) / 1000)) : 0) : null;
    const armed = fresh ? r.armed : null, fall = fresh ? r.fall_active : null, cry = fresh ? r.cry_active : null;
    let status = 'waiting';
    if (!gateway && receivedAt) status = 'disconnected';
    else if (gateway && !fresh) status = c.serial && c.base_last_seen ? 'stale' : 'waiting';
    else if (fresh && armed === false) status = 'paused';
    else if (fresh && fall === true) status = 'fall';
    else if (fresh && (r.link_lost === true || c.status === 'offline' || (age !== null && age >= 6000))) status = 'offline';
    else if (fresh && (c.status === 'stale' || !baby)) status = c.status === 'waiting' ? 'pairing' : 'delayed';
    else if (fresh && cry === true) status = 'cry';
    else if (fresh && muted > 0) status = 'muted';
    else if (fresh) status = armed === true && fall === false && cry === false ? 'normal' : 'observing';
    return {gateway, fresh, baby, age: fresh ? age : null, armed, fall, cry, muted, status};
  }

  return Object.freeze({empty, normalize, cleanEvents, view});
})();

if (typeof module !== 'undefined' && module.exports) module.exports = ReceiverProfile;
