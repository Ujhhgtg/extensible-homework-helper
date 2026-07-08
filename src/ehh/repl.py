#!/usr/bin/env python
# -*- coding: utf-8 -*-


import json
import re
import shlex
from typing import Optional

import httpx
from prompt_toolkit import PromptSession
from prompt_toolkit.shortcuts import choice
from rich import traceback

from . import globalvars
from .models.ai_client import AIClient
from .models.credentials import Credentials
from .models.homework_kind import HomeworkKind
from .models.homework_record import HomeworkRecord
from .models.homework_status import HomeworkStatus
from .models.token import Token
from .tasks import (
    complete_homework,
    download_audio,
    download_text_content,
    fill_in_answers,
    fill_in_speaking_answers,
    generate_answers,
    generate_speaking_audio,
    get_answers,
    get_hw_list,
    get_paper_answers,
    get_text_content,
    login,
    print_hw_list,
    start_hw,
    submit_answers,
    transcribe_audio,
)
from .utils.config import load_config, migrate_config_if_needed, save_config
from .utils.constants import BASE_URL, COMPLETION_WORD_MAP
from .utils.context.impl.api_context import APIContext
from .utils.context.impl.console_messenger import ConsoleMessenger
from .utils.convert import parse_index_ranges, try_parse_int
from .utils.crypto import encodeb64_safe
from .utils.fs import CACHE_DIR
from .utils.logging import patch_whisper_transcribe_progress, print, print_and_copy_path
from .utils.prompt import ReplCompleter, prompt_for_yn


def _filename_stem(hw: HomeworkRecord, use_title: bool) -> str:
    """Cache-file stem for a homework item: the human-readable (sanitized) title
    when use_title is set, otherwise the url-safe encoded title."""
    if use_title:
        # strip characters unsafe for filenames; keep it readable
        return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", hw.title).strip() or encodeb64_safe(
            hw.title
        )
    return encodeb64_safe(hw.title)


def _run_answers_item(
    sub: str,
    hw: HomeworkRecord,
    token: Optional[Token],
    ai_client: Optional[AIClient],
    session: PromptSession,
    use_title: bool = False,
) -> bool:
    """Execute a batch-friendly `answers <sub>` action on one homework item.

    Returns True if the homework list should be refreshed afterward (i.e. `start`).
    """
    match sub:
        case "download":
            if token is None:
                print("<error> not logged in; cannot retrieve answers")
                return False

            answers = get_answers(token, hw)
            if answers is None:
                print("<error> no answers retrieved; cannot save to file")
                return False

            answers_file = (
                CACHE_DIR / f"homework_{_filename_stem(hw, use_title)}_answers.json"
            )
            with open(answers_file, "wt", encoding="utf-8") as f:
                f.write(json.dumps(answers, indent=4, ensure_ascii=False))
            print_and_copy_path(answers_file)

        case "download_from_paper":
            if token is None:
                print("<error> not logged in; cannot retrieve answers")
                return False

            answers = get_paper_answers(token, hw)
            if answers is None:
                print("<error> no answers retrieved; cannot save to file")
                return False

            answers_file = (
                CACHE_DIR
                / f"homework_{_filename_stem(hw, use_title)}_answers_paper.json"
            )
            with open(answers_file, "wt", encoding="utf-8") as f:
                f.write(json.dumps(answers, indent=4, ensure_ascii=False))
            print_and_copy_path(answers_file)

        case "generate":
            if ai_client is None:
                print("<error> no ai client selected")
                return False

            if token is None:
                print(
                    "<warning> not logged in, cannot determine whether hw has audio"
                )
                has_audio_manual = prompt_for_yn(session, "hw has audio? ")
            else:
                has_audio_manual = None

            answers = generate_answers(token, hw, ai_client, has_audio_manual)
            if answers is None:
                print("<error> failed to generate answers")
                return False

            answers_file = (
                CACHE_DIR / f"homework_{encodeb64_safe(hw.title)}_answers_gen.json"
            )
            with open(answers_file, "wt", encoding="utf-8") as f:
                f.write(json.dumps(answers, indent=4, ensure_ascii=False))
            print_and_copy_path(answers_file)

        case "generate_speaking":
            if token is None:
                print("<error> not logged in; cannot generate speaking audio")
                return False

            clips = generate_speaking_audio(token, hw)
            if clips is None:
                print("<error> failed to generate speaking audio")
                return False
            if not clips:
                print("<info> no speaking questions in this item")
                return False
            for clip in clips:
                print(f"<info> Q{clip['index']} -> {clip['path']}")

        case "fill_in_speaking":
            if token is None:
                print("<error> not logged in; cannot fill in speaking answers")
                return False

            if hw.status in [
                HomeworkStatus.NOT_COMPLETED,
                HomeworkStatus.MAKE_UP,
            ]:
                should_start = prompt_for_yn(
                    session,
                    "homework not completed or needs makeup; start it now? ",
                )
                if should_start:
                    start_hw(token, hw)

            # never auto-submit here; user reviews and submits manually
            fill_in_speaking_answers(token, hw, submit=False)

        case "start":
            if token is None:
                print("<error> not logged in; cannot start homework")
                return False

            start_hw(token, hw)
            return True

        case _:
            print("<error> argument invalid")

    return False


