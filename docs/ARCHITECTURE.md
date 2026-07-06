# Architecture

```
Sugar-activity-on-Demand/
├── main.py                       entry point: dependency check, theme setup, Gtk.main
├── core/              foundations shared by everything
│   ├── spec.py        ActivitySpec — the validated generation request
│   ├── licenses.py    license texts and metadata
│   └── projects.py    list/reopen previously generated projects
├── llm/               talking to models
│   ├── providers.py   provider clients (OpenRouter, Gemini, OpenAI, …)
│   ├── credentials.py local API-key store
│   └── enhance.py     expand short prompts into detailed briefs
├── generation/        idea → activity.py
│   ├── pipeline.py    orchestrates enhance → RAG → plan → code → package
│   ├── prompts.py     planner prompts
│   ├── rag.py         local retrieval over installed Sugar activities
│   ├── codegen.py     code-generation prompts and response extraction
│   ├── generator.py   plan normalization, project assembly, .xo packaging
│   ├── validator.py   safety + quality validation of generated code
│   ├── runtime_check.py  runs candidate code in a GTK subprocess gate
│   ├── runtime_harness.py  subprocess body for the runtime gate
│   ├── critic.py      one self-review round over accepted code
│   ├── icons.py       model-drawn activity icons (glyph fallback)
│   ├── refine.py      SEARCH/REPLACE refinement patches
│   └── templates.py   local template renderer (offline fallback)
├── service/           background execution and persistence
│   ├── service.py     public facade (get_service): submit, watch, cancel
│   ├── queue.py       worker queue
│   ├── jobs.py        persistent job records
│   └── sessions.py    prompt/refinement conversations and revisions
├── exports/
│   └── flatpak.py     buildable Flatpak sources / best-effort bundles
├── preview/
│   └── runner.py      run generated activities in-process, shell-free
└── ui/
    ├── window.py      top-level window
    ├── ring.py        Sugar-style home ring layout (ported from jarabe)
    ├── theme.py       studio CSS
    └── panel.py       the whole studio UI (home, create, studio views)
```

**Layering** (imports point downward only, module-level):
`ui` → `service` → `generation` → `llm` → `core`, with `exports` and
`preview` as leaves used by `ui`/`generation`. `llm/providers` reaches
into `generation/codegen+prompts` for response extraction — a
deliberate exception with no module-level cycle.

A test (`tests/test_studio.py`) enforces that no `jarabe` (Sugar
shell) module is ever imported: the studio depends on the Sugar
*toolkit* only.

## How generated code is accepted

Provider code passes through three gates before a learner sees it:

1. **Static validation** (`validator.py`) — structure, safety, and
   request-specific quality checks. Errors reject the attempt;
   warnings ride along as "Also consider" hints on retries.
2. **Runtime gate** (`runtime_check.py` + `runtime_harness.py`) —
   the candidate actually runs in a sandboxed GTK subprocess on the
   preview stubs: start, pump events, Journal write/read round-trip.
   Crashes, degraded startup, or a blocking `__init__` become retry
   feedback for the model. Skipped without a display;
   `AOD_RUNTIME_CHECK=off` disables, `AOD_RUNTIME_CHECK_TIMEOUT`
   tunes the limit (default 25 s).
3. **Critic round** (`critic.py`) — the model reviews its own
   accepted code once against a checklist (wired handlers, reachable
   win logic, real Journal state) and replies `OK` or minimal
   SEARCH/REPLACE fixes. Patched code must re-pass gates 1 and 2 or
   the original is kept. `AOD_CRITIC=off` disables.

Outcomes are recorded in the saved plan under `runtime_check` and
`critic`.

The activity's icon comes from the model too (`icons.py`): one
`generate_text` call returns a 55x55 SVG on Sugar's color entities,
strictly sanitized (no scripts, images, text, gradients, or external
references; the canonical entity header is re-applied).  Anything
doubtful falls back to the deterministic template/category glyph.
`AOD_AI_ICON=off` disables; the outcome is recorded under
`icon_source`.

## Correspondence with the Sugar shell fork

The same experience runs embedded in the
[Sugar fork](https://github.com/Ashutoshx7/sugar) (`aod-activity-on-demand`
branch), which keeps flat module names. When porting changes between
the two:

| Sugar fork (`src/jarabe/…`) | Studio |
|---|---|
| `model/aodspec.py` | `core/spec.py` |
| `model/aodlicenses.py` | `core/licenses.py` |
| `model/aodprojects.py` | `core/projects.py` |
| `model/aodllm.py` | `llm/providers.py` |
| `model/aodcredentials.py` | `llm/credentials.py` |
| `model/aodenhance.py` | `llm/enhance.py` |
| `model/aodpipeline.py` | `generation/pipeline.py` |
| `model/aodgenerator.py` | `generation/generator.py` |
| `model/aodcodegen.py` | `generation/codegen.py` |
| `model/aodprompts.py` | `generation/prompts.py` |
| `model/aodrag.py` | `generation/rag.py` |
| `model/aodrefine.py` | `generation/refine.py` |
| `model/aodvalidator.py` | `generation/validator.py` |
| `model/aodruntime.py` | `generation/runtime_check.py` |
| `model/aodruntimeharness.py` | `generation/runtime_harness.py` |
| `model/aodcritic.py` | `generation/critic.py` |
| `model/aodicons.py` | `generation/icons.py` |
| `model/aodtemplates.py` | `generation/templates.py` |
| `model/aodservice.py` | `service/service.py` |
| `model/aodjobs.py` | `service/jobs.py` |
| `model/aodqueue.py` | `service/queue.py` |
| `model/aodsessions.py` | `service/sessions.py` |
| `model/aodflatpak.py` | `exports/flatpak.py` |
| `model/aodpreview.py` | `preview/runner.py` |
| `desktop/homebox.py` (panel part) | `ui/panel.py` (+ `ring.py`, `theme.py`) |
