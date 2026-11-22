# Export a standalone SVG

Antigravity renders `stateDiagram-v2` blocks natively inside `<appDataDir>/brain/<conversation-id>/statechart_<slug>.md`. Use this workflow only when the user asks for a standalone SVG file or a large chart is easier to inspect outside inline text.

Render each `.mmd` file with the npm package `pele@1.9.0`. Install Pele once, outside the repo. Write each SVG next to its `.mmd` file with the same stem, then copy any SVG you want to embed into `<appDataDir>/brain/<conversation-id>/` before referencing it in an Antigravity artifact. The API is documented at https://pele.run/api. Pass `{ limit: 1_000_000, outputLimit: 8_000_000, maxEdges: 10_000 }` to `render`, because Pele's defaults are smaller than a 500-state chart can grow. When Pele throws a `PeleError`, surface the Mermaid text and the error.

## Colors

Pele ignores Mermaid `theme` and `themeVariables`. Set its `--pele-*` CSS variables on `.pele` (documented at https://pele.run/theming). `scripts/statechart` assigns each state its group color class (`class sN teal`) and bug marks (`class sN breaks`, `class sN mayBreak`, `class sN bugPath`, and `class sN repeats`).

`chart.mmd` includes `classDef` rules for `breaks` and `mayBreak` so standard Mermaid viewers show bug marks natively, while group colors, `bugPath`, and `repeats` have no `classDef`. Because Pele writes `classDef` rules as inline `style` attributes that override normal CSS, the mark rules below use `!important` so dark themes stay readable. Put mark rules after group colors so bug marks take precedence.

Prepend this `<style>` block inside each exported SVG so it adapts to light and dark viewers:

```css
.pele {
  --pele-bg: #ffffff;
  --pele-fg: #1c1c1c;
  --pele-muted: #656565;
  --pele-line: #808080;
  --pele-surface: #fcfcfc;
  --pele-surface-alt: #f1f1f1;
  --pele-border: #c9c9c9;
}
.pele .blue rect { fill: #c3e0ff; }
.pele .orange rect { fill: #f0d3bf; }
.pele .purple rect { fill: #e3d5ff; }
.pele .yellow rect { fill: #f0dcbf; }
.pele .teal rect { fill: #bfe3df; }
.pele .tan rect { fill: #e5d9ce; }
.pele .pink rect { fill: #ffcbe6; }
.pele .breaks rect {
  fill: #ffecee !important;
  stroke: #e72e3b !important;
  stroke-width: 2.5px !important;
}
.pele .breaks text {
  fill: #cd2834 !important;
}
.pele .mayBreak rect {
  fill: #fff3e6 !important;
  stroke: #e8730c !important;
  stroke-width: 2.5px !important;
}
.pele .mayBreak text {
  fill: #b85a06 !important;
}
.pele .bugPath rect {
  stroke: #1680f3 !important;
  stroke-width: 2.5px !important;
}
.pele .repeats rect {
  stroke: #9b35d6 !important;
  stroke-width: 2.5px !important;
  stroke-dasharray: 6 3;
}
@media (prefers-color-scheme: dark) {
  .pele {
    --pele-bg: #1f1f1f;
    --pele-fg: #f5f5f5;
    --pele-muted: #acacac;
    --pele-line: #939393;
    --pele-surface: #121212;
    --pele-surface-alt: #2c2c2c;
    --pele-border: #4e4e4e;
  }
  .pele .blue rect { fill: #1b3857; }
  .pele .orange rect { fill: #573117; }
  .pele .purple rect { fill: #3c2e57; }
  .pele .yellow rect { fill: #573d17; }
  .pele .teal rect { fill: #174641; }
  .pele .tan rect { fill: #3d3127; }
  .pele .pink rect { fill: #57233e; }
  .pele .breaks rect {
    fill: #2e2021 !important;
    stroke: #cf2b35 !important;
  }
  .pele .breaks text {
    fill: #ff6463 !important;
  }
  .pele .mayBreak rect {
    fill: #2e2619 !important;
    stroke: #d0700f !important;
  }
  .pele .mayBreak text {
    fill: #ffa257 !important;
  }
  .pele .bugPath rect {
    stroke: #116dd2 !important;
  }
  .pele .repeats rect {
    stroke: #9a3fcf !important;
  }
}
```
