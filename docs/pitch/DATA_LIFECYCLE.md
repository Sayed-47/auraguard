# AuraGuard — Data Lifecycle & Engineering (submission answers)

## 1. Data Sources

**Select:** ✅ IoT / Sensor / Streaming · ✅ Synthetic / AI-generated Data

Specific sources:

- **MPU6050 IMU** (I²C @ 100 kHz): 3-axis acceleration (±8 g) + 3-axis gyroscope (±500 °/s), sampled at 50–200 Hz on the ESP32 baby unit.
- **Analog sound sensor** (GPIO34, ADC1): raw amplified microphone voltage, captured as 128-sample bursts at 2 kHz.
- **BLE link telemetry**: connection RSSI polled every 500 ms by the ESP32 (BLE central, GATT service `FFE0`/characteristic `FFE1`).
- **Arduino Uno room receiver**: newline-delimited status/event logs over USB serial at 9600 baud (`uno-room-v1` protocol).
- **Synthetic training data**: `server/ai/simulate.py` — a seeded physics simulator producing labeled motion windows (normal / play-running / fall with free-fall, impact, post-impact tilt) and audio windows (cry harmonics vs hiss / knock / steady tone / fan hum).

## 2. Acquisition Methods

**Select:** ✅ IoT/embedded streaming acquisition (custom) · ✅ Automated flows (async tasks, hardware timers)

- **On-device:** hardware-timed loops — 50 Hz motion ring buffer, 2 kHz audio bursts (loudness-gated so audio never starves fall detection), 500 ms RSSI polls, I²C burst reads with all-zero/fault rejection and automatic bus recovery.
- **Gateway:** `pyserial` + asyncio reader (`SerialTransport`) with bounded `LineFramer` (4096-byte cap, oversized-frame discard), exponential-backoff reconnect (1→15 s), and a 250 ms watchdog task that drives link-freshness state machines.
- No web scraping, MCP, OCR, or STT is used — audio intelligence is on-device feature extraction, not speech-to-text.

## 3. Parsing, Formats & Cleaning

**Formats handled:** ✅ newline text protocol (custom) · ✅ JSON · ✅ CSV · ✅ JSONL-style ND logs · ✅ Markdown · ✅ C header (model artifacts) · ✅ Audio (raw ADC streams)

- **Parsers:** custom grammar for the Uno's USB logs (exact strings + `ROOM_STATUS` regex), `json.loads` for the legacy `json-v1` telemetry profile, CSV via stdlib `csv` (exports, test vectors).
- **Cleaning / enrichment:** RSSI EMA smoothing (τ = 2.5 s) + 3 dB zone hysteresis to stop flapping; rejection of all-zero IMU frames (loose-wire signature); quantization of ADC bursts; population statistics, jerk, Goertzel band powers, tilt-angle computation as enrichment features.
- **Schema validation:** `validate_packet()` — strict bounded validation per field (ranges, integer/boolean distinctions, packet types); Pydantic models on the control API; contract tests (`server/test_receiver_ui.cjs` + 79 Python tests) pinning the parser grammar exactly.

## 4. Storage Targets

**Select:** ✅ Relational (SQLite, WAL mode)

- `server/state.py` `Store`: `history` (timestamp, acceleration, sound_level) and `events` (id, type, severity, title, detail, timestamp, acknowledged) tables.
- **Indexes:** `history_time`, `event_time`. **Retention:** rolling caps — 86,400 history rows, 2,000 events (auto-pruned). **Isolation:** one connection on the event-loop thread; WAL for concurrent reads.
- **Model artifacts:** JSON weight files (`server/ai/weights/*.json`) + generated C header compiled into firmware — versioned alongside code.

## 5. Visualization

**Select:** ✅ Custom DOM/SVG dashboard (vanilla JS, no framework) + ✅ Mermaid (docs)

- Real-time: WebSocket pushes a full snapshot every 1 s; the view layer (`dist/receiver-profile.js`) normalizes it into hero status, device cards, metric tiles, session counters.
- Event history: searchable/filterable timeline grouped by day with CSV export.
- **Accessibility:** semantic HTML, `aria-live` alert regions, `role="status"`, keyboard-focusable views, reduced-motion-friendly CSS, dark/light themes.
- Architecture/pipeline diagrams as Mermaid in `docs/` (renders natively on GitHub/DEV).
- Pitch assets: pure-PIL programmatic animation rendered to MP4 via ffmpeg (`docs/pitch/`).

## 6. Insights — AI, ML & Non-AI

**Select:** ✅ Classical ML (hand-rolled softmax regression, stdlib-only) · ✅ Anomaly Detection · ✅ Rule Engine / Heuristics (non-AI) · ✅ Statistical Analysis

