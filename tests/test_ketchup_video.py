from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "skills" / "ketchup-video" / "scripts" / "render_ketchup.py"

sys.path.insert(0, str(SCRIPT_PATH.parent))
import render_ketchup


def _make_sample_png(path: Path, width: int = 160, height: int = 90, rgba: tuple[int, int, int, int] = (240, 80, 40, 255)) -> None:
    raw = bytearray((b"\x00" + bytes(rgba[:3]) * width) * height)
    path.write_bytes(render_ketchup.encode_png_rgb(width, height, raw, compress_level=1))


def _make_sample_rgba_png(path: Path, width: int = 120, height: int = 80) -> None:
    row = bytearray([0])
    for x in range(width):
        alpha = 255 if x < width // 2 else 128
        row.extend((40, 180, 240, alpha))
    raw = bytes(row) * height

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png_bytes = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b"")
    path.write_bytes(png_bytes)


def _ffprobe_json(mp4_path: Path) -> dict:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,width,height,pix_fmt,r_frame_rate",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(mp4_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def test_check_env_present() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--check-env"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["ok"] is True
    assert data["ffmpeg"]
    assert data["ffprobe"]
    assert data["encoders"] == {"libx264": True, "png": True}
    assert data["fallback"] is None
    assert data["error"] is None


def test_check_env_missing_ffmpeg(tmp_path: Path) -> None:
    clean_env = {k: v for k, v in os.environ.items() if k != "PATH"}
    clean_env["PATH"] = str(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--check-env"],
        capture_output=True,
        text=True,
        env=clean_env,
        check=False,
    )
    assert proc.returncode != 0
    assert "Traceback" not in proc.stdout
    assert "Traceback" not in proc.stderr
    data = json.loads(proc.stdout)
    assert data["ok"] is False
    assert data["ffmpeg"] is None
    assert data["fallback"] == "generative_ui"
    assert data["error"]


def test_word_diff_hold_math_and_screenshot_exclusion(tmp_path: Path) -> None:
    shot_path = tmp_path / "screen.png"
    _make_sample_png(shot_path)

    raw_spec = {
        "slides": [
            {
                "title": "Pipeline Overview",
                "labels": ["Step One", "Step Two"],
                "nodes": [
                    {"id": "a", "label": "Build Stage", "status": "done"},
                    {"id": "b", "label": "Verify Stage", "status": "running"},
                ],
                "edges": [{"from": "a", "to": "b", "label": "feeds"}],
                "screenshots": [{"path": str(shot_path), "caption": "ignored screenshot caption words"}],
                "subtitle": "First slide sets the initial baseline.",
            },
            {
                "title": "Pipeline Overview",
                "labels": ["Step One", "Step Two"],
                "nodes": [
                    {"id": "a", "label": "Build Stage", "status": "done"},
                    {"id": "b", "label": "Verify Stage", "status": "done"},
                ],
                "edges": [{"from": "a", "to": "b", "label": "feeds"}],
                "images": [str(shot_path)],
                "subtitle": "All checks pass.",
            },
            {
                "title": "Pipeline Overview Updated",
                "labels": ["Step One", "Step Two Changed", "Step Three"],
                "nodes": [
                    {"id": "a", "label": "Build Stage", "status": "done"},
                    {"id": "b", "label": "Verify Complete Now", "status": "done"},
                ],
                "edges": [{"from": "a", "to": "b", "label": "shipped"}],
                "subtitle": "Every updated label and subtitle adds reading time accurately here.",
            },
        ]
    }
    spec = render_ketchup.parse_spec(raw_spec, tmp_path)
    timings, total_duration = render_ketchup.compute_timings(spec)

    assert timings[0].added_words == 17
    assert timings[0].hold_seconds == 6.0

    assert timings[1].added_words == 3
    assert timings[1].hold_seconds == 2.0

    assert timings[2].added_words == 22
    assert timings[2].hold_seconds == 8.0

    assert total_duration == pytest.approx(6.0 + 2.0 + 8.0 + 2 * 0.3)
    assert timings[1].steady_start == pytest.approx(6.3)
    assert timings[1].steady_end == pytest.approx(8.3)
    assert timings[2].steady_start == pytest.approx(8.6)
    assert timings[2].steady_end == pytest.approx(16.6)


def test_subtitle_strip_isolation_and_wrapping(tmp_path: Path) -> None:
    base_slide_dict = {
        "title": "Isolation Check",
        "nodes": [{"id": "n1", "label": "Worker Ready", "status": "done"}],
        "subtitle": "",
    }
    ten_word_sub = "Ten clear words describe how this worker handles each task."
    twenty_five_word_sub = (
        "Twenty five words verify that longer subtitles wrap cleanly onto multiple rows inside the fixed "
        "bottom strip without touching or clipping against the slide diagram above."
    )
    overflow_sub = " ".join(["overflowword"] * 90)

    spec = render_ketchup.parse_spec(
        {
            "width": 1280,
            "height": 720,
            "strip_height": 96,
            "slides": [
                base_slide_dict,
                {**base_slide_dict, "subtitle": ten_word_sub},
                {**base_slide_dict, "subtitle": twenty_five_word_sub},
                {**base_slide_dict, "subtitle": overflow_sub},
            ],
        },
        tmp_path,
    )
    strip_y = spec.height - spec.strip_height
    row_bytes = 1 + spec.width * 3
    cache: dict = {}

    canvases_and_lines = [render_ketchup.render_slide_canvas(spec, slide, cache) for slide in spec.slides]
    baseline_slide_area = bytes(canvases_and_lines[0][0].raw[: strip_y * row_bytes])

    for idx, (canvas, lines) in enumerate(canvases_and_lines[1:], start=1):
        assert bytes(canvas.raw[: strip_y * row_bytes]) == baseline_slide_area, f"slide {idx} leaked above strip_y"
        assert lines, f"slide {idx} produced empty subtitle lines"
        strip_bytes = canvas.raw[(strip_y + 2) * row_bytes :]
        assert any(b != render_ketchup.BG_STRIP[i % 3] for i, b in enumerate(strip_bytes) if i % row_bytes != 0)

    assert len(canvases_and_lines[2][1]) >= 2
    assert canvases_and_lines[3][1][-1].endswith("...")


