import { describe, expect, it } from "bun:test";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const CHECK_PLAN_SCRIPT = path.resolve(__dirname, "check-plan.mjs");

function createBasePlan(extraContent = ""): string {
  return `# Sample plan

Intro line one.
Intro line two.

## How to read this

One box is one unit of work. Every box names the evidence that checks it.
Check a box only when its evidence exists.
The program runs playbooks/autopilot-full.md.
Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

## Program checklist

### Arm the program

- [ ] Arm /goal with this plan
- [ ] git show origin/main:skills/poteto-mode/playbooks/autopilot-full.md
- [ ] Arm the 30-minute audit tick
- [ ] status message

### Spawn owners

- [ ] Spawn one owner per PR

### PR mechanics

- [ ] Open the PR ready

### Verdict and merge

- [ ] Verdict clean

### Boot recipe

- [ ] Boot recipe

## Ship reliability fixes (PR 1)

**Depends on.** None.

**Files.**

- [ ] Edit file.ts

**Build.**

- [ ] Symbol change

**You see.**

- [ ] Ready message

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Unit tests pass

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on \`worker-model\` at the PR head

- [ ] Lane 1. Scenario 1. Save \`lane-1.png\`. Pass when true
- [ ] Lane 2. Scenario 2. Save \`lane-2.png\`. Pass when true
- [ ] Lane 3. Scenario 3. Save \`lane-3.png\`. Pass when true
- [ ] Lane 4. Scenario 4. Save \`lane-4.png\`. Pass when true
- [ ] Lane 5. Scenario 5. Save \`lane-5.png\`. Pass when true
- [ ] Lane 6. Scenario 6. Save \`lane-6.png\`. Pass when true
- [ ] Lane 7. Scenario 7. Save \`lane-7.png\`. Pass when true
- [ ] Lane 8. Scenario 8. Save \`lane-8.png\`. Pass when true
- [ ] Lane 9. Scenario 9. Save \`lane-9.png\`. Pass when true
- [ ] Lane 10. Scenario 10. Save \`lane-10.png\`. Pass when true

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. Execution time
- [ ] Probe. Time command
- [ ] Baseline. 100ms
- [ ] Rule. Less than 110ms

**Review gate.** None. Not review-gated.

**Merge.**

- [ ] Merge PR

${extraContent}

## Close the program

- [ ] Disarm 30-minute tick

## Appendix A. Prototype evidence

Evidence here
`;
}

function runCheckPlan(planText: string): { status: number; stdout: string; stderr: string } {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "check-plan-test-"));
  const tmpFile = path.join(tmpDir, "plan.md");
  fs.writeFileSync(tmpFile, planText, "utf8");
  try {
    const res = spawnSync("node", [CHECK_PLAN_SCRIPT, tmpFile], {
      encoding: "utf8",
    });
    return {
      status: res.status ?? (res.error ? 1 : 0),
      stdout: res.stdout ?? "",
      stderr: res.stderr ?? "",
    };
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
}

describe("check-plan code fence matching and prose rules", () => {
  it("allows standard triple-backtick fences containing forbidden prose characters", () => {
    const plan = createBasePlan(`
\`\`\`ts
// Forbidden in prose: mid-sentence colon, long — dash, ‘single’ and “double” quotes
const message = "status: ok — verified";
\`\`\`
`);
    const res = runCheckPlan(plan);
    expect(res.status).toBe(0);
    expect(res.stderr).not.toContain("long dash");
    expect(res.stderr).not.toContain("curly quote");
    expect(res.stderr).not.toContain("mid-sentence colon");
  });

  it("allows tilde fences (~~~) containing forbidden prose characters", () => {
    const plan = createBasePlan(`
~~~bash
# Forbidden in prose: colon: value — long dash and ‘curly’ quotes
echo "done: 100%"
~~~
`);
    const res = runCheckPlan(plan);
    expect(res.status).toBe(0);
    expect(res.stderr).not.toContain("long dash");
    expect(res.stderr).not.toContain("curly quote");
    expect(res.stderr).not.toContain("mid-sentence colon");
  });

  it("allows indented fences with 1 to 3 leading spaces", () => {
    const plan = createBasePlan(`
   \`\`\`python
   # 3 leading spaces on open and close
   x = "colon: here — dash ‘quotes’"
   \`\`\`
`);
    const res = runCheckPlan(plan);
    expect(res.status).toBe(0);
    expect(res.stderr).not.toContain("long dash");
    expect(res.stderr).not.toContain("curly quote");
    expect(res.stderr).not.toContain("mid-sentence colon");
  });

  it("supports multi-backtick fences (````) nesting triple-backtick fences", () => {
    const plan = createBasePlan(`
\`\`\`\`markdown
Here is a nested markdown code fence:
\`\`\`ts
const nested = "mid-sentence: colon — dash ‘quotes’";
\`\`\`
\`\`\`\`
`);
    const res = runCheckPlan(plan);
    expect(res.status).toBe(0);
    expect(res.stderr).not.toContain("long dash");
    expect(res.stderr).not.toContain("curly quote");
    expect(res.stderr).not.toContain("mid-sentence colon");
  });

  it("rejects unclosed triple-backtick code fences at EOF with exit code 1", () => {
    const plan = createBasePlan(`
\`\`\`ts
const unclosed = true;
`);
    // Remove the Close the program section and leave fence unclosed at EOF
    const unclosedPlan = plan + "\n```ts\nconst dangling = 1;\n";
    const res = runCheckPlan(unclosedPlan);
    expect(res.status).toBe(1);
    expect(res.stderr).toContain("unclosed code fence");
  });

  it("rejects unclosed tilde code fences at EOF with exit code 1", () => {
    const plan = createBasePlan() + "\n~~~sh\necho 'unclosed tilde'\n";
    const res = runCheckPlan(plan);
    expect(res.status).toBe(1);
    expect(res.stderr).toContain("unclosed code fence");
  });

  it("fails on prose rules outside code blocks but ignores them inside code blocks", () => {
    // 1. Outside code block: em dash fails
    const dashPlan = createBasePlan("\nThis prose has a long — dash outside of code.\n");
    const dashRes = runCheckPlan(dashPlan);
    expect(dashRes.status).toBe(1);
    expect(dashRes.stderr).toContain("long dash");

    // 2. Outside code block: curly quote fails
    const quotePlan = createBasePlan("\nThis prose has ‘curly quotes’ outside of code.\n");
    const quoteRes = runCheckPlan(quotePlan);
    expect(quoteRes.status).toBe(1);
    expect(quoteRes.stderr).toContain("curly quote");

    // 3. Outside code block: mid-sentence colon fails
    const colonPlan = createBasePlan("\nThis prose has: a mid-sentence colon.\n");
    const colonRes = runCheckPlan(colonPlan);
    expect(colonRes.status).toBe(1);
    expect(colonRes.stderr).toContain("mid-sentence colon");

    // 4. Inside code block: all three are allowed
    const validPlan = createBasePlan(`
\`\`\`text
This has a long — dash, ‘curly quotes’, and mid-sentence: colon.
\`\`\`
`);
    const validRes = runCheckPlan(validPlan);
    expect(validRes.status).toBe(0);
    expect(validRes.stderr).toBe("");
  });
});
