# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the interactive REPL
ehh-repl          # after install
just r            # alias

# Run the Telegram bot
ehh-tgbot

# Lint
uv run ruff check src/
uv run ruff format src/

# Build wheel
just build        # → dist/ehh-0.0.1-py3-none-any.whl

# Install locally (picks up edits on reinstall)
just install      # uv tool install .
```

There are no tests. Use `ruff` for all linting and formatting.

## Architecture

The project automates homework workflows on the 简练英语平台 (`gateway.jeedu.net` API).

### Layers

**`tasks.py`** — all API calls and business logic. Functions are stateless; they receive `token` / `record` / `client` as arguments and call `globalvars.context.*` for I/O.

**`repl.py`** — interactive REPL (`main()`). Parses shell-like commands with `shlex`, dispatches to `tasks.py` functions, handles all user prompts. This is the only place that calls `session.prompt()`.

**`telegram_bot.py`** — Telegram bot frontend; calls the same `tasks.py` functions.

**`globalvars.py`** — single global `context: Context` set at startup; avoids threading context through every call.

### Context / Messenger pattern

`utils/context/base.py` defines two abstract classes:
- `Context` — holds `http_client`, `config` (Munch), and optionally `whisper_model`.
- `Messenger` — `send_text / send_table / send_progress / send_exception`.

Implementations in `utils/context/impl/`: `APIContext` (REPL), `ConsoleMessenger`, `TelegramMessenger`, `TextualMessenger`. This lets `tasks.py` remain frontend-agnostic.

### Models (`models/`)

| File | Purpose |
|---|---|
| `HomeworkRecord` | One assignment row: id, title, kind, status, scores, publish time |
| `HomeworkKind` | `QUESTIONS` (radio/text paper) or `TRANSLATION` (sentence task) |
| `HomeworkStatus` | API integer → enum (NOT_COMPLETED, COMPLETED, MAKE_UP, …) |
| `Token` | OAuth bearer token + `UserInfo` |
| `AIClient` | OpenAI-compatible client wrapper; holds model list and selected index |

### Answer kinds

`_get_answer_kind(tagId)` in `tasks.py` classifies by `tagId` prefix:
- `radio*` → `"choice"` (single A–D letter, **but** 听说训练 assignments use compound `B#B#C#B#B` format — these are excluded from any answer-flipping via `_is_flippable_choice()`)
- `text*` → `"fill-in-blanks"` (may be a `/`-separated list of acceptable answers)
- numeric → `"speaking"` (TTS-synthesized via edge-tts, uploaded as mp3)

### Config

YAML config loaded into a `Munch` (attribute-access). Stored at the platform config dir (`platformdirs`). Migration from a local `config.yaml` is handled automatically by `migrate_config_if_needed()`. Credentials and AI client settings support multiple entries with a `selected` index.

### REPL command structure

```
answers <sub> <spec>
```
- `spec` accepts comma-separated indices and inclusive ranges: `0-1,3,5,7-9`
- `fill_in` — single index only; prompts for an answers JSON file and a correctness spec
- `complete` — full pipeline (get paper answers → TTS speaking → upload → saveCache); prompts for a correctness spec applied independently per assignment
- `submit` — submits cached answers
- Correctness spec formats: `0.8` (rate), `8` (correct count), `-2` (wrong count), `rand(1,5)` / `rand(-5,-1)` / `rand(0.5,0.9)` (random range, both bounds same kind)

### API flow for a QUESTIONS homework

1. `start_hw` — mark as started
2. `get_paper_answers` — fetch paper, extract `tagId + answer` per question
3. `_upload_speaking_clips` — TTS-synthesize + upload mp3 for speaking questions
4. `_build_answers_payload` — assemble saveCache payload
5. `_save_answers_cache_payload` — POST to `saveCache`
6. `submit_answers` (optional) — POST to `userTaskSubmit`

TRANSLATION homework uses a separate endpoint and goes through `generate_translation_answers` (LLM) → `submit_translation`.