def test_render_end_to_end_three_and_five_slides(tmp_path: Path) -> None:
    rgba_shot = tmp_path / "shot.png"
    _make_sample_rgba_png(rgba_shot)

    spec_3_path = tmp_path / "slides3.json"
    spec_3_path.write_text(
        json.dumps(
            {
                "slides": [
                    {
                        "title": "Build Phase",
                        "nodes": [
                            {"id": "a", "label": "Compile", "status": "done"},
                            {"id": "b", "label": "Test", "status": "running"},
                        ],
                        "edges": [{"from": "a", "to": "b", "label": "next"}],
                        "screenshots": [{"path": str(rgba_shot)}],
                        "subtitle": "Compile succeeded and the test suite is running now.",
                    },
                    {
                        "title": "Build Phase",
                        "nodes": [
                            {"id": "a", "label": "Compile", "status": "done"},
                            {"id": "b", "label": "Test", "status": "done"},
                        ],
                        "edges": [{"from": "a", "to": "b", "label": "next"}],
                        "subtitle": "All unit checks passed with zero regressions.",
                    },
                    {
                        "title": "Ready",
                        "labels": ["PR Open", "CI Green"],
                        "subtitle": "Everything is verified and ready for review.",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    out_3 = tmp_path / "out3.mp4"
    sheet_3 = tmp_path / "sheet3.png"
    proc_3 = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--spec",
            str(spec_3_path),
            "--out",
            str(out_3),
            "--contact-sheet",
            str(sheet_3),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_3.returncode == 0, proc_3.stderr
    summary_3 = json.loads(proc_3.stdout)
    assert summary_3["ok"] is True
    assert len(summary_3["slides"]) == 3

    probe_3 = _ffprobe_json(out_3)
    stream_3 = probe_3["streams"][0]
    assert stream_3["codec_name"] == "h264"
    assert stream_3["width"] == 1280
    assert stream_3["height"] == 720
    assert stream_3["pix_fmt"] == "yuv420p"
    assert stream_3["r_frame_rate"] == "30/1"
    hold_sum_3 = sum(s["hold_seconds"] for s in summary_3["slides"])
    assert float(probe_3["format"]["duration"]) >= hold_sum_3

    sw, sh, srgba = render_ketchup.decode_png_rgba(sheet_3)
    assert sw > 0 and sh > 0
    assert len(srgba) == sw * sh * 4
    tile_h = sh // 2
    tile_w = sw // 2
    top_left_px = srgba[(tile_h // 2 * sw + tile_w // 2) * 4 : (tile_h // 2 * sw + tile_w // 2) * 4 + 4]
    top_right_px = srgba[(tile_h // 2 * sw + tile_w + tile_w // 2) * 4 : (tile_h // 2 * sw + tile_w + tile_w // 2) * 4 + 4]
    bot_left_px = srgba[((tile_h + tile_h // 2) * sw + tile_w // 2) * 4 : ((tile_h + tile_h // 2) * sw + tile_w // 2) * 4 + 4]
    assert len({top_left_px, top_right_px, bot_left_px}) >= 2

    spec_5_path = tmp_path / "slides5.json"
    spec_5_path.write_text(
        json.dumps(
            {
                "slides": [
                    {
                        "title": f"Stage {i + 1}",
                        "nodes": [
                            {"id": "s1", "label": "Spec", "status": "done"},
                            {"id": "s2", "label": f"Step {i + 1}", "status": "done" if i == 4 else "running"},
                        ],
                        "edges": [{"from": "s1", "to": "s2"}],
                        "subtitle": f"Slide {i + 1} shows steady progress across the five step pipeline.",
                    }
                    for i in range(5)
                ]
            }
        ),
        encoding="utf-8",
    )
    out_5 = tmp_path / "out5.mp4"
    sheet_5 = tmp_path / "sheet5.png"
    t0 = time.perf_counter()
    proc_5 = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--spec",
            str(spec_5_path),
            "--out",
            str(out_5),
            "--contact-sheet",
            str(sheet_5),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed = time.perf_counter() - t0
    assert proc_5.returncode == 0, proc_5.stderr
    assert elapsed < 10.0, f"5-slide render took {elapsed:.2f}s (expected < 10.0s)"

    summary_5 = json.loads(proc_5.stdout)
    probe_5 = _ffprobe_json(out_5)
    assert float(probe_5["format"]["duration"]) >= sum(s["hold_seconds"] for s in summary_5["slides"])
    sw5, sh5, _ = render_ketchup.decode_png_rgba(sheet_5)
    assert sw5 > 0 and sh5 > 0
