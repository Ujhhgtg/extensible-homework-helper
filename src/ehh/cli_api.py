#!/usr/bin/env python
# -*- coding: utf-8 -*-


import json
import shlex
from typing import Optional

import httpx
from prompt_toolkit import PromptSession
from prompt_toolkit.shortcuts import choice
from prompt_toolkit.shortcuts import CompleteStyle
from rich import traceback

from .models.homework_record import HomeworkRecord
from .models.ai_client import AIClient
from .models.credentials import Credentials
from .models.api.token import Token
from .utils.api.constants import *
from .utils.constants import COMPLETION_WORD_MAP
from .utils.logging import (
    print,
    print_and_copy_path,
    patch_whisper_transcribe_progress,
)
from .utils.convert import try_parse_int
from .utils.crypto import encodeb64_safe
from .utils.prompt import ReplCompleter, prompt_for_yn
from .utils.config import load_config, save_config, migrate_config_if_needed
from .utils.context.impl.api_context import APIContext
from .utils.context.impl.console_messenger import ConsoleMessenger
from .utils.fs import CACHE_DIR
from .tasks_api import *
from . import globalvars


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
                _hw_list = get_hw_list(token)
                if _hw_list is None:
                    print("<error> failed to retrieve homework list")
                else:
                    hw_list = _hw_list
                    print_hw_list(hw_list)
        else:
            print(
                f"<warning> default credentials index {sel_index} out of range; resetting default creds and not logging in"
            )
            globalvars.context.config.credentials.selected = None
    else:
        print(f"<warning> no default credentials provided; not logging in")

    print("--- entering interactive mode ---")
    while True:
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
                        "  answers - fill in/download (from paper)/generate/submit answers for a homework item"
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

                            print(get_text(token, hw_list[index]))
                        case "download":
                            if token is None:
                                print("<error> not logged in; cannot download text")
                                continue

                            download_text(token, hw_list[index])
                        case _:
                            print("<error> argument invalid")

                case "answers":
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
                        case "fill_in":
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
                                    start_hw(token, hw_list[index])

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
                                except Exception:
                                    print("<error> invalid correct rate input")
                                    continue
                                if (
                                    not (0.0 <= expected_correct_rate <= 1.0)
                                    or expected_correct_rate is None
                                ):
                                    print("<error> correct rate out of range")
                                    continue
                            fill_in_answers(
                                token, hw_list[index], answers, expected_correct_rate
                            )

                        case "download":
                            if token is None:
                                print("<error> not logged in; cannot retrieve answers")
                                continue

                            answers = get_answers(token, hw_list[index])
                            if answers is None:
                                print(
                                    "<error> no answers retrieved; cannot save to file"
                                )
                                continue

                            answers_file = (
                                CACHE_DIR
                                / f"homework_{encodeb64_safe(hw_list[index].title)}_answers.json"
                            )
                            with open(answers_file, "wt", encoding="utf-8") as f:
                                f.write(
                                    json.dumps(answers, indent=4, ensure_ascii=False)
                                )
                            print_and_copy_path(answers_file)

                        case "download_from_paper":
                            if token is None:
                                print("<error> not logged in; cannot retrieve answers")
                                continue

                            answers = get_paper_answers(token, hw_list[index])
                            if answers is None:
                                print(
                                    "<error> no answers retrieved; cannot save to file"
                                )
                                continue

                            answers_file = (
                                CACHE_DIR
                                / f"homework_{encodeb64_safe(hw_list[index].title)}_answers_paper.json"
                            )
                            with open(answers_file, "wt", encoding="utf-8") as f:
                                f.write(
                                    json.dumps(answers, indent=4, ensure_ascii=False)
                                )
                            print_and_copy_path(answers_file)

                        case "generate":
                            if ai_client is None:
                                print("<error> no ai client selected")
                                continue

                            if token is None:
                                print(
                                    "<warning> not logged in, cannot determine whether hw has audio"
                                )
                                has_audio_manual = prompt_for_yn(
                                    session, "hw has audio? "
                                )
                            else:
                                has_audio_manual = None

                            answers = generate_answers(
                                token, hw_list[index], ai_client, has_audio_manual
                            )
                            if answers is None:
                                print("<error> failed to generate answers")
                                continue

                            answers_file = (
                                CACHE_DIR
                                / f"homework_{encodeb64_safe(hw_list[index].title)}_answers_gen.json"
                            )
                            with open(answers_file, "wt", encoding="utf-8") as f:
                                f.write(
                                    json.dumps(answers, indent=4, ensure_ascii=False)
                                )
                            print_and_copy_path(answers_file)

                        case "submit":
                            if token is None:
                                print("<error> not logged in; cannot submit homework")
                                continue

                            submit_answers(token, hw_list[index])

                        case "start":
                            if token is None:
                                print("<error> not logged in; cannot start homework")
                                continue

                            start_hw(token, hw_list[index])
                            _hw_list = get_hw_list(token)
                            if _hw_list is None:
                                print("<error> failed to retrieve homework list")
                                continue
                            hw_list = _hw_list

                        case _:
                            print("<error> argument invalid")

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
                            )  # type: ignore
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
                                )  # type: ignore
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
                                )  # type: ignore
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

        except Exception as e:
            print("<error> an unexpected error occurred:")
            globalvars.context.messenger.send_exception(e)


if __name__ == "__main__":
    main()
