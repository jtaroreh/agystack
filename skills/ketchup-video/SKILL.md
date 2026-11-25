---
name: ketchup-video
description: "Catch the user up like /ketchup, with a short subtitled video of slides for what happened and the waiting calls as text under it. Use for /ketchup-video."
disable-model-invocation: true
---

# Ketchup video

Follow [`/ketchup`](../ketchup/SKILL.md), showing what happened in a short subtitled video instead of its summary and inline visuals. Start the window at the last message the user wrote before `/ketchup-video`, not before any earlier `/ketchup`. Writing the spec, contact sheet, and video inside `<appDataDir>/brain/<conversation-id>/` (with intermediate files in `<appDataDir>/brain/<conversation-id>/scratch/`), outside the repo, is the one exception to `/ketchup`'s read-only rule.

The reply contains `/ketchup`'s opening sentence, the embedded video from `<appDataDir>/brain/<conversation-id>/`, one line naming any remaining work you can do yourself, and the action items. When the video shows a call's options, name each option identically to the video.

## Environment Gate and Fallback

Run the environment probe before writing any slide spec:

```bash
python3 <skill-dir>/scripts/render_ketchup.py --check-env
```

- When `--check-env` exits `0` (`ok: true`), render the MP4 with `render_ketchup.py`.
- When `--check-env` exits non-zero (`ok: false`, such as missing `ffmpeg`, `ffprobe`, or `libx264`), do not attempt MP4 rendering or emit broken video links. State the missing dependency in one line and fall back to a `generative_ui` interactive HTML slide deck paired with [`/ketchup`](../ketchup/SKILL.md) text action items.

## Slides

Draw from the screenshots, recordings, diffs, and data the work produced, not chat prose. Before writing `slides.json`, write the one sentence the user should leave with and one line per slide. Drop any slide that does not change what the user knows. Use at most 10 slides, and fewer is better. Neither note goes in the reply.

Each slide makes one point. Evolve one picture from slide to slide rather than cutting between unrelated layouts. Keep semantic colors and shapes consistent across every slide (`done`/`merged` green, `running`/`active` amber, `failed`/`blocked` red, `waiting` blue-slate). Show the work in pictures, such as a system flow, a PR stack with each PR's state, a before-and-after diagram, or options side by side. A slide is never a bullet list, a status list, a table, or disconnected boxes.

Keep text minimal. Put each label directly on the thing it names in plain words, not tags like `"Tests: pass"`. Never caption what a picture already shows, and never repeat a fact across slides or in the text under them.

Show the outcome of each item the user asked for: `done`, `still running`, `failed`, or `not checked`. Never mark work waiting on the user as done. Include any bug found and fixed along the way. If a visible change has no screenshot, note that on its slide and name what changed on screen. Never invent numbers or draw fake screens.

## Subtitles

Give each slide one short subtitle sentence, around ten words, stating what the picture means rather than reading out its labels. Place all subtitle text in `subtitle`; `render_ketchup.py` places it in the fixed bottom strip (`y in [height - strip_height, height)`) with automatic word-wrapping and clamping so subtitles never overlap slide content.

## Spec Schema (`slides.json`)

Write `<appDataDir>/brain/<conversation-id>/scratch/slides.json`:

- Top-level fields: `width` (default `1280`), `height` (default `720`), `strip_height` (default `96`), `fps` (default `30`), `transition_seconds` (default `0.3`), `slides` (non-empty list).
- Slide fields:
  - `title`: optional string.
  - `subtitle`: string rendered into the fixed bottom strip.
  - `labels`: optional list of short label strings.
  - `nodes`: optional list of `{id?, label, x?, y?, status?}`.
  - `edges`: optional list of `{from, to, label?}`.
  - `screenshots` (or `images`): optional list of string paths or `{path, caption?}` objects (8-bit PNGs composited inside the slide area; words inside screenshots are excluded from hold calculations).

## Render and Verify

Delegate all word-diff hold calculations (`max(2.0, ceil(added_words / 3))`), bottom-strip layout, slide rendering, MP4 encoding (`1280x720`, `30fps`, `libx264`, `yuv420p`, `+faststart`, `0.3s` `xfade` transitions), and contact-sheet extraction to `render_ketchup.py`:

```bash
python3 <skill-dir>/scripts/render_ketchup.py \
  --spec <appDataDir>/brain/<conversation-id>/scratch/slides.json \
  --out <appDataDir>/brain/<conversation-id>/ketchup.mp4 \
  --contact-sheet <appDataDir>/brain/<conversation-id>/scratch/contact_sheet.png
```

Before embedding `ketchup.mp4` in your reply, inspect `contact_sheet.png` in a single `read_file` call to verify legibility, clean subtitle wrapping, and zero overlap. Fix any unreadable slide in `slides.json`, re-render, and inspect the updated contact sheet before posting.
