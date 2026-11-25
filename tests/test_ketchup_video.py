from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "skills" / "ketchup-video" / "scripts" / "render_ketchup.py"
HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
UV_BIN = shutil.which("uv")

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
    assert "Traceback" not in proc.stdout and "Traceback" not in proc.stderr
    data = json.loads(proc.stdout)
    assert data["text_backend"] in {"pillow-truetype", "bitmap-5x7"}
    if data["text_backend"] == "pillow-truetype":
        assert data["font_path"] and Path(data["font_path"]).is_file()
    else:
        assert data["font_path"] is None

    if HAS_FFMPEG:
        assert proc.returncode == 0, proc.stderr
        assert data["ok"] is True
        assert data["ffmpeg"]
        assert data["ffprobe"]
        assert data["encoders"] == {"libx264": True, "png": True}
        assert data["fallback"] is None
        assert data["error"] is None
    else:
        assert proc.returncode == 1
        assert data["ok"] is False
        assert data["fallback"] == "generative_ui"
        assert data["error"]


@pytest.mark.skipif(UV_BIN is None, reason="uv not installed")
def test_check_env_uv_run_truetype() -> None:
    proc = subprocess.run(
        [UV_BIN, "run", str(SCRIPT_PATH), "--check-env"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "Traceback" not in proc.stdout and "Traceback" not in proc.stderr
    data = json.loads(proc.stdout)
    assert data["text_backend"] == "pillow-truetype"
    assert data["font_path"] is not None
    assert Path(data["font_path"]).is_file()

    if HAS_FFMPEG:
        assert proc.returncode == 0, proc.stderr
        assert data["ok"] is True
        assert data["fallback"] is None
        assert data["error"] is None
    else:
        assert proc.returncode == 1
        assert data["ok"] is False
        assert data["fallback"] == "generative_ui"
        assert data["error"]


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


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")
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


@pytest.mark.skipif(UV_BIN is None, reason="uv not installed")
def test_uv_run_truetype_render_isolation_and_clamping(tmp_path: Path) -> None:
    shot_path = tmp_path / "shot.png"
    _make_sample_png(shot_path)

    long_sub = (
        "Twenty five words verify that longer subtitles wrap cleanly onto multiple rows inside the fixed "
        "bottom strip without touching or clipping against the slide diagram above."
    )
    overflow_sub = " ".join(["overflowword"] * 90)
    spec_path = tmp_path / "truetype_spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "width": 1280,
                "height": 720,
                "strip_height": 96,
                "slides": [
                    {
                        "title": "TrueType Pipeline",
                        "nodes": [
                            {"id": "a", "label": "Spec Parse", "status": "done"},
                            {"id": "b", "label": "TrueType Render", "status": "running"},
                        ],
                        "edges": [{"from": "a", "to": "b", "label": "flows"}],
                        "screenshots": [{"path": str(shot_path), "caption": "ignored words"}],
                        "subtitle": "Antialiased typography renders cleanly inside the bottom strip.",
                    },
                    {
                        "title": "TrueType Pipeline",
                        "nodes": [
                            {"id": "a", "label": "Spec Parse", "status": "done"},
                            {"id": "b", "label": "TrueType Render", "status": "done"},
                        ],
                        "edges": [{"from": "a", "to": "b", "label": "flows"}],
                        "subtitle": long_sub,
                    },
                    {
                        "title": "Overflow Guard",
                        "labels": ["Clamped Strip"],
                        "subtitle": overflow_sub,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    isolation_check = (
        "import json, sys; from pathlib import Path; "
        f"sys.path.insert(0, {str(SCRIPT_PATH.parent)!r}); "
        "import render_ketchup as rk; "
        "backend = rk.resolve_text_backend(); "
        "assert backend.name == 'pillow-truetype' and backend.font_path; "
        f"spec_raw = json.loads(Path({str(spec_path)!r}).read_text(encoding='utf-8')); "
        f"spec_full = rk.parse_spec(spec_raw, Path({str(tmp_path)!r})); "
        "timings, _ = rk.compute_timings(spec_full); "
        "assert timings[0].added_words == 15 and timings[0].hold_seconds == 5.0; "
        "c_full, lines_full = rk.render_slide_canvas(spec_full, spec_full.slides[0], {}, text_backend=backend); "
        f"png_out = Path({str(tmp_path / 'truetype_slide0.png')!r}); "
        "png_out.write_bytes(c_full.to_png_bytes(compress_level=1)); "
        "pw, ph, prgba = rk.decode_png_rgba(png_out); "
        "assert (pw, ph) == (1280, 720) and len(prgba) == pw * ph * 4 and lines_full; "
        "base = {'title': 'Isolation', 'nodes': [{'id': 'n1', 'label': 'Worker', 'status': 'done'}], 'subtitle': ''}; "
        f"spec = rk.parse_spec({{'width': 1280, 'height': 720, 'strip_height': 96, 'slides': [base, {{**base, 'subtitle': {long_sub!r}}}, {{**base, 'subtitle': {overflow_sub!r}}}]}}, Path({str(tmp_path)!r})); "
        "strip_y = spec.height - spec.strip_height; "
        "row_bytes = 1 + spec.width * 3; "
        "rendered = [rk.render_slide_canvas(spec, s, {}, text_backend=backend) for s in spec.slides]; "
        "base_top = bytes(rendered[0][0].raw[:strip_y * row_bytes]); "
        "assert bytes(rendered[1][0].raw[:strip_y * row_bytes]) == base_top; "
        "assert bytes(rendered[2][0].raw[:strip_y * row_bytes]) == base_top; "
        "assert len(rendered[1][1]) >= 2; "
        "assert rendered[2][1][-1].endswith('...'); "
        "print(json.dumps({'ok': True, 'backend': backend.name, 'font_path': backend.font_path}))"
    )
    iso_proc = subprocess.run(
        [UV_BIN, "run", "--with", "pillow>=10.0.0", "python3", "-c", isolation_check],
        capture_output=True,
        text=True,
        check=False,
    )
    assert iso_proc.returncode == 0, iso_proc.stderr
    assert json.loads(iso_proc.stdout)["backend"] == "pillow-truetype"

    if HAS_FFMPEG:
        out_mp4 = tmp_path / "truetype.mp4"
        sheet_png = tmp_path / "truetype_sheet.png"
        proc = subprocess.run(
            [
                UV_BIN,
                "run",
                str(SCRIPT_PATH),
                "--spec",
                str(spec_path),
                "--out",
                str(out_mp4),
                "--contact-sheet",
                str(sheet_png),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        summary = json.loads(proc.stdout)
        assert summary["ok"] is True
        assert summary["text_backend"] == "pillow-truetype"
        assert summary["font_path"] and Path(summary["font_path"]).is_file()
        assert summary["slides"][0]["added_words"] == 15
        assert summary["slides"][0]["hold_seconds"] == 5.0
        assert len(summary["slides"][1]["subtitle_lines"]) >= 2
        assert summary["slides"][2]["subtitle_lines"][-1].endswith("...")

        probe = _ffprobe_json(out_mp4)
        stream = probe["streams"][0]
        assert stream["codec_name"] == "h264"
        assert stream["width"] == 1280
        assert stream["height"] == 720
        assert stream["pix_fmt"] == "yuv420p"
        sw, sh, _ = render_ketchup.decode_png_rgba(sheet_png)
        assert sw > 0 and sh > 0


def test_no_pil_fallback_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "PIL", None)
    backend = render_ketchup.resolve_text_backend()
    assert backend.name == "bitmap-5x7"
    assert backend.font_path is None

    base = {
        "title": "Fallback Isolation",
        "nodes": [{"id": "n1", "label": "Bitmap Node", "status": "done"}],
        "subtitle": "",
    }
    long_sub = (
        "Twenty five words verify that longer subtitles wrap cleanly onto multiple rows inside the fixed "
        "bottom strip without touching or clipping against the slide diagram above."
    )
    spec = render_ketchup.parse_spec(
        {
            "width": 1280,
            "height": 720,
            "strip_height": 96,
            "slides": [base, {**base, "subtitle": long_sub}],
        },
        tmp_path,
    )
    strip_y = spec.height - spec.strip_height
    row_bytes = 1 + spec.width * 3
    c0, _ = render_ketchup.render_slide_canvas(spec, spec.slides[0], {}, text_backend=backend)
    c1, lines1 = render_ketchup.render_slide_canvas(spec, spec.slides[1], {}, text_backend=backend)
    assert bytes(c1.raw[: strip_y * row_bytes]) == bytes(c0.raw[: strip_y * row_bytes])
    assert len(lines1) >= 2
    slide_png = tmp_path / "fallback_slide.png"
    slide_png.write_bytes(c1.to_png_bytes(compress_level=1))
    pw, ph, _ = render_ketchup.decode_png_rgba(slide_png)
    assert (pw, ph) == (1280, 720)

    shim = (
        "import sys; "
        "sys.modules['PIL'] = None; "
        f"sys.path.insert(0, {str(SCRIPT_PATH.parent)!r}); "
        "import render_ketchup; "
        "raise SystemExit(render_ketchup.main(sys.argv[1:]))"
    )
    env_proc = subprocess.run(
        [sys.executable, "-c", shim, "--check-env"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "Traceback" not in env_proc.stdout and "Traceback" not in env_proc.stderr
    env_data = json.loads(env_proc.stdout)
    assert env_data["text_backend"] == "bitmap-5x7"
    assert env_data["font_path"] is None
    if HAS_FFMPEG:
        assert env_proc.returncode == 0, env_proc.stderr
        assert env_data["ok"] is True
    else:
        assert env_proc.returncode == 1
        assert env_data["ok"] is False
        assert env_data["fallback"] == "generative_ui"

    if HAS_FFMPEG:
        spec_path = tmp_path / "fallback_spec.json"
        spec_path.write_text(
            json.dumps(
                {
                    "slides": [
                        {
                            "title": "Bitmap Fallback",
                            "labels": ["No Pillow Needed"],
                            "subtitle": "Plain python renders cleanly without Pillow installed.",
                        },
                        {
                            "title": "Bitmap Fallback",
                            "labels": ["No Pillow Needed", "Contact Sheet Valid"],
                            "subtitle": "Both slides produce a valid MP4 and contact sheet.",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        out_mp4 = tmp_path / "fallback.mp4"
        sheet_png = tmp_path / "fallback_sheet.png"
        render_proc = subprocess.run(
            [
                sys.executable,
                "-c",
                shim,
                "--spec",
                str(spec_path),
                "--out",
                str(out_mp4),
                "--contact-sheet",
                str(sheet_png),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert render_proc.returncode == 0, render_proc.stderr
        assert "Traceback" not in render_proc.stdout and "Traceback" not in render_proc.stderr
        summary = json.loads(render_proc.stdout)
        assert summary["ok"] is True
        assert summary["text_backend"] == "bitmap-5x7"
        assert summary["font_path"] is None
        sw, sh, _ = render_ketchup.decode_png_rgba(sheet_png)
        assert sw > 0 and sh > 0
