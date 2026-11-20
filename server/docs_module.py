"""Live /docs module: public pitch deck + technical docs + admin panel.

Serves a visibility-gated public documentation page whose content is assembled
from the running gateway (routes, receiver state, event counts, AI model
metadata) plus an admin-editable pitch/team configuration stored on disk.

Visibility rules (verified in server/test_docs.py):
  * enabled == False                       -> /docs and /api/docs return 404
  * visible_from in the future             -> 404
  * visible_until in the past              -> 404
  * inside the window (or no window set)   -> public

Admin endpoints require the X-Admin-Token header matching the token in the
on-disk config (server/data/docs-config.json by default, git-ignored).
"""

from __future__ import annotations

from datetime import datetime, timezone
import hmac
import json
import os
from pathlib import Path
import re
import secrets
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import UploadFile


HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "docs_static"
DEFAULT_CONFIG_PATH = HERE / "data" / "docs-config.json"
IMAGE_DIR = HERE / "data" / "docs-images"
PITCH_VIDEO = HERE.parent / "docs" / "pitch" / "auraguard-pitch.mp4"
AI_WEIGHTS_DIR = HERE / "ai" / "weights"
TEAM_IMAGE_SIZE = 256
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_TEXT = 4000
MAX_FEATURES = 12
MAX_TEAM = 12

DOC_LIBRARY = (
    ("docs/AI.md", "AI layer: models, features, training, verification"),
    ("docs/PROTOCOL.md", "Exact Uno USB protocol and API state rules"),
    ("docs/BABY_BLE_V5.md", "Baby-unit BLE transport and detector behavior"),
    ("docs/LAB_SETUP.md", "Lab setup, expected logs, troubleshooting"),
    ("docs/pitch/PITCH.md", "Three-point pitch narrative"),
    ("docs/pitch/DATA_LIFECYCLE.md", "Data lifecycle submission answers"),
    ("README.md", "Project overview and run guide"),
)

TECH_STACK = (
    ("ESP32 baby unit", "On-device feature extraction + softmax inference (C, no TFLite dependency)"),
    ("Arduino Uno receiver", "Physical ACK / ARM controls, LEDs, buzzer; text-line USB logs at 9600 baud"),
    ("Python gateway", "FastAPI + WebSocket, pySerial, Pydantic validation, SQLite persistence"),
    ("Browser dashboard", "Vanilla JS, self-hosted Manrope, no remote requests"),
    ("AI training pipeline", "Pure-stdlib Python: simulator, features, softmax trainer, host C cross-check"),
)