- **Models:** (a) 3-class motion classifier — 11 physics features (free-fall fraction, jerk RMS, gyro energy, post-impact stillness, tilt change, periodicity) — 100% held-out accuracy on simulator data, running-misread-as-fall ≤ 2%; (b) binary cry classifier — 9 acoustic features (Goertzel band shares 78–250/266–531/547–984 Hz, envelope modulation/depth, zero-crossing, duty) — 99% held-out; (c) RSSI range model — EMA + hysteresis zones + 8 s sustained-far pre-alert.
- **Training:** pure-Python full-batch gradient descent with L2; reproducible seeded simulator; `python -m server.ai.train` exports JSON + C header in seconds.
- **Evaluation:** held-out seeds, confusion matrices, fall recall ≥ 95%, cry recall ≥ 85%, plus a host-compiled g++ harness that proves the firmware's C inference matches Python bit-for-bit (≤1e-3) on shared vectors.
- **Non-AI analytics:** the original impact→stillness fall gate remains as a safety fallback when the classifier is uncertain (fusion can veto, never silence); link-loss timers; receiver event counters; freshness/stale/offline state machines.
- **Delivery:** in-app dashboard events + hero status, physical buzzer/LED alarms on the Uno, `WANDER` BLE token, CSV export.

## 7. Pipelines & Orchestration

- **Edge pipeline (event-driven):** sample → ring buffers → feature windows → inference → fusion → BLE tokens; priorities and cooldowns managed by hardware-timed state machines.
- **Gateway pipeline:** asyncio serial reader → bounded framer → grammar parser → validated state monitor → SQLite + WebSocket broadcast; watchdog every 250 ms.
- **Offline training pipeline:** simulator → feature extraction → train → evaluate → export C header → host cross-check. No Airflow/cron needed — the trainer is an idempotent CLI run at development time.

## 8. Outbound — APIs & Distribution

- **REST:** `GET /api/status`, `GET /api/events?limit=`, `GET /api/history`, `GET /api/export.csv`, `GET /healthz`, `POST /api/control` + `GET /api/control/{id}` (reference profiles), `GET /downloads/auraguard-project.zip`.
- **Realtime:** `WS /ws` — 1 Hz snapshot stream, origin-checked, 20-client cap.
- **Exports:** CSV (events from the browser, history from the API).
- **Model distribution:** trained weights ship as a generated C header compiled into the ESP32 firmware — the edge device *is* the inference endpoint.
- **Auth/rate notes:** binds `127.0.0.1` by design (local-first); the Heroku deployment serves the public read-only demo (no hardware attached).

## 9. Open Source Stack

- **FastAPI + Uvicorn** — gateway HTTP/WebSocket server.
- **pyserial** — USB serial acquisition from the Uno.
- **SQLite (stdlib)** — WAL persistence for events/history.
- **Python standard library** — the entire ML stack: feature math (Goertzel, statistics), softmax training, simulator, exporters.
- **Pillow + ffmpeg** — programmatic pitch-video rendering.
- **Lucide** (ISC) — dashboard icon set; **Manrope** (OFL) — bundled UI font.
- **Arduino-ESP32 core / NimBLE** — BLE central firmware; **Arduino Uno** — room receiver.
- **Node.js (node:test)** — UI contract tests against real parser snapshots.

## 10. Quality, Governance & Observability

- **Data quality:** 79 Python tests (parser grammar, state machines, AI accuracy thresholds on fresh seeds), 12 Node contract tests, host-compiled C↔Python inference parity checks; bounded numeric validation everywhere; freshness SLAs — stale ≥ 3 s, offline ≥ 5–6 s; retention caps prune old rows.
- **Privacy & compliance:** privacy-by-architecture — all inference on the ESP32; no audio, motion, or baby data ever leaves the nursery; no accounts, no PII, no cloud; gateway binds localhost; README warns that screenshots/logs can identify a lab session. GDPR surface is effectively nil.
- **Lineage & observability:** every alert is traceable to a classifier probability or a deterministic gate (logged on-device at 115200 baud); gateway diagnostics expose `invalid_packets`, `last_error`, receiver counters (`fall_reports`, `cry_episodes`, `acknowledgments`, `wander_reports`), and I²C fault counts.
- **Cost & performance:** zero per-inference cost (edge ML, no API calls); µs-scale inference on-device; total cloud footprint is one basic Heroku dyno for the demo page.
- **Anything else:** simulator-first training with a documented path to retrain on real nursery captures; the AI layer is additive — the original threshold detector remains as a fall-back so a model failure degrades to the proven baseline, never to silence.

## Publish local environment to internet

**Select:** none — we deploy instead of tunnel. The local gateway intentionally binds `127.0.0.1` (baby data never leaves the room); the public demo is deployed to **Heroku** (`git push heroku main`, uvicorn on `$PORT`). If a live-hardware demo ever needs exposing, **Cloudflare Tunnel (cloudflared)** would be the pick — free, no port opening, keeps the gateway process unmodified.
