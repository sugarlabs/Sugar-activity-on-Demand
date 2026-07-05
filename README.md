<p align="center">
  <img src="docs/banner.png" alt="Sugar Activity Studio — generate real Sugar learning activities from a plain-language idea" width="100%">
</p>

<h1 align="center">Sugar Activity Studio</h1>

<p align="center">
  <b>Describe a learning activity in plain words — get a real, installable Sugar activity.</b>
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

> **Sugar Activity Studio** is the standalone desktop app for
> **Activity on Demand** by <b>Sugar Labs</b>: an AI-assisted studio that turns a
> learner's or teacher's idea — *"a fraction matching game with levels
> and instant feedback"* — into a complete
> [Sugar](https://sugarlabs.org) activity: planned, coded, validated,
> live-previewed, and packaged as an installable `.xo` bundle.
> Runs on any Linux desktop. **No Sugar shell required.**

<p align="center">
  <sub><b>idea</b> → ✨ enhance → plan · RAG → generate → validate → <b>preview</b> → refine → <b>export</b></sub>
</p>

## Features

- 🏠 **Sugar-style home** — opens on your XO icon, in your own colors,
  with every activity you have generated ringed around it — the same
  ring/spiral geometry as the Sugar shell. Click an icon to play it;
  hover or right-click for **Open** / **Modify**.
- ✨ **Plain-language creation** — pick a learning area, describe the
  idea, press Send. The **Enhance** button (and automatic enhancement
  for short prompts) expands rough ideas into a detailed brief the AI
  can build correctly — and the chat shows the brief it understood, so
  you learn what a strong prompt looks like.
- 🧭 **Grounded generation** — the pipeline retrieves patterns from real
  installed Sugar activities (local RAG — no uploads, no training),
  plans with your chosen model, generates `activity.py`, and validates
  it (syntax, Sugar API misuse, import safety, request match) with
  automatic retry-and-fix rounds.
- 🖼️ **Live preview** — the generated activity runs embedded in the
  studio. Click any part of the preview and describe a change;
  refinements land as minimal patches with full version history.
- 📜 **Review & versions** — read the generated code with syntax
  highlighting, inspect the plan, hop between revisions.
- 📦 **Export & install** — one click packages an `.xo` bundle, exports
  buildable Flatpak sources, or installs to `~/Activities` and launches
  the activity immediately via `sugar-activity3`.
- 🛡️ **Safe by design** — generated code is held to an import/call
  allowlist, may not touch the network or filesystem APIs, and every
  failure path degrades gracefully.

## Requirements

The GTK stack comes from your distribution, not PyPI:

| Requirement | Why |
|---|---|
| Python ≥ 3.8 | the app itself |
| GTK 3 + PyGObject (`python3-gi`, `gir1.2-gtk-3.0`) | the UI |
| Sugar toolkit (`python3-sugar3`, `sugar-toolkit-gtk3`) | Sugar widgets, `.xo` packaging, the `sugar-activity3` launcher |
| *(optional)* `sugar-artwork` themes | authentic Sugar look; degrades gracefully without |

On Debian/Ubuntu:

```sh
sudo apt install python3-gi gir1.2-gtk-3.0 python3-sugar3 sugar-toolkit-gtk3
```

> [!NOTE]
> The studio depends on the Sugar **toolkit as a library** — the way any
> GTK app depends on GTK. It does **not** need the Sugar desktop
> installed or running.

## Setup & run

**From a checkout** (no install):

```sh
git clone https://github.com/Ashutoshx7/sugar-aod-studio.git
cd sugar-aod-studio
python3 bin/sugar-aod-studio        # or: python3 -m aodstudio
```

**Installed:**

```sh
pip install .
sugar-aod-studio
```

### Connect an AI model

Open the create page and use the **provider selector** next to the
prompt box: choose a provider, paste your API key, Save. Keys are
stored locally in your profile and never leave your machine except to
call the provider you chose.

| | |
|---|---|
| **Providers** | OpenRouter *(default: `anthropic/claude-opus-4.8`)*, Gemini, OpenAI, Claude, DeepSeek, Qwen, Moonshot, Ollama *(local, no key)* |
| **Offline** | a keyless *local template* mode for trying the flow without any AI |
| **Overrides** | `AOD_OPENROUTER_MODEL`, `AOD_GEMINI_MODEL`, `AOD_OLLAMA_MODEL`, … and `AOD_LLM_PROVIDER` for the default provider |

## Using the studio

1. **Home** — everything you've made, around your XO. Click to play,
   right-click → *Modify* to keep working on one, or **Create new**.
2. **Create** — pick a learning area, type your idea. Press
   **✨ Enhance** to expand it into an editable brief, or just Send —
   short prompts are enhanced automatically (toggle: *Enhance
   Auto/Off*).
3. **Studio** — watch the generation progress, then explore the
   **Preview / Review / Versions** tabs. Click a part of the live
   preview and describe a change, or chat a refinement — each one
   becomes a new version.
4. **Ship it** — *Export XO*, *Export Flatpak*, or *Install & Open* to
   put it in `~/Activities` and play it instantly.

## Where things live

| Path | Contents |
|---|---|
| `~/.sugar/default/aod/` | projects, sessions, jobs, API keys — shared with a Sugar shell install if you have one |
| `~/Activities/` | installed activities |

## Development

```sh
python3 -m pytest tests/ -q     # 150 tests: pipeline, providers, UI smoke
python3 -m flake8 aodstudio/
```

`aodstudio/model/` is the shell-free backend (planning, RAG, LLM
providers, code generation, validation, packaging, sessions);
`aodstudio/ui/` is the GTK front end (`panel.py` hosts the whole
studio, `window.py` wraps it); `bin/sugar-aod-studio` is the launcher.
A test enforces that no `jarabe` (Sugar shell) module is ever imported.

## Provenance

Extracted from the `aod-activity-on-demand` branch of the
[Sugar shell fork](https://github.com/Ashutoshx7/sugar), where the same
experience also runs embedded in the Sugar home view. The home ring
layout is ported from Sugar's `favoriteslayout.py`.

---

<p align="center">
  <sub>GPL-3.0-or-later, same as Sugar — see <a href="LICENSE">LICENSE</a> · built with ❤️ for learners</sub>
</p>