DEFAULT_PITCH = {
    "product_name": "AuraGuard",
    "tagline": "A baby monitor that means what it says: on-device AI tells crying from noise, falls from play, and warns before the Bluetooth link drops.",
    "problem": "Cheap baby monitors cry wolf. Any loud sound becomes \u201ccrying\u201d \u2014 a knock, the TV, a fan. Any jolt becomes a \u201cfall\u201d \u2014 including a baby who is just running around. And you only learn the baby wandered too far when the link is already dead. The result is alarm fatigue: parents stop trusting the monitor precisely when it matters.",
    "users": "Parents and caregivers of infants (0\u201324 months) running this DIY ESP32 + Arduino room monitor in a nursery, who need three answers they can trust \u2014 is that sound really my baby, was that really a fall, is my baby still in range \u2014 privately, on-device, with no cloud and no subscription.",
    "approach": "Not a wrapper around a cloud API: the intelligence is the product and runs where the data is born, on the ESP32 itself. Physics-based features (Goertzel band shares around the cry fundamental, free-fall fraction, gyro energy, post-impact stillness) feed tiny softmax classifiers trained offline in pure-stdlib Python, exported as a C header. A safety-first fusion layer means a model misfire can never silence a real fall pattern.",
    "features": [
        "Cry classifier: 9 audio features from 2 kHz bursts, softmax inference on-device; 99% held-out accuracy against knocks, TV hiss, fan hum, and appliance tones.",
        "Fall vs play: acceleration + gyroscope motion classifier; 100% held-out accuracy with running-as-fall at or below 2%, plus an AI veto for play-like triggers.",
        "WANDER pre-warning: BLE RSSI range zones raise a warning 8+ seconds before the receiver's link-loss alarm would fire.",
        "Safety-first fusion: one alert state, FALL > SENSOR_FAULT > WANDER > CRY; the proven temporal fall detector can never be silenced by a classifier misfire.",
        "Private by design: inference on the ESP32, a gateway bound to 127.0.0.1, no cloud, no account, no subscription.",
        "Honest telemetry: disconnected hardware shows \u201cunknown\u201d, never a fabricated reading; physical ACK / ARM buttons keep working without the browser.",
    ],
    "repo_url": "https://github.com/Sayed-47/auraguard",
    "video_url": "",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_moment(value: str | None) -> datetime | None:
    if value is None or value == "":
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid ISO 8601 datetime: {value!r}") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def visibility_state(config: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    if not config.get("enabled", False):
        return {"visible": False, "reason": "disabled"}
    start = parse_moment(config.get("visible_from"))
    end = parse_moment(config.get("visible_until"))
    if start and now < start:
        return {"visible": False, "reason": "not_yet_open"}
    if end and now > end:
        return {"visible": False, "reason": "closed"}
    return {"visible": True, "reason": "open"}


class DocsConfigStore:
    """JSON-file persistence with atomic writes; lives in the git-ignored data dir."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._config = self._load()

    def _load(self) -> dict[str, Any]:
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
        else:
            data = {}
        config = {
            "enabled": bool(data.get("enabled", True)),
            "visible_from": data.get("visible_from") or None,
            "visible_until": data.get("visible_until") or None,
            "admin_token": data.get("admin_token") or secrets.token_hex(20),
            "pitch": {**DEFAULT_PITCH, **(data.get("pitch") or {})},
            "team": data.get("team") if isinstance(data.get("team"), list) else [],
        }
        # Validate persisted schedule eagerly so a corrupt file cannot 500 every request.
        parse_moment(config["visible_from"])
        parse_moment(config["visible_until"])
        if not self.path.is_file() or data.get("admin_token") != config["admin_token"]:
            self._write(config)
        return config

    def _write(self, config: dict[str, Any]) -> None:
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temp, self.path)

    @property
    def config(self) -> dict[str, Any]:
        return self._config

    def update(self, changes: dict[str, Any]) -> dict[str, Any]:
        merged = {**self._config, **changes}
        self._write(merged)
        self._config = merged
        return self._config


class PitchUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_name: str | None = Field(default=None, max_length=120)
    tagline: str | None = Field(default=None, max_length=400)
    problem: str | None = Field(default=None, max_length=MAX_TEXT)
    users: str | None = Field(default=None, max_length=MAX_TEXT)
    approach: str | None = Field(default=None, max_length=MAX_TEXT)
    features: list[str] | None = None
    repo_url: str | None = Field(default=None, max_length=400)
    video_url: str | None = Field(default=None, max_length=400)


class DocsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    visible_from: str | None = None
    visible_until: str | None = None
    pitch: PitchUpdate | None = None


class TeamMemberIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(default="", max_length=160)
    email: str = Field(default="", max_length=254)


def clean_member(member: TeamMemberIn) -> dict[str, Any]:
    name = member.name.strip()
    role = member.role.strip()
    email = member.email.strip()
    if not name:
        raise HTTPException(422, "Team member name cannot be blank.")
    if email and (email.count("@") != 1 or " " in email):
        raise HTTPException(422, "Team member email must look like an email address.")
    return {"name": name, "role": role, "email": email}


def ai_model_cards() -> list[dict[str, Any]]:
    """Live metadata from the shipped weight files, never a hard-coded copy."""
    cards = []
    for path in sorted(AI_WEIGHTS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        cards.append({
            "id": path.stem,
            "kind": data.get("kind"),
            "classes": data.get("class_names"),
            "n_classes": data.get("n_classes"),
            "n_features": data.get("n_features"),
            "feature_names": data.get("feature_names"),
            "version": data.get("version"),
        })
    return cards


def api_listing(app: FastAPI) -> list[dict[str, Any]]:
    """The server's real route table, so the API reference can never go stale."""
    rows = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not (route.path.startswith("/api") or route.path in {"/healthz", "/ws", "/docs", "/docs/admin"}):
            continue
        methods = sorted(method for method in (route.methods or set()) if method not in {"HEAD", "OPTIONS"})
        rows.append({"path": route.path, "methods": methods, "summary": route.summary or route.name})
    rows.sort(key=lambda row: (row["path"], row["methods"]))
    return rows


def live_payload(app: FastAPI, settings: Any) -> dict[str, Any]:
    monitor = app.state.monitor
    snapshot = monitor.snapshot()
    events = snapshot.get("events") or []
    by_type: dict[str, int] = {}
    for event in events:
        by_type[event["type"]] = by_type.get(event["type"], 0) + 1
    receiver = snapshot.get("receiver")
    return {
        "generated_at": snapshot["timestamp"],
        "protocol": snapshot["protocol"],
        "session_started_at": snapshot["session_started_at"],
        "connection": {
            "status": snapshot["connection"]["status"],
            "serial": snapshot["connection"]["serial"],
            "port": snapshot["connection"]["port"],
        },
        "receiver": {
            "status": receiver["status"],
            "armed": receiver["armed"],
            "fall_active": receiver["fall_active"],
            "cry_active": receiver["cry_active"],
            "wander_active": receiver["wander_active"],
            "link_lost": receiver["link_lost"],
            "counters": receiver["counters"],
        } if receiver else None,
        "event_total": len(events),
        "event_counts_by_type": by_type,
        "recent_events": events[:6],
        "diagnostics": snapshot["diagnostics"],
        "capabilities": snapshot["capabilities"],
        "api_routes": api_listing(app),
        "ai_models": ai_model_cards(),
        "docs_library": [{"path": path, "title": title, "url": f"https://github.com/Sayed-47/auraguard/blob/main/{path}"} for path, title in DOC_LIBRARY if (HERE.parent / path).is_file()],
        "tech_stack": [{"layer": layer, "detail": detail} for layer, detail in TECH_STACK],
        "server": {"title": app.title, "version": app.version},
    }


def public_team(config: dict[str, Any]) -> list[dict[str, Any]]:
    members = []
    for member in config.get("team", []):
        members.append({
            "id": member["id"],
            "name": member["name"],
            "role": member.get("role", ""),
            "email": member.get("email", ""),
            "image_url": f"/api/docs/team-image/{member['id']}?v={member.get('image_version', 0)}" if member.get("has_image") else None,
        })
    return members


def register_docs_routes(app: FastAPI, settings: Any) -> None:
    config_path = Path(getattr(settings, "docs_config", None) or DEFAULT_CONFIG_PATH)
    store = DocsConfigStore(config_path)
    image_dir = config_path.parent / "docs-images"
    image_dir.mkdir(parents=True, exist_ok=True)
    app.state.docs_store = store

    def require_visible(request: Request) -> dict[str, Any]:
        state = visibility_state(store.config)
        if not state["visible"]:
            raise HTTPException(404, "The documentation page is not available.")
        return state

    def require_admin(request: Request) -> None:
        token = request.headers.get("x-admin-token", "")
        if not token or not hmac.compare_digest(token, store.config["admin_token"]):
            raise HTTPException(403, "A valid X-Admin-Token header is required.")

    def page(name: str) -> str:
        return (STATIC_DIR / name).read_text(encoding="utf-8")

    @app.get("/docs", response_class=HTMLResponse)
    async def docs_page(request: Request):
        require_visible(request)
        return HTMLResponse(page("docs.html"))

    @app.get("/docs/admin", response_class=HTMLResponse)
    async def docs_admin_page():
        # Always reachable: this page is how visibility gets switched back on.
        return HTMLResponse(page("docs-admin.html"))

    @app.get("/docs-assets/{name}")
    async def docs_asset(name: str):
        if name not in {"docs.css", "docs.js", "docs-admin.js"}:
            raise HTTPException(404, "Unknown docs asset.")
        media = "text/css" if name.endswith(".css") else "application/javascript"
        return HTMLResponse(page(name), media_type=media, headers={"Cache-Control": "no-store"})

    @app.get("/api/docs")
    async def docs_public(request: Request):
        require_visible(request)
        config = store.config
        pitch = dict(config["pitch"])
        if not pitch.get("video_url") and PITCH_VIDEO.is_file():
            pitch["video_url"] = "/api/docs/pitch-video"
        return {
            "pitch": pitch,
            "team": public_team(config),
            "visibility": {"enabled": config["enabled"], "visible_from": config["visible_from"], "visible_until": config["visible_until"]},
            "live": live_payload(app, settings),
        }

    @app.get("/api/docs/live")
    async def docs_live(request: Request):
        require_visible(request)
        return live_payload(app, settings)

    @app.get("/api/docs/pitch-video")
    async def docs_pitch_video(request: Request):
        require_visible(request)
        if not PITCH_VIDEO.is_file():
            raise HTTPException(404, "No pitch video is bundled with this build.")
        return FileResponse(PITCH_VIDEO, media_type="video/mp4", filename="auraguard-pitch.mp4")

    @app.get("/api/docs/team-image/{member_id}")
    async def docs_team_image(member_id: str, request: Request):
        require_visible(request)
        member = next((m for m in store.config["team"] if m["id"] == member_id), None)
        path = image_dir / f"{member_id}.png"
        if member is None or not member.get("has_image") or not path.is_file():
            raise HTTPException(404, "No image for this team member.")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/api/docs/admin")
    async def docs_admin_read(request: Request):
        require_admin(request)
        config = store.config
        state = visibility_state(config)
        return {
            "enabled": config["enabled"],
            "visible_from": config["visible_from"],
            "visible_until": config["visible_until"],
            "visible_now": state["visible"],
            "visibility_reason": state["reason"],
            "pitch": config["pitch"],
            "team": public_team(config),
        }

    @app.put("/api/docs/admin")
    async def docs_admin_update(update: DocsUpdate, request: Request):
        require_admin(request)
        changes: dict[str, Any] = {}
        if update.enabled is not None:
            changes["enabled"] = update.enabled
        for key in ("visible_from", "visible_until"):
            if key in update.model_fields_set:
                value = getattr(update, key)
                try:
                    parse_moment(value)
                except ValueError as exc:
                    raise HTTPException(422, str(exc)) from exc
                changes[key] = value or None
        if update.pitch is not None:
            pitch = dict(store.config["pitch"])
            for key, value in update.pitch.model_dump(exclude_unset=True).items():
                if key == "features":
                    if value is None:
                        continue
                    cleaned = [str(item).strip() for item in value if str(item).strip()][:MAX_FEATURES]
                    pitch["features"] = cleaned
                elif value is not None:
                    text = str(value).strip()
                    if key in {"repo_url", "video_url"} and text and not re.fullmatch(r"https?://[^\s]+|/[^\s]*", text):
                        raise HTTPException(422, f"{key} must be an http(s) URL or a local path.")
                    pitch[key] = text
            changes["pitch"] = pitch
        try:
            store.update(changes)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"ok": True, **visibility_state(store.config)}

    @app.post("/api/docs/admin/team", status_code=201)
    async def docs_team_add(member: TeamMemberIn, request: Request):
        require_admin(request)
        team = list(store.config["team"])
        if len(team) >= MAX_TEAM:
            raise HTTPException(409, f"Team is limited to {MAX_TEAM} members.")
        entry = {"id": "tm-" + uuid4().hex[:10], **clean_member(member), "has_image": False, "image_version": 0}
        team.append(entry)
        store.update({"team": team})
        return {"ok": True, "member": entry}

    @app.put("/api/docs/admin/team/{member_id}")
    async def docs_team_edit(member_id: str, member: TeamMemberIn, request: Request):
        require_admin(request)
        team = list(store.config["team"])
        entry = next((m for m in team if m["id"] == member_id), None)
        if entry is None:
            raise HTTPException(404, "Team member not found.")
        entry.update(clean_member(member))
        store.update({"team": team})
        return {"ok": True, "member": entry}

    @app.delete("/api/docs/admin/team/{member_id}")
    async def docs_team_delete(member_id: str, request: Request):
        require_admin(request)
        team = store.config["team"]
        remaining = [m for m in team if m["id"] != member_id]
        if len(remaining) == len(team):
            raise HTTPException(404, "Team member not found.")
        store.update({"team": remaining})
        image = image_dir / f"{member_id}.png"
        if image.is_file():
            image.unlink()
        return {"ok": True}

    @app.post("/api/docs/admin/team/{member_id}/image")
    async def docs_team_image_upload(member_id: str, request: Request):
        require_admin(request)
        team = list(store.config["team"])
        entry = next((m for m in team if m["id"] == member_id), None)
        if entry is None:
            raise HTTPException(404, "Team member not found.")
        form = await request.form()
        upload = form.get("image")
        if not isinstance(upload, UploadFile):
            raise HTTPException(422, "Send the image as multipart form field 'image'.")
        raw = await upload.read()
        if not raw:
            raise HTTPException(422, "The uploaded file is empty.")
        if len(raw) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "Team images are limited to 8 MB.")
        try:
            from PIL import Image
            from io import BytesIO
            source = Image.open(BytesIO(raw))
            source.load()
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(415, "The uploaded file is not a readable image.") from exc
        source = source.convert("RGB")
        width, height = source.size
        side = min(width, height)
        left, top = (width - side) // 2, (height - side) // 2
        square = source.crop((left, top, left + side, top + side)).resize((TEAM_IMAGE_SIZE, TEAM_IMAGE_SIZE), Image.LANCZOS)
        square.save(image_dir / f"{member_id}.png", format="PNG")
        entry["has_image"] = True
        entry["image_version"] = int(entry.get("image_version", 0)) + 1
        store.update({"team": team})
        return {"ok": True, "image_url": f"/api/docs/team-image/{member_id}?v={entry['image_version']}", "size": TEAM_IMAGE_SIZE}
