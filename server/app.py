"""Local Bluetooth serial gateway and web server.

Run from the project directory:
    python server/app.py --port COM5
    python server/app.py --port /dev/ttyUSB0

The cloud preview cannot open your Bluetooth adapter. This process runs on the
computer connected to the Arduino base station and serves the same dashboard.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager, suppress
import csv
from dataclasses import dataclass
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from typing import Literal

try:
    from .state import MAX_LINE_BYTES, PROTOCOLS, Monitor, Store
    from .docs_module import register_docs_routes
except ImportError:
    from state import MAX_LINE_BYTES, PROTOCOLS, Monitor, Store
    from docs_module import register_docs_routes


HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
PROJECT_FILES = (
    "README.md",
    "docs/PROTOCOL.md",
    "docs/BABY_BLE_V5.md",
    "docs/LAB_SETUP.md",
    "dist/index.html",
    "dist/style.css",
    "dist/app.js",
    "dist/receiver-profile.js",
    "dist/favicon.svg",
    "dist/assets/manrope-latin.woff2",
    "dist/assets/OFL-Manrope.txt",
    "server/app.py",
    "server/state.py",
    "server/docs_module.py",
    "server/docs_static/docs.html",
    "server/docs_static/docs.css",
    "server/docs_static/docs.js",
    "server/docs_static/docs-admin.html",
    "server/docs_static/docs-admin.js",
    "server/test_docs.py",
    "server/requirements.txt",
    "server/requirements-test.txt",
    "server/test_gateway.py",
    "server/test_receiver_ui.cjs",
    "firmware/README.md",
    "firmware/esp32_baby_unit_ble_v5/esp32_baby_unit_ble_v5.ino",
    "firmware/uno_room_receiver_cry/uno_room_receiver_cry.ino",
    "firmware/wearable/wearable.ino",
    "firmware/wearable/fall_detector.h",
    "firmware/base_station/base_station.ino",
    "firmware/base_station/protocol.h",
    "firmware/tests/test_logic.cpp",
)


def approved_cached_archive(path: Path) -> bool:
    """Only reuse a generated download that contains the explicit source list."""
    if path.is_symlink() or not path.is_file():
        return False
    try:
        with ZipFile(path) as archive:
            names = []
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                name = entry.filename
                if "\\" in name or name.startswith("/") or ".." in name.split("/"):
                    return False
                if name not in PROJECT_FILES:
                    # A distributable may use one enclosing project directory.
                    parts = name.split("/", 1)
                    if len(parts) != 2 or not parts[0] or parts[1] not in PROJECT_FILES:
                        return False
                    name = parts[1]
                names.append(name)
            return set(names) == set(PROJECT_FILES) and len(names) == len(PROJECT_FILES)
    except (BadZipFile, OSError):
        return False


def project_archive() -> bytes:
    """Build from known source paths only, never from a recursive directory walk."""
    output = BytesIO()
    root = PROJECT_ROOT.resolve()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for relative in PROJECT_FILES:
            path = root / relative
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
                continue
            archive.write(path, arcname=relative)
    return output.getvalue()


@dataclass
class Settings:
    port: str | None = None
    baud: int = 9600
    database: Path | str | None = None
    static_dir: Path = HERE.parent / "dist"
    protocol: str = "uno-room-v1"
    docs_config: Path | None = None

    def __post_init__(self):
        if self.protocol not in PROTOCOLS:
            raise ValueError("unsupported device protocol")

    @property
    def db_path(self) -> Path | str:
        return self.database if self.database is not None else HERE / "data" / f"auraguard-{self.protocol}-live.sqlite3"


class LineFramer:
    """Bounded newline framing; timed-out partial reads are retained."""

    def __init__(self):
        self.buffer = bytearray()
        self.discarding = False
        self.dropped = 0

    def feed(self, data: bytes) -> list[bytes]:
        lines = []
        for value in data:
            if value == 10:
                if not self.discarding and self.buffer:
                    lines.append(bytes(self.buffer).removesuffix(b"\r"))
                self.buffer.clear()
                self.discarding = False
            elif not self.discarding:
                self.buffer.append(value)
                if len(self.buffer) > MAX_LINE_BYTES:
                    self.buffer.clear()
                    self.discarding = True
                    self.dropped += 1
        return lines


class SerialTransport:
    def __init__(self, monitor: Monitor, port: str, baud: int):
        self.monitor = monitor
        self.port_name = port
        self.baud = baud
        self.serial = None
        self.write_lock = asyncio.Lock()

    async def run(self):
        import serial

        delay = 1.0
        while True:
            client = None
            try:
                client = await asyncio.to_thread(
                    serial.Serial, self.port_name, self.baud,
                    timeout=0.2, write_timeout=1.0,
                )
                self.serial = client
                self.monitor.set_serial(True)
                framing = LineFramer()
                previous_drops = 0
                delay = 1.0
                while True:
                    data = await asyncio.to_thread(client.read, 1024)
                    if data:
                        for line in framing.feed(data):
                            self.monitor.ingest_line(line)
                        if framing.dropped > previous_drops:
                            self.monitor.invalid_packets += framing.dropped - previous_drops
                            self.monitor.last_error = "Ignored oversized serial frame."
                            previous_drops = framing.dropped
                    self.monitor.tick()
            except asyncio.CancelledError:
                raise
            except (serial.SerialException, OSError, ValueError) as exc:
                self.monitor.set_serial(False, f"Serial connection unavailable: {exc}")
            finally:
                self.serial = None
                if client is not None:
                    with suppress(Exception):
                        await asyncio.to_thread(client.close)
                self.monitor.set_serial(False)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 15.0)

    async def send(self, command: dict):
        if not self.monitor.hardware_controls:
            raise RuntimeError(f"No outbound command protocol for {self.monitor.protocol}.")
        async with self.write_lock:
            client = self.serial
            if client is None or not client.is_open:
                raise ConnectionError("Serial port is not connected.")
            payload = (json.dumps(command, separators=(",", ":")) + "\n").encode("ascii")
            count = await asyncio.to_thread(client.write, payload)
            if count != len(payload):
                raise ConnectionError("Serial command could not be written completely.")


class ControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["arm", "disarm", "acknowledge"]


def origin_allowed(origin: str | None, host: str | None, scheme: str) -> bool:
    if origin is None:
        return True  # Local non-browser clients may omit Origin.
    parsed = urlsplit(origin)
    expected_scheme = "https" if scheme in {"https", "wss"} else "http"
    return parsed.scheme == expected_scheme and parsed.netloc == host and not parsed.path and not parsed.query and not parsed.fragment


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = Store(settings.db_path)
        monitor = Monitor(store, port=settings.port, protocol=settings.protocol)
        app.state.monitor = monitor
        app.state.transport = SerialTransport(monitor, settings.port, settings.baud) if settings.port else None
        app.state.ws_clients = 0

        async def watchdog():
            while True:
                monitor.tick()
                await asyncio.sleep(0.25)

        tasks = [asyncio.create_task(watchdog())]
        if app.state.transport:
            tasks.append(asyncio.create_task(app.state.transport.run()))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            store.close()

    # docs_url/redoc_url are disabled: /docs belongs to the live documentation module.
    app = FastAPI(title="AuraGuard local gateway", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/api/status")
    async def status(request: Request):
        return request.app.state.monitor.snapshot()

    @app.get("/api/history")
    async def history(request: Request, limit: int = Query(default=120, ge=1, le=86400)):
        monitor = request.app.state.monitor
        return [] if monitor.event_only else monitor.store.history(limit)

    @app.get("/api/events")
    async def events(request: Request, limit: int = Query(default=100, ge=1, le=2000)):
        return request.app.state.monitor.store.events(limit)

    @app.get("/api/export.csv")
    async def export(request: Request, limit: int = Query(default=86400, ge=1, le=86400)):
        monitor = request.app.state.monitor
        output = StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["timestamp_utc", "acceleration_g", "sound_level_relative_0_100", "mode"])
        for row in ([] if monitor.event_only else monitor.store.history(limit)):
            writer.writerow([row["timestamp"], row["acceleration"], row["sound_level"], monitor.mode])
        return Response(
            output.getvalue(), media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="auraguard-{monitor.mode}.csv"', "Cache-Control": "no-store"},
        )

    @app.post("/api/control", status_code=202)
    async def control(command: ControlRequest, request: Request):
        if not origin_allowed(request.headers.get("origin"), request.headers.get("host"), request.url.scheme):
            raise HTTPException(403, "Open the dashboard from this local server before controlling the base station.")
        monitor = request.app.state.monitor
        if not monitor.hardware_controls:
            raise HTTPException(409, f"Hardware controls are unavailable for {monitor.protocol}. Use the receiver's physical ACK and ARM buttons.")
        if request.app.state.transport is None:
            raise HTTPException(503, "No serial port is configured. Restart with --port COM5 or your device's port.")
        try:
            wire = monitor.prepare_command(command.action)
        except ConnectionError as exc:
            raise HTTPException(503, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        try:
            await request.app.state.transport.send(wire)
        except Exception as exc:
            monitor.finish_command(wire["id"], "failed", "The command could not be written to the base station.")
            raise HTTPException(503, "Serial write failed; hardware state has not been changed by the dashboard.") from exc
        return {"id": wire["id"], "action": command.action, "status": "pending", "message": "Awaiting hardware confirmation."}

    @app.get("/api/control/{command_id}")
    async def control_status(command_id: str, request: Request):
        result = request.app.state.monitor.command_result(command_id)
        if result is None:
            raise HTTPException(404, "Command not found in this server session.")
        return result

    @app.websocket("/ws")
    async def stream(websocket: WebSocket):
        if not origin_allowed(websocket.headers.get("origin"), websocket.headers.get("host"), websocket.url.scheme):
            await websocket.close(code=1008)
            return
        if websocket.app.state.ws_clients >= 20:
            await websocket.close(code=1013)
            return
        await websocket.accept()
        websocket.app.state.ws_clients += 1
        try:
            while True:
                await asyncio.wait_for(websocket.send_json(websocket.app.state.monitor.snapshot()), timeout=5.0)
                await asyncio.sleep(1.0)
        except (WebSocketDisconnect, RuntimeError, TimeoutError):
            pass
        finally:
            websocket.app.state.ws_clients -= 1
            with suppress(Exception):
                await websocket.close()

    @app.get("/healthz")
    async def health():
        return {"ok": True, "mode": "live", "protocol": settings.protocol}

    @app.get("/downloads/auraguard-project.zip")
    async def download_project():
        cached = settings.static_dir / "downloads" / "auraguard-project.zip"
        if approved_cached_archive(cached):
            return FileResponse(
                cached, media_type="application/zip", filename="auraguard-project.zip",
                headers={"Cache-Control": "no-store"},
            )
        return Response(
            project_archive(), media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="auraguard-project.zip"',
                "Cache-Control": "no-store",
            },
        )

    register_docs_routes(app, settings)

    # API routes come before the static mount so /api and /ws retain their routes.
    if settings.static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(settings.static_dir), html=True), name="dashboard")
    else:
        @app.get("/")
        async def no_dashboard():
            return {"message": "Place the dashboard files in ../dist, then restart the gateway.", "status_url": "/api/status"}

    return app


app = create_app(Settings(port=os.getenv("AURAGUARD_PORT"), protocol=os.getenv("AURAGUARD_PROTOCOL", "uno-room-v1")))


def main():
    parser = argparse.ArgumentParser(description="Serve the AuraGuard dashboard and receive Bluetooth base-station telemetry.")
    parser.add_argument("--port", help="Receiver USB serial port, such as COM5 or /dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=9600, help="Receiver USB serial baud (default: 9600)")
    parser.add_argument("--protocol", choices=sorted(PROTOCOLS), default="uno-room-v1", help="Serial contract (default: uno-room-v1 USB receiver logs)")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind address (default: 127.0.0.1)")
    parser.add_argument("--http-port", type=int, default=8000, help="HTTP port (default: 8000)")
    parser.add_argument("--db", type=Path, help="Optional local SQLite path; protocols have separate defaults")
    parser.add_argument("--list-ports", action="store_true", help="List OS serial ports and exit")
    args = parser.parse_args()
    if args.list_ports:
        from serial.tools import list_ports
        ports = list(list_ports.comports())
        for port in ports:
            print(f"{port.device}\t{port.description}")
        if not ports:
            print("No serial ports found. Connect the base station and try again.")
        return
    if args.baud <= 0 or not 1 <= args.http_port <= 65535:
        parser.error("baud must be positive and HTTP port must be between 1 and 65535")
    import uvicorn
    config = Settings(port=args.port, baud=args.baud, database=args.db, protocol=args.protocol)
    print("AuraGuard: LIVE — waiting for hardware")
    print(f"Protocol: {args.protocol}")
    print("Docs module: /docs (public) and /docs/admin (token in server/data/docs-config.json)")
    if args.protocol == "baby-ble-v5":
        print("Read-only event mode: the room unit must forward exact OK / FALL / CRY lines over USB serial.")
    print(f"Open http://{args.host}:{args.http_port}")
    uvicorn.run(create_app(config), host=args.host, port=args.http_port, workers=1)


if __name__ == "__main__":
    main()
