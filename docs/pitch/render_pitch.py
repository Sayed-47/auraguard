"""Render the AuraGuard pitch animation (auraguard-pitch.mp4).

Pure-PIL frame rendering + ffmpeg encode. No other dependencies.

Usage (from the repository root):
    python docs/pitch/render_pitch.py            # full render (~a few minutes)
    python docs/pitch/render_pitch.py --preview  # render one frame per scene for review

Output: docs/pitch/auraguard-pitch.mp4 (1920x1080, 30 fps).
"""

from __future__ import annotations

import argparse
import math
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
FPS = 30
HERE = Path(__file__).resolve().parent
FRAMES = HERE / "_frames"
OUT = HERE / "auraguard-pitch.mp4"

BG = (18, 18, 24)
CARD = (30, 30, 40)
CARD_EDGE = (62, 60, 74)
TEXT = (245, 244, 239)
MUTED = (150, 147, 160)
ACCENT = (224, 115, 79)
ACCENT_DEEP = (170, 86, 61)
GREEN = (88, 178, 128)
AMBER = (224, 164, 79)
RED = (224, 92, 92)
BLUE = (104, 156, 224)
PURPLE = (164, 122, 224)

FONTS = {
    "regular": "segoeui.ttf",
    "bold": "segoeuib.ttf",
    "semibold": "segoeuisl.ttf",
}
_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    key = (kind, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(str(Path(r"C:\Windows\Fonts") / FONTS[kind]), size)
    return _font_cache[key]


def ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def fade(t: float, start: float, dur: float = 0.5) -> float:
    return ease((t - start) / dur)


def text(d: ImageDraw.ImageDraw, xy, s: str, kind: str, size: int, fill=TEXT, anchor="la", alpha: float = 1.0):
    if alpha <= 0:
        return
    if alpha < 1.0:
        fill = tuple(int(c * alpha + BG[i] * (1 - alpha)) for i, c in enumerate(fill[:3]))
    d.text(xy, s, font=font(kind, size), fill=fill, anchor=anchor)


def card(d: ImageDraw.ImageDraw, box, radius=26, fill=CARD, edge=CARD_EDGE, width=2, alpha: float = 1.0):
    if alpha <= 0:
        return
    if alpha < 1.0:
        fill = tuple(int(c * alpha + BG[i] * (1 - alpha)) for i, c in enumerate(fill))
        edge = tuple(int(c * alpha + BG[i] * (1 - alpha)) for i, c in enumerate(edge))
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=edge, width=width)


def arrow(d: ImageDraw.ImageDraw, x0, y0, x1, y1, fill=MUTED, width=6, head=18):
    d.line([x0, y0, x1, y1], fill=fill, width=width)
    ang = math.atan2(y1 - y0, x1 - x0)
    for da in (math.radians(150), math.radians(-150)):
        d.line([x1, y1, x1 + head * math.cos(ang + da), y1 + head * math.sin(ang + da)], fill=fill, width=width)


