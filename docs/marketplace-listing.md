# agystack Marketplace Listing

This document defines the official catalog metadata, presentation copy, and developer guidance for the Antigravity Plugins Marketplace.

## Marketplace Card Overview

- **Plugin Name:** `agystack`
- **Display Name:** `agystack`
- **Version:** `0.16.0`
- **Category:** Developer Tools / Agentic Engineering
- **Author:** Joel Taroreh
- **Repository:** https://github.com/jtaroreh/agystack
- **License:** MIT
- **Logo:** `assets/logo.svg` (256x256, transparent, high-contrast geometric chevron)

## Description

Rigorous agentic engineering framework for Google Antigravity: poteto-mode, playbooks, isolated subagents, adversarial reviews, and cloud swarms. Spinoff of poteto's pstack.

## Suggested Prompts

1. `/agystack plan and implement this feature`
2. `/interrogate this implementation with multi-model adversarial reviews`
3. `/create-verification-skill for this project`

## Key Capabilities

- **Twenty-Three Rigorous Playbooks:** Structured procedural engines for bug fixes, performance investigations, refactoring, autonomous loops, and stacked shipping.
- **Twenty-Four Anti-Slop Principles:** Invariant rules that prevent speculative code, enforce domain data models, and mandate real-world runtime verification.
- **Subagent Context Isolation:** Guard coordinator chat context windows by delegating code changes over 50 lines to isolated background workers.
- **Google Cloud Run Swarms (`/swarm`):** Scale beyond local machine concurrency with serverless container fleets executing parallel parameter sweeps and candidate patches.
- **Multi-Model Adversarial Interrogation (`/interrogate`):** Dispatch concurrent reviewer panels across distinct model tiers to challenge diffs before merge.
- **Native Antigravity Artifacts:** Structured deliverables (`implementation_plan.md`, `walkthrough.md`, `<topic>_report.md`) rendered directly in the IDE canvas.

## Installation

### Via Antigravity CLI
```bash
agy plugin install agystack
```

### Via Antigravity App
1. Open the left sidebar and navigate to **Customizations**.
2. Select the **Marketplace** tab.
3. Search for `agystack` and click **Install**.

### Via Agent Prompt
```text
install this antigravity plugin for me: https://github.com/jtaroreh/agystack
```

## Validation & Verification

Before publishing or upgrading the plugin bundle, verify strict compliance:

```bash
# Strict manifest and directory validation
agy plugin validate . --strict

# Automated test suite
pytest tests/
```
