<p align="center">
  <img src="docs/banner.png" alt="Sugar Activity Studio — generate real Sugar learning activities from a plain-language idea" width="100%">
</p>

<h1 align="center">Sugar Activity Studio</h1>

<p align="center">
  <strong>Turn a plain-language learning idea into a real, installable Sugar activity.</strong>
</p>

<p align="center">
  <img alt="License: GPL-3.0-or-later" src="https://img.shields.io/badge/license-GPL--3.0--or--later-8957e5?style=flat-square">
  <img alt="Python 3.8+" src="https://img.shields.io/badge/python-3.8%2B-3776ab?style=flat-square">
  <img alt="GTK 3" src="https://img.shields.io/badge/UI-GTK%203-4a86cf?style=flat-square">
  <img alt="Platform: Linux" src="https://img.shields.io/badge/platform-linux-f4a63a?style=flat-square">
</p>

<p align="center">
  <a href="#features">Features</a> ·
  <a href="#requirements">Requirements</a> ·
  <a href="#setup--run">Setup</a> ·
  <a href="#using-the-studio">Usage</a> ·
  <a href="#development">Development</a>
</p>

---

## Overview

**Sugar Activity Studio** is a standalone desktop application for **Activity on Demand** by **Sugar Labs**.

It helps learners and teachers describe an activity in plain words and turn that idea into a complete [Sugar](https://sugarlabs.org) activity. The studio plans, generates, validates, previews, refines, and packages the activity as an installable `.xo` bundle.

Example:

> “A fraction matching game with levels and instant feedback.”

The studio runs on any Linux desktop and does **not** require the Sugar shell to be installed or running.

<p align="center">
  <sub><strong>idea</strong> → enhance → plan → generate → validate → run → preview → refine → export</sub>
</p>

---

## Features

### Sugar-style home

The studio opens with a Sugar-inspired home view centered around your XO identity. Generated activities are arranged around it using the same ring-style geometry as the Sugar shell.

You can open an activity, continue modifying it, or create a new one from the home screen.

### Plain-language creation

Choose a learning area, describe your idea, and send it to the studio.

The prompt enhancement flow can expand short or rough ideas into a clearer activity brief. The enhanced brief is shown back to you, helping you understand what the model will build and how to write stronger prompts.

### Grounded generation

The generation pipeline retrieves patterns from real installed Sugar activities using local RAG. It uses those patterns to plan and generate the activity while staying close to Sugar conventions.

No activity data is uploaded for training.

### Runtime validation

Generated code is not accepted only because it looks correct. Each candidate is validated for syntax, Sugar API usage, import safety, and request alignment.

The activity is then run in a sandboxed subprocess, event-pumped, saved, restored, and checked before it is accepted. Crashes are returned to the model as feedback for retry-and-fix rounds.

### Live preview and refinement

Generated activities run directly inside the studio preview.

You can click part of the preview and describe a change. Refinements are applied as minimal patches, with full version history preserved.

### Review and version history

The studio lets you inspect the generated code, review the plan, and move between revisions. This makes the process transparent and easier to debug.

### Export and install

Activities can be exported as `.xo` bundles, exported as buildable Flatpak sources, or installed directly to `~/Activities`.

Installed activities can be launched immediately using `sugar-activity3`.

### Safe by design

Generated code is checked against an import and call allowlist. Network access and unsafe filesystem APIs are blocked, and failure paths are designed to degrade gracefully.

---

## Requirements

The GTK and Sugar dependencies come from your Linux distribution, not PyPI.

| Requirement          | Purpose                                                        |
| -------------------- | -------------------------------------------------------------- |
| Python 3.8 or newer  | Runs the studio                                                |
| GTK 3 + PyGObject    | Provides the desktop UI                                        |
| Sugar Toolkit GTK3   | Sugar widgets, `.xo` packaging, and `sugar-activity3` launcher |
| sugar-artwork themes | Optional Sugar visual styling                                  |

On Debian or Ubuntu:

```sh
sudo apt install python3-gi gir1.2-gtk-3.0 python3-sugar3 sugar-toolkit-gtk3
```

> The studio depends on the Sugar toolkit as a library, the same way a GTK app depends on GTK. It does not require the Sugar desktop shell.

---

## Setup & run

```sh
git clone https://github.com/Ashutoshx7/Sugar-activity-on-Demand.git
cd Sugar-activity-on-Demand
python3 bin/sugar-aod-studio
```

Or run:

```sh
python3 main.py
```

---

## Connect an AI model

Open the create page and use the provider selector next to the prompt box.

Choose a provider, paste your API key, and save. Keys are stored locally in your profile and are only used to call the provider you select.

| Option       | Details                                                                                |
| ------------ | -------------------------------------------------------------------------------------- |
| Providers    | OpenRouter, Gemini, OpenAI, Claude, DeepSeek, Qwen, Moonshot, Ollama                   |
| Default      | OpenRouter with `anthropic/claude-opus-4.8`                                            |
| Offline mode | Keyless local template mode for trying the flow without an AI provider                 |
| Overrides    | `AOD_OPENROUTER_MODEL`, `AOD_GEMINI_MODEL`, `AOD_OLLAMA_MODEL`, and `AOD_LLM_PROVIDER` |

---

## Using the studio

### 1. Home

View all activities you have created around your XO icon. Open an activity, modify an existing one, or create a new project.

### 2. Create

Pick a learning area and describe your idea. Use prompt enhancement to turn a rough idea into a more complete activity brief, or send the prompt directly.

Short prompts can be enhanced automatically using the auto-enhance toggle.

### 3. Studio

Watch the generation pipeline progress, then explore the generated activity through the preview, review, and version tabs.

You can refine the activity by selecting part of the preview or sending a follow-up instruction.

### 4. Ship

Export the activity as an `.xo` bundle, export Flatpak sources, or install it directly to `~/Activities`.

---

## Where things live

| Path                    | Contents                                              |
| ----------------------- | ----------------------------------------------------- |
| `~/.sugar/default/aod/` | Projects, sessions, jobs, and locally stored API keys |
| `~/Activities/`         | Installed Sugar activities                            |

The `~/.sugar/default/aod/` directory is shared with a Sugar shell install when one is available.

---

## Development

Run the test suite:

```sh
python3 -m pytest tests/ -q
```

Run linting:

```sh
python3 -m flake8 core llm generation service exports preview ui main.py
```

The codebase is organized by domain:

| Directory     | Purpose                                                    |
| ------------- | ---------------------------------------------------------- |
| `core/`       | Specs, licenses, and project models                        |
| `llm/`        | Providers, credentials, and prompt enhancement             |
| `generation/` | Pipeline, RAG, code generation, validation, and refinement |
| `service/`    | Job queue and sessions                                     |
| `exports/`    | Flatpak and export logic                                   |
| `preview/`    | Activity preview runtime                                   |
| `ui/`         | GTK interface                                              |

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full architecture map.

A test ensures that no `jarabe` module from the Sugar shell is imported, keeping the studio independent from the full Sugar desktop environment.

---

## Provenance

Sugar Activity Studio was extracted from the `aod-activity-on-demand` branch of the [Sugar shell fork](https://github.com/Ashutoshx7/sugar), where the same experience also runs embedded inside the Sugar home view.

The home ring layout is ported from Sugar's `favoriteslayout.py`.

---

<p align="center">
  <sub>GPL-3.0-or-later, same as Sugar. See <a href="LICENSE">LICENSE</a>.</sub>
</p>