def baby_icon(d: ImageDraw.ImageDraw, cx, cy, r, color, alpha: float = 1.0):
    if alpha <= 0:
        return
    c = tuple(int(v * alpha + BG[i] * (1 - alpha)) for i, v in enumerate(color))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=c, width=max(3, r // 8))
    d.arc([cx - r * 0.5, cy - r * 1.25, cx + r * 0.5, cy - r * 0.05], start=200, end=340, fill=c, width=max(3, r // 8))
    d.ellipse([cx - r * 0.45, cy - r * 0.2, cx - r * 0.25, cy], fill=c)
    d.ellipse([cx + r * 0.25, cy - r * 0.2, cx + r * 0.45, cy], fill=c)
    d.arc([cx - r * 0.35, cy + r * 0.15, cx + r * 0.35, cy + r * 0.6], start=20, end=160, fill=c, width=max(3, r // 8))


def speaker_icon(d: ImageDraw.ImageDraw, cx, cy, s, color, alpha: float = 1.0):
    if alpha <= 0:
        return
    c = tuple(int(v * alpha + BG[i] * (1 - alpha)) for i, v in enumerate(color))
    d.polygon([(cx - s, cy - s * 0.4), (cx - s * 0.35, cy - s * 0.4), (cx + s * 0.35, cy - s), (cx + s * 0.35, cy + s), (cx - s * 0.35, cy + s * 0.4), (cx - s, cy + s * 0.4)], outline=c, width=5)
    for k, rr in enumerate((0.55, 0.9)):
        d.arc([cx + s * 0.25 - s * rr, cy - s * rr, cx + s * 0.25 + s * rr, cy + s * rr], start=-55, end=55, fill=c, width=5)


def gyro_icon(d: ImageDraw.ImageDraw, cx, cy, s, color, alpha: float = 1.0):
    if alpha <= 0:
        return
    c = tuple(int(v * alpha + BG[i] * (1 - alpha)) for i, v in enumerate(color))
    d.ellipse([cx - s, cy - s, cx + s, cy + s], outline=c, width=5)
    d.ellipse([cx - s, cy - s * 0.45, cx + s, cy + s * 0.45], outline=c, width=4)
    d.ellipse([cx - s * 0.18, cy - s * 0.18, cx + s * 0.18, cy + s * 0.18], fill=c)


def rssi_icon(d: ImageDraw.ImageDraw, cx, cy, s, color, alpha: float = 1.0):
    if alpha <= 0:
        return
    c = tuple(int(v * alpha + BG[i] * (1 - alpha)) for i, v in enumerate(color))
    for k, rr in enumerate((0.4, 0.75, 1.1)):
        d.arc([cx - s * rr, cy - s * rr, cx + s * rr, cy + s * rr], start=-120, end=-60, fill=c, width=6)
    d.ellipse([cx - 7, cy - 2, cx + 7, cy + 12], fill=c)


def scene_frame() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG)
    return img, ImageDraw.Draw(img)


# ---------- scenes ----------

def scene_title(d, t, dur):
    a = fade(t, 0.2, 0.9)
    baby_icon(d, W // 2, H // 2 - 120, 64, ACCENT, a)
    text(d, (W // 2, H // 2 + 10), "AuraGuard", "bold", 120, TEXT, anchor="mm", alpha=a)
    text(d, (W // 2, H // 2 + 110), "AI-native baby monitoring", "semibold", 44, MUTED, anchor="mm", alpha=fade(t, 0.8, 0.8))
    text(d, (W // 2, H - 90), "input  →  on-device AI  →  alerts that mean something", "regular", 30, ACCENT, anchor="mm", alpha=fade(t, 1.4, 0.8))


def scene_problem(d, t, dur):
    text(d, (140, 130), "01 · THE PROBLEM & WHO FEELS IT", "bold", 34, ACCENT, alpha=fade(t, 0.1))
    text(d, (140, 210), "Cheap monitors cry wolf.", "bold", 74, TEXT, alpha=fade(t, 0.2))

    bullets = [
        ("Any loud sound is “crying”", "knocks, TV hiss, fans — all false alarms"),
        ("Any jolt is a “fall”", "even a baby who is just running around"),
        ("Out of range = too late", "you find out only when the link is dead"),
    ]
    y = 350
    for i, (head, sub) in enumerate(bullets):
        a = fade(t, 0.7 + i * 0.7)
        x = 140 + (1 - ease((t - 0.7 - i * 0.7) / 0.7)) * 60
        card(d, (x, y, 1120, y + 128), alpha=a)
        text(d, (x + 42, y + 34), "×", "bold", 52, RED, alpha=a)
        text(d, (x + 100, y + 30), head, "bold", 38, TEXT, alpha=a)
        text(d, (x + 100, y + 82), sub, "regular", 28, MUTED, alpha=a)
        y += 152

    text(d, (140, y + 24), "→  Alarm fatigue: parents stop trusting the monitor.", "semibold", 36, RED, alpha=fade(t, 2.9))

    a = fade(t, 3.6)
    card(d, (1220, 330, 1780, 830), alpha=a)
    text(d, (1256, 370), "THE USER", "bold", 28, ACCENT, alpha=a)
    baby_icon(d, 1500, 520, 58, TEXT, a)
    text(d, (1500, 640), "Parents & caregivers", "bold", 40, TEXT, anchor="mm", alpha=a)
    text(d, (1500, 700), "of infants 0–24 months", "regular", 30, MUTED, anchor="mm", alpha=a)
    for j, line in enumerate(["nursery-room monitor", "needs alerts they can trust", "private · on-device · no cloud"]):
        text(d, (1500, 770 + j * 44), line, "regular", 27, MUTED if j < 2 else GREEN, anchor="mm", alpha=fade(t, 3.9 + j * 0.3))


def scene_ai(d, t, dur):
    text(d, (140, 130), "02 · THE AI-NATIVE APPROACH", "bold", 34, ACCENT, alpha=fade(t, 0.1))
    text(d, (140, 210), "The AI runs where the data is born.", "bold", 68, TEXT, alpha=fade(t, 0.2))
    text(d, (140, 300), "Three small on-device models + fusion — no cloud, no subscription.", "regular", 34, MUTED, alpha=fade(t, 0.4))

    cards = [
        ("MOTION AI", "accel + gyroscope", "fall  vs  play/running", GREEN, gyro_icon),
        ("CRY AI", "sound sensor, 2 kHz", "baby cry  vs  noise", BLUE, speaker_icon),
        ("RANGE AI", "BLE link RSSI", "near / far + pre-warning", PURPLE, rssi_icon),
    ]
    x = 140
    for i, (name, sub, answers, color, icon_fn) in enumerate(cards):
        a = fade(t, 0.9 + i * 0.7)
        dx = (1 - ease((t - 0.9 - i * 0.7) / 0.7)) * 60
        card(d, (x + dx, 400, x + dx + 520, 700), alpha=a)
        icon_fn(d, x + dx + 86, 500, 44, color, a)
        text(d, (x + dx + 156, 448), name, "bold", 36, color, alpha=a)
        text(d, (x + dx + 156, 500), sub, "regular", 27, MUTED, alpha=a)
        text(d, (x + dx + 40, 596), "learns:", "regular", 26, MUTED, alpha=a)
        text(d, (x + dx + 40, 640), answers, "semibold", 30, TEXT, alpha=a)
        x += 580

    a = fade(t, 3.2)
    card(d, (140, 780, 1780, 940), alpha=a)
    text(d, (180, 820), "SENSOR FUSION", "bold", 28, ACCENT, alpha=a)
    text(d, (180, 870), "one alert state:", "regular", 30, MUTED, alpha=a)
    x = 560
    for i, (label, color) in enumerate([("FALL", RED), ("SENSOR FAULT", AMBER), ("WANDER", PURPLE), ("CRY", BLUE)]):
        aa = fade(t, 3.5 + i * 0.3)
        w = d.textlength(label, font=font("bold", 32)) + 56
        card(d, (x, 838, x + w, 900), radius=31, fill=tuple(int(c * 0.22 + BG[i2] * 0.78) for i2, c in enumerate(color)), edge=color, alpha=aa)
        text(d, (x + w / 2, 868), label, "bold", 32, color, anchor="mm", alpha=aa)
        x += w + 28
        if i < 3:
            text(d, (x - 14, 868), "›", "bold", 36, MUTED, anchor="mm", alpha=aa)


def draw_node(d, cx, cy, w, h, title, sub, color, alpha, pulse=0.0):
    grow = 1.0 + 0.05 * pulse
    ww, hh = w * grow, h * grow
    card(d, (cx - ww / 2, cy - hh / 2, cx + ww / 2, cy + hh / 2), alpha=alpha)
    text(d, (cx, cy - 18), title, "bold", 34, color, anchor="mm", alpha=alpha)
    text(d, (cx, cy + 28), sub, "regular", 25, MUTED, anchor="mm", alpha=alpha)


def scene_flow(d, t, dur):
    text(d, (140, 120), "03 · THE SYSTEM FLOW", "bold", 34, ACCENT, alpha=fade(t, 0.1))
    text(d, (140, 200), "Input  →  on-device AI  →  output.", "bold", 68, TEXT, alpha=fade(t, 0.2))

    inputs = [
        (480, speaker_icon, "Sound sensor", "2 kHz bursts", BLUE),
        (700, gyro_icon, "MPU6050", "accel + gyro", GREEN),
        (920, rssi_icon, "BLE link", "RSSI range", PURPLE),
    ]
    for i, (cy, icon_fn, name, sub, color) in enumerate(inputs):
        a = fade(t, 0.7 + i * 0.4)
        icon_fn(d, 240, cy, 40, color, a)
        draw_node(d, 460, cy, 330, 120, name, sub, color, a)

    ai_a = fade(t, 2.0)
    card(d, (820, 400, 1330, 1000), alpha=ai_a)
    text(d, (1075, 452), "ESP32 · ON-DEVICE AI", "bold", 30, ACCENT, anchor="mm", alpha=ai_a)
    stages = [("features", 560), ("classifiers", 700), ("fusion", 840)]
    for i, (label, cy) in enumerate(stages):
        a = fade(t, 2.3 + i * 0.4)
        card(d, (880, cy - 52, 1270, cy + 52), radius=20, fill=(36, 36, 50), edge=ACCENT_DEEP, alpha=a)
        text(d, (1075, cy), label, "semibold", 34, TEXT, anchor="mm", alpha=a)
        if i < 2:
            arrow(d, 1075, cy + 56, 1075, cy + 84, MUTED, 4, 10)

    outs = [("FALL", RED, 500), ("CRY", BLUE, 660), ("WANDER", PURPLE, 820)]
    for i, (label, color, cy) in enumerate(outs):
        a = fade(t, 3.6 + i * 0.35)
        draw_node(d, 1560, cy, 260, 96, label, "alert", color, a)
    text(d, (1560, 950), "Uno receiver → gateway → dashboard", "regular", 26, MUTED, anchor="mm", alpha=fade(t, 4.6))

    # animated packets: input -> AI, AI -> outputs
    for i, (cy, icon_fn, name, sub, color) in enumerate(inputs):
        period, offset = 1.6, i * 0.5
        phase = ((t - 2.0) / period + offset) % 1.0
        if t > 2.0:
            x = 625 + phase * (820 - 625)
            d.ellipse([x - 10, cy - 10, x + 10, cy + 10], fill=color)
    for i, (label, color, cy) in enumerate(outs):
        period, offset = 1.6, 0.25 + i * 0.5
        phase = ((t - 3.6) / period + offset) % 1.0
        if t > 3.6:
            x = 1330 + phase * (1430 - 1330)
            d.ellipse([x - 10, cy - 10, x + 10, cy + 10], fill=color)
    for cy in (480, 700, 920):
        arrow(d, 630, cy, 800, cy, (70, 68, 84), 4, 12)
    for label, color, cy in outs:
        arrow(d, 1336, cy, 1416, cy, (70, 68, 84), 4, 12)


def scene_outro(d, t, dur):
    a = fade(t, 0.2, 0.9)
    baby_icon(d, W // 2, H // 2 - 150, 56, ACCENT, a)
    text(d, (W // 2, H // 2 - 30), "AuraGuard", "bold", 96, TEXT, anchor="mm", alpha=a)
    text(d, (W // 2, H // 2 + 70), "raw sensors in  →  trustworthy alerts out", "semibold", 40, MUTED, anchor="mm", alpha=fade(t, 0.8))
    text(d, (W // 2, H // 2 + 160), "in milliseconds · entirely inside the nursery", "regular", 32, GREEN, anchor="mm", alpha=fade(t, 1.3))
    text(d, (W // 2, H - 100), "github.com/Sayed-47/auraguard", "regular", 28, MUTED, anchor="mm", alpha=fade(t, 1.8))


SCENES = [
    (scene_title, 3.4),
    (scene_problem, 11.5),
    (scene_ai, 10.5),
    (scene_flow, 14.5),
    (scene_outro, 4.0),
]


def render(preview: bool) -> None:
    total = sum(d for _, d in SCENES)
    total_frames = int(total * FPS)
    FRAMES.mkdir(exist_ok=True)
    if preview:
        for i, (scene, dur) in enumerate(SCENES):
            img, d = scene_frame()
            scene(d, dur * 0.75, dur)
            img.save(HERE / f"preview_scene{i}.png")
        print(f"wrote {len(SCENES)} preview frames to {HERE}")
        return
    frame_no = 0
    for scene, dur in SCENES:
        n = int(dur * FPS)
        for k in range(n):
            img, d = scene_frame()
            scene(d, k / FPS, dur)
            if k < 14:  # fade from black
                overlay = Image.new("RGB", (W, H), BG)
                img = Image.blend(overlay, img, ease(k / 14))
            img.save(FRAMES / f"frame_{frame_no:05d}.png")
            frame_no += 1
        if frame_no % 300 < FPS:
            print(f"{frame_no}/{total_frames} frames")
    subprocess.run([
        "ffmpeg", "-y", "-framerate", str(FPS), "-i", str(FRAMES / "frame_%05d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", str(OUT),
    ], check=True)
    shutil.rmtree(FRAMES)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    render(args.preview)