def main():
    globalvars.context = APIContext(
        messenger=ConsoleMessenger(), http_client=httpx.Client(base_url=BASE_URL)
    )

    print("--- extensible homework helper ---")
    print("--- by: ujhhgtg ---")
    print("--- github: https://github.com/Ujhhgtg/extensible-homework-helper ---")

    print("--- step: initialize ---")
    traceback.install()
    print("<info> rich traceback installed")
    migrate_config_if_needed()
    globalvars.context.config = load_config()
    print("<info> loaded config file")
    patch_whisper_transcribe_progress()
    print("<info> patched whisper.transcribe to use rich console")

    hw_list: list[HomeworkRecord] = []
    session: PromptSession = PromptSession()
    ai_client: Optional[AIClient] = None
    token: Optional[Token] = None

    if globalvars.context.config.ai_client.selected is not None:
        sel_index = globalvars.context.config.ai_client.selected
        if 0 <= sel_index < len(globalvars.context.config.ai_client.all):
            ai_client = AIClient.from_dict(
                globalvars.context.config.ai_client.all[sel_index]
            )
            print(f"<info> using default AI client at index {sel_index}")
        else:
            print(
                f"<warning> default AI client index {sel_index} out of range; falling back to no AI client"
            )

    if globalvars.context.config.credentials.selected is not None:
        sel_index = globalvars.context.config.credentials.selected
        if 0 <= sel_index < len(globalvars.context.config.credentials.all):
            cred = Credentials.from_dict(
                globalvars.context.config.credentials.all[sel_index]
            )
            token = login(cred)
            if token is None:
                print(
                    f"<error> login with default credentials at index {sel_index} failed"
                )
            else:
                print(
                    f"<info> using default credentials at index {sel_index}: {cred.describe()}"
                )
        else:
            print(
                f"<warning> default credentials index {sel_index} out of range; resetting default creds and not logging in"
            )
            globalvars.context.config.credentials.selected = None
    else:
        print("<warning> no default credentials provided; not logging in")

    print("--- entering interactive mode ---")
    while True:
        if token is not None:
            _hw_list = get_hw_list(token)
            if _hw_list is None:
                print("<error> failed to retrieve homework list")
            else:
                print("<info> updated homework list")
                hw_list = _hw_list

        user_input = (
            session.prompt(
                "ehh> ",
                completer=ReplCompleter(COMPLETION_WORD_MAP),
            )
            .strip()
            .lower()
        )
        input_parts = shlex.split(user_input)
        if len(input_parts) <= 0:
            continue

        try:
            match input_parts[0]:
                case "help":
                    print("available commands:")
                    print("  audio - download/transcribe audio of a homework item")
                    print("  text - display/download text content of a homework item")
                    print(
                        "  answers <sub> <spec> - fill in (single index only)/download/download_from_paper/generate/generate_speaking/fill_in_speaking/complete/submit/start"
                    )
                    print(
                        "  <spec> accepts a single index, comma-separated indices, and inclusive ranges, e.g. 0-1,3,5,7-9 (fill_in takes a single index only)"
                    )
                    print(
                        "  answers download|download_from_paper [-h] <spec> - -h names the cache file after the homework title"
                    )
                    print(
                        "  answers complete <spec> - full pipeline for one or more items in order (no submit)"
                    )
                    print(
                        "  answers submit <spec> - submit one or more items in order"
                    )
                    print("  help - show this help message")
                    print("  list - list all homework items")
                    print("  account - login/logout/select default account")
                    print("  ai - select AI client & model")
                    print("  config - reload/save configuration")
                    print("  exit - exit the program")

                case "list":
                    if token is None:
                        print("<error> not logged in; cannot retrieve homework list")
                        continue

                    _hw_list = get_hw_list(token)
                    if _hw_list is None:
                        print("<error> failed to retrieve homework list")
                        continue

                    hw_list = _hw_list
                    print_hw_list(hw_list)

                case "audio":
                    if len(input_parts) < 3:
                        print("<error> argument not enough")
                        continue
                    index = try_parse_int(input_parts[2])
                    if index is None:
                        print("<error> argument invalid")
                        continue

                    if index < 0 or index >= len(hw_list):
                        print(f"<error> index out of range: {index}")
                        continue

                    match input_parts[1]:
                        case "download":
                            if token is None:
                                print("<error> not logged in; cannot download audio")
                                continue

                            download_audio(token, hw_list[index])

                        case "transcribe":
                            audio_file = (
                                CACHE_DIR
                                / f"homework_{encodeb64_safe(hw_list[index].title)}_audio.mp3"
                            )
                            if not audio_file.is_file():
                                print(
                                    f"<error> audio file for index {index} not found; please download it first"
                                )
                                continue
                            transcribe_audio(hw_list[index])
                        case _:
                            print("<error> argument invalid")

                case "text":
                    if len(input_parts) < 3:
                        print("<error> argument not enough")
                        continue
                    index = try_parse_int(input_parts[2])
                    if index is None:
                        print("<error> argument invalid")
                        continue
                    if index < 0 or index >= len(hw_list):
                        print(f"<error> index out of range: {index}")
                        continue

                    match input_parts[1]:
                        case "display":
                            if token is None:
                                print("<error> not logged in; cannot display text")
                                continue

                            print(get_text_content(token, hw_list[index]))
                        case "download":
                            if token is None:
                                print("<error> not logged in; cannot download text")
                                continue

                            download_text_content(token, hw_list[index])
                        case _:
                            print("<error> argument invalid")

                case "answers":
                    if len(input_parts) < 3:
                        print("<error> argument not enough")
                        continue

                    # separate flags (e.g. -h) from the positional index spec.
                    # -h: for download/download_from_paper, name the cache file after
                    # the homework title instead of the encoded id.
                    flags = [p for p in input_parts[2:] if p.startswith("-")]
                    positional = [p for p in input_parts[2:] if not p.startswith("-")]
                    use_title = "-h" in flags
                    if len(positional) == 0:
                        print("<error> no index provided")
                        continue
                    spec = positional[0]

                    # `complete` accepts a comma-separated list of indices and
                    # inclusive ranges, run in order (e.g. "0-1,3,5,7-9").
                    if input_parts[1] == "complete":
                        if token is None:
                            print("<error> not logged in; cannot complete homework")
                            continue

                        indices = parse_index_ranges(spec, len(hw_list))
                        if indices is None:
                            print(
                                f"<error> invalid or out-of-range index spec: {spec!r}"
                            )
                            continue
                        if len(indices) == 0:
                            print("<error> no index provided")
                            continue

                        for pos, idx in enumerate(indices):
                            hw = hw_list[idx]
                            print(
                                f"--- ({pos + 1}/{len(indices)}) completing "
                                f"[{idx}] {hw.title} ---"
                            )
                            # questions must be started first; translations submit
                            # directly without a start call. in full-pipeline
                            # complete mode we start automatically without asking.
                            if hw.kind != HomeworkKind.TRANSLATION and hw.status in [
                                HomeworkStatus.NOT_COMPLETED,
                                HomeworkStatus.MAKE_UP,
                            ]:
                                print(
                                    "<info> homework not completed or needs makeup; starting it"
                                )
                                start_hw(token, hw)
                            # full pipeline; never auto-submit (review + submit manually)
                            complete_homework(
                                token, hw, submit=False, ai_client=ai_client
                            )
                        continue

                    # `submit` also accepts a comma-separated list of indices and
                    # inclusive ranges, submitted in order (e.g. "0-1,3,5,7-9").
                    if input_parts[1] == "submit":
                        if token is None:
                            print("<error> not logged in; cannot submit homework")
                            continue

                        indices = parse_index_ranges(spec, len(hw_list))
                        if indices is None:
                            print(
                                f"<error> invalid or out-of-range index spec: {spec!r}"
                            )
                            continue
                        if len(indices) == 0:
                            print("<error> no index provided")
                            continue

                        for pos, idx in enumerate(indices):
                            hw = hw_list[idx]
                            print(
                                f"--- ({pos + 1}/{len(indices)}) submitting "
                                f"[{idx}] {hw.title} ---"
                            )
                            submit_answers(token, hw)
                        continue

                    # `fill_in` is interactive (per-item file + correct rate prompts),
                    # so it stays single-index only.
                    if input_parts[1] == "fill_in":
                        index = try_parse_int(spec)
                        if index is None or index < 0 or index >= len(hw_list):
                            print(f"<error> invalid or out-of-range index: {spec!r}")
                            continue

                        if token is None:
                            print("<error> not logged in; cannot fill in answers")
                            continue

                        hw = hw_list[index]
                        if hw.status in [
                            HomeworkStatus.NOT_COMPLETED,
                            HomeworkStatus.MAKE_UP,
                        ]:
                            should_start = prompt_for_yn(
                                session,
                                "homework not completed or needs makeup; start it now? ",
                            )
                            if should_start:
                                start_hw(token, hw)

                        answers_input = session.prompt(
                            "answers file (relative path is ok): "
                        ).strip()
                        with open(answers_input, "rt", encoding="utf-8") as f:
                            answers = json.load(f)
                        expected_correct_rate_input = session.prompt(
                            "expected correct rate (0.0-1.0, default 1.0): "
                        ).strip()
                        expected_correct_rate = None
                        if expected_correct_rate_input != "":
                            try:
                                expected_correct_rate = float(
                                    expected_correct_rate_input
                                )
                            except ValueError:
                                print("<error> invalid correct rate input")
                                continue
                            if not (0.0 <= expected_correct_rate <= 1.0):
                                print("<error> correct rate out of range")
                                continue
                        fill_in_answers(token, hw, answers, expected_correct_rate)
                        continue

                    # remaining index-based subcommands accept the advanced spec
                    # (comma-separated indices and inclusive ranges, e.g. "0-1,3,5-9")
                    indices = parse_index_ranges(spec, len(hw_list))
                    if indices is None:
                        print(
                            f"<error> invalid or out-of-range index spec: {spec!r}"
                        )
                        continue
                    if len(indices) == 0:
                        print("<error> no index provided")
                        continue

                    needs_refresh = False
                    for pos, idx in enumerate(indices):
                        hw = hw_list[idx]
                        if len(indices) > 1:
                            print(
                                f"--- ({pos + 1}/{len(indices)}) {input_parts[1]} "
                                f"[{idx}] {hw.title} ---"
                            )
                        if _run_answers_item(
                            input_parts[1], hw, token, ai_client, session, use_title
                        ):
                            needs_refresh = True

                    if needs_refresh and token is not None:
                        _hw_list = get_hw_list(token)
                        if _hw_list is None:
                            print("<error> failed to retrieve homework list")
                        else:
                            hw_list = _hw_list

                case "account":
                    if len(input_parts) < 2:
                        print("<error> argument not enough")
                        continue

                    match input_parts[1]:
                        case "login":
                            options = list(
                                map(
                                    lambda c: (
                                        c[0],
                                        c[1].describe(),
                                    ),
                                    enumerate(
                                        map(
                                            lambda c: Credentials.from_dict(c),
                                            globalvars.context.config.credentials.all,
                                        )
                                    ),
                                )
                            )
                            default = 0
                            if isinstance(
                                globalvars.context.config.credentials.selected, int
                            ):
                                default = globalvars.context.config.credentials.selected
                            cred_choice = choice(
                                "select credentials to use:",
                                options=options,
                                default=default,
                            )
                            cred = Credentials.from_dict(
                                globalvars.context.config.credentials.all[cred_choice]
                            )
                            token = login(cred)
                            if token is None:
                                print("<error> failed to login")
                                continue

                            _hw_list = get_hw_list(token)
                            if _hw_list is None:
                                print("<error> failed to retrieve homework list")

                            print(
                                f"<success> logged in with credentials: {cred.describe()}"
                            )
                        case "logout":
                            token = None
                            print("<success> logged out")

                        case "select_default":
                            options = [("none", "disable auto login")]
                            options.extend(
                                map(
                                    lambda c: (
                                        c[0],
                                        c[1].describe(),
                                    ),
                                    enumerate(
                                        map(
                                            lambda c: Credentials.from_dict(c),
                                            globalvars.context.config.credentials.all,
                                        )
                                    ),
                                )
                            )
                            default = "none"
                            if isinstance(
                                globalvars.context.config.credentials.selected, int
                            ):
                                default = globalvars.context.config.credentials.selected
                            cred_choice = choice(
                                "select default credentials to use:",
                                options=options,
                                default=default,
                            )
                            if cred_choice == "none":
                                globalvars.context.config.credentials.selected = None
                                print("<info> disabled auto login")
                                continue

                            globalvars.context.config.credentials.selected = cred_choice
                            cred = Credentials.from_dict(
                                globalvars.context.config.credentials.all[cred_choice]
                            )
                            print(
                                f"<info> selected default credentials: {cred.describe()}"
                            )
                        case _:
                            print("<error> argument invalid")

                case "ai":
                    if len(input_parts) < 2:
                        print("<error> argument not enough")
                        continue

                    match input_parts[1]:
                        case "select_api":
                            options = [("none", "disable AI features")]
                            options.extend(
                                map(
                                    lambda c: (
                                        c[0],
                                        c[1].describe(),
                                    ),
                                    enumerate(
                                        map(
                                            lambda c: AIClient.from_dict(c),
                                            globalvars.context.config.ai_client.all,
                                        )
                                    ),
                                )
                            )
                            default = "none"
                            if isinstance(
                                globalvars.context.config.ai_client.selected, int
                            ):
                                default = globalvars.context.config.ai_client.selected
                            client_choice = choice(
                                "select AI client to use:",
                                options=options,
                                default=default,
                            )
                            if client_choice == "none":
                                ai_client = None
                                globalvars.context.config.ai_client.selected = None
                                print("<info> AI features disabled")
                                continue

                            ai_client_conf = globalvars.context.config.ai_client.all[
                                client_choice
                            ]
                            ai_client = AIClient.from_dict(ai_client_conf)
                            globalvars.context.config.ai_client.selected = client_choice
                            print(f"<info> selected AI client: {ai_client.describe()}")
                        case "select_model":
                            if ai_client is None:
                                print("<error> no ai client selected")
                                continue

                            options = list(enumerate(ai_client.models))
                            model_choice = choice(
                                "select AI model to use:",
                                options=options,
                                default=ai_client.selected_model_index,
                            )

                            ai_client_conf = next(
                                c
                                for c in globalvars.context.config.ai_client.all
                                if c.api_url == ai_client.api_url
                                and c.api_key == ai_client.api_key
                            )
                            ai_client_conf.model.selected = model_choice
                            ai_client.selected_model_index = model_choice
                            print(
                                f"<info> selected AI model: {ai_client.selected_model}"
                            )
                        case _:
                            print("<error> argument invalid")

                case "config":
                    if len(input_parts) < 2:
                        print("<error> argument not enough")
                        continue

                    match input_parts[1]:
                        case "reload":
                            globalvars.context.config = load_config()
                            print("<info> reloaded config file")
                            print("<info> note: current states are not changed")
                        case "save":
                            save_config(globalvars.context.config)
                            print("<info> saved config to file")
                        case _:
                            print("<error> argument invalid")

                case "exit":
                    print("<info> exiting...")
                    save_config(globalvars.context.config)
                    print("<info> saved config to file")
                    break

                case _:
                    print(f"<error> unrecognized command: '{user_input}'")

        except NotImplementedError:
            print("<error> feature not yet implemented")

        except KeyboardInterrupt:
            print("<warning> interrupted")

        except Exception:
            print("<error> an unexpected error occurred")
            globalvars.context.messenger.send_exception(None)  # type: ignore


if __name__ == "__main__":
    main()
