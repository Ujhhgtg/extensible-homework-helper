#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
from typing import Optional

import httpx
from munch import Munch
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from . import globalvars
from .models.ai_client import AIClient
from .models.credentials import Credentials
from .models.homework_record import HomeworkRecord
from .models.homework_status import HomeworkStatus
from .models.token import Token
from .tasks import (
    download_audio,
    download_text_content,
    generate_answers,
    get_answers,
    get_hw_list,
    get_paper_answers,
    login,
    start_hw,
    submit_answers,
    transcribe_audio,
)
from .utils.config import load_config, migrate_config_if_needed, save_config
from .utils.constants import BASE_URL
from .utils.context.impl.api_context import APIContext
from .utils.context.impl.console_messenger import ConsoleMessenger
from .utils.context.impl.telegram_messenger import TelegramMessenger
from .utils.crypto import encodeb64_safe
from .utils.fs import CACHE_DIR
from .utils.logging import print

hw_list: list[HomeworkRecord] = []
token: Optional[Token] = None
config: Munch = None


def _ensure_hw_list() -> bool:
    global hw_list, token
    if token is None:
        return False
    if not hw_list:
        hw_list = get_hw_list(token) or []
    return len(hw_list) > 0


def _get_ai_client_from_config() -> Optional[AIClient]:
    sel = getattr(config.ai_client, "selected", None)
    if isinstance(sel, int) and 0 <= sel < len(config.ai_client.all):
        return AIClient.from_dict(config.ai_client.all[sel])
    return None


async def command_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global hw_list, token

    if not isinstance(globalvars.context.messenger, TelegramMessenger):
        globalvars.context = APIContext(
            messenger=TelegramMessenger(
                bot=context.bot, chat_id=update.effective_chat.id
            ),
            http_client=httpx.Client(base_url=BASE_URL),
        )

    if token is None:
        print("<error> not logged in; cannot retrive homework list")
        return

    hw_list = get_hw_list(token)
    if not hw_list:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="No homework items found.",
        )
        return

    message_lines = ["*📚 Homework List 📋*"]

    for i, hw in enumerate(hw_list):
        status_text = hw.status.value if hw.status else "Unknown"
        if hw.status == HomeworkStatus.COMPLETED:
            status_emoji = "✅"
        elif (
            hw.status == HomeworkStatus.NOT_COMPLETED
            or hw.status == HomeworkStatus.MAKE_UP
            or hw.status == HomeworkStatus.IN_PROGRESS
        ):
            status_emoji = "⏳"
        else:
            status_emoji = "❓"

        # Escape characters for MarkdownV2 minimally
        safe_title = (
            hw.title.replace("-", "\\-").replace(".", "\\.").replace("_", "\\_")
        )
        status_score_info = (
            f"Status: `{status_text}` \\| Score: `{hw.current_score}/{hw.total_score}`"
        )

        message_lines.append(
            f"{i+1}\\. {status_emoji} `{safe_title}`\n    {status_score_info}"
        )

    message = "\n\n".join(message_lines)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
        parse_mode="MarkdownV2",
    )


async def command_download_audio(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    global hw_list, token

    chat_id = update.effective_chat.id

    if token is None:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Not logged in; cannot download audio.",
        )
        return

    if not context.args:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Please provide a homework index after the command, e.g., /download_audio 1",
        )
        return

    try:
        idx = int(context.args[0]) - 1
    except ValueError:
        await context.bot.send_message(chat_id=chat_id, text="Invalid index.")
        return

    if not _ensure_hw_list():
        await context.bot.send_message(
            chat_id=chat_id, text="No homework items available."
        )
        return

    if idx < 0 or idx >= len(hw_list):
        await context.bot.send_message(
            chat_id=chat_id, text=f"Index out of range: {idx+1}"
        )
        return

    record = hw_list[idx]

    try:
        download_audio(token, record)
    except Exception as e:
        await context.bot.send_message(
            chat_id=chat_id, text=f"Failed to download audio: {e}"
        )
        return

    audio_path = CACHE_DIR / f"homework_{encodeb64_safe(record.title)}_audio.mp3"
    if not audio_path.exists():
        await context.bot.send_message(
            chat_id=chat_id, text="Audio file not found after download."
        )
        return

    await context.bot.send_message(
        chat_id=chat_id, text=f"Audio for homework '{record.title}' downloaded."
    )
    await context.bot.send_audio(
        chat_id=chat_id,
        audio=audio_path,
        caption=f"Audio: {record.title}",
    )


async def command_transcribe_audio(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    global hw_list, token

    if not context.args:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Provide homework index, e.g. /transcribe_audio 1",
        )
        return

    try:
        idx = int(context.args[0]) - 1
    except ValueError:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Invalid index."
        )
        return

    if not _ensure_hw_list():
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="No homework items available."
        )
        return

    if idx < 0 or idx >= len(hw_list):
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=f"Index out of range: {idx+1}"
        )
        return

    record = hw_list[idx]
    audio_file = CACHE_DIR / f"homework_{encodeb64_safe(record.title)}_audio.mp3"
    if not audio_file.exists():
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Audio file not found; please /download_audio first.",
        )
        return

    try:
        transcribe_audio(record)
    except Exception as e:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=f"Transcription failed: {e}"
        )
        return

    txt_path = audio_file.with_suffix(audio_file.suffix + ".txt")
    if txt_path.exists():
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=f"Transcription saved: {txt_path}"
        )
        await context.bot.send_document(
            chat_id=update.effective_chat.id, document=open(str(txt_path), "rb")
        )
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Transcription file not found after transcribe.",
        )


async def command_download_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    global hw_list, token

    if token is None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Not logged in; cannot download text.",
        )
        return
    if not context.args:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Provide homework index, e.g. /download_text 1",
        )
        return
    try:
        idx = int(context.args[0]) - 1
    except ValueError:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Invalid index."
        )
        return
    if not _ensure_hw_list():
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="No homework items."
        )
        return
    if idx < 0 or idx >= len(hw_list):
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=f"Index out of range: {idx+1}"
        )
        return
    record = hw_list[idx]
    try:
        download_text_content(token, record)
    except Exception as e:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=f"Failed to download text: {e}"
        )
        return
    txt_path = CACHE_DIR / f"homework_{encodeb64_safe(record.title)}_text.txt"
    if txt_path.exists():
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=open(str(txt_path), "rb"),
            caption=f"Text: {record.title}",
        )
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Text file not found after download."
        )


async def command_download_answers(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    global hw_list, token

    if token is None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Not logged in; cannot retrieve answers.",
        )
        return
    if not context.args:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Provide homework index, e.g. /download_answers 1",
        )
        return
    try:
        idx = int(context.args[0]) - 1
    except ValueError:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Invalid index."
        )
        return
    if not _ensure_hw_list():
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="No homework items."
        )
        return
    if idx < 0 or idx >= len(hw_list):
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=f"Index out of range: {idx+1}"
        )
        return
    record = hw_list[idx]
    answers = get_answers(token, record)
    if answers is None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="No answers retrieved."
        )
        return
    answers_file = CACHE_DIR / f"homework_{encodeb64_safe(record.title)}_answers.json"
    answers_file.write_text(
        json.dumps(answers, indent=4, ensure_ascii=False), encoding="utf-8"
    )
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=open(str(answers_file), "rb"),
        caption=f"Answers: {record.title}",
    )


async def command_download_answers_paper(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    global hw_list, token

    if token is None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Not logged in; cannot retrieve answers.",
        )
        return
    if not context.args:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Provide homework index, e.g. /download_answers_paper 1",
        )
        return
    try:
        idx = int(context.args[0]) - 1
    except ValueError:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Invalid index."
        )
        return
    if not _ensure_hw_list():
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="No homework items."
        )
        return
    if idx < 0 or idx >= len(hw_list):
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=f"Index out of range: {idx+1}"
        )
        return
    record = hw_list[idx]
    answers = get_paper_answers(token, record)
    if answers is None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="No answers retrieved."
        )
        return
    answers_file = (
        CACHE_DIR / f"homework_{encodeb64_safe(record.title)}_answers_paper.json"
    )

    answers_file.write_text(
        json.dumps(answers, indent=4, ensure_ascii=False), encoding="utf-8"
    )
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=open(str(answers_file), "rb"),
        caption=f"Paper Answers: {record.title}",
    )


async def command_generate_answers(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    global hw_list, token

    if not context.args:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Provide homework index, e.g. /generate_answers 1",
        )
        return
    try:
        idx = int(context.args[0]) - 1
    except ValueError:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Invalid index."
        )
        return
    ai_client = _get_ai_client_from_config()
    if ai_client is None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="No AI client configured in config."
        )
        return
    if not _ensure_hw_list():
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="No homework items."
        )
        return
    if idx < 0 or idx >= len(hw_list):
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=f"Index out of range: {idx+1}"
        )
        return
    record = hw_list[idx]
    # if token not present, we cannot auto-detect audio; ask user via argument 'has_audio=yes'
    has_audio_manual = None
    if token is None:
        if len(context.args) > 1 and context.args[1].lower() in (
            "yes",
            "y",
            "true",
            "1",
        ):
            has_audio_manual = True
        else:
            has_audio_manual = False
    answers = generate_answers(token, record, ai_client, has_audio_manual)
    if answers is None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Failed to generate answers."
        )
        return
    answers_file = (
        CACHE_DIR / f"homework_{encodeb64_safe(record.title)}_answers_gen.json"
    )

    answers_file.write_text(
        json.dumps(answers, indent=4, ensure_ascii=False), encoding="utf-8"
    )
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=open(str(answers_file), "rb"),
        caption=f"Generated Answers: {record.title}",
    )


async def command_submit_answers(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    global hw_list, token

    if token is None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Not logged in; cannot submit homework.",
        )
        return
    if not context.args:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Provide homework index, e.g. /submit_answers 1",
        )
        return
    try:
        idx = int(context.args[0]) - 1
    except ValueError:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Invalid index."
        )
        return
    if not _ensure_hw_list():
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="No homework items."
        )
        return
    if idx < 0 or idx >= len(hw_list):
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=f"Index out of range: {idx+1}"
        )
        return
    record = hw_list[idx]
    submit_answers(token, record)
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=f"Submit attempted for: {record.title}"
    )


async def command_start_hw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global hw_list, token

    if token is None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Not logged in; cannot start homework.",
        )
        return
    if not context.args:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Provide homework index, e.g. /start_hw 1",
        )
        return
    try:
        idx = int(context.args[0]) - 1
    except ValueError:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Invalid index."
        )
        return
    if not _ensure_hw_list():
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="No homework items."
        )
        return
    if idx < 0 or idx >= len(hw_list):
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=f"Index out of range: {idx+1}"
        )
        return
    record = hw_list[idx]
    start_hw(token, record)
    # refresh list
    new_list = get_hw_list(token)
    if new_list:
        hw_list = new_list
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=f"Started homework: {record.title}"
    )


async def command_account_login(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    global token, hw_list
    # usage: /account_login [index]
    sel_index = None
    if context.args:
        try:
            sel_index = int(context.args[0])
        except ValueError:
            await context.bot.send_message(
                chat_id=update.effective_chat.id, text="Invalid index."
            )
            return
    cred_obj = None
    sel = getattr(config.credentials, "selected", None)
    if isinstance(sel, int) and 0 <= sel < len(config.credentials.all):
        cred_obj = Credentials.from_dict(config.credentials.all[sel])
    elif sel_index is not None and 1 <= sel_index <= len(config.credentials.all):
        cred_obj = Credentials.from_dict(config.credentials.all[sel_index - 1])
    elif len(config.credentials.all) > 0:
        cred_obj = Credentials.from_dict(config.credentials.all[0])
    if cred_obj is None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="No credentials configured."
        )
        return
    token = login(cred_obj)
    if token is None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Login failed."
        )
        return
    hw_list = get_hw_list(token) or []
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=f"Logged in as: {cred_obj.describe()}"
    )


async def command_account_logout(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    global token, hw_list
    token = None
    hw_list = []
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Logged out.")


async def command_ai_select_api(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    global hw_list, token

    # usage: /ai_select_api <index|none>
    if not context.args:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Provide ai index or 'none', e.g. /ai_select_api 1",
        )
        return
    arg = context.args[0].lower()
    if arg == "none":
        config.ai_client.selected = None
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="AI features disabled."
        )
        return
    try:
        idx = int(arg)
    except ValueError:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Invalid index."
        )
        return
    if idx < 1 or idx > len(config.ai_client.all):
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Index out of range."
        )
        return
    config.ai_client.selected = idx - 1
    save_config(config)
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=f"Selected AI client index: {idx}"
    )


async def command_ai_select_model(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    global hw_list, token

    # usage: /ai_select_model <model_index>
    ai_client = _get_ai_client_from_config()
    if ai_client is None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="No AI client configured."
        )
        return
    if not context.args:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Provide model index, e.g. /ai_select_model 1",
        )
        return
    try:
        midx = int(context.args[0])
    except ValueError:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Invalid model index."
        )
        return
    if midx < 1 or midx > len(ai_client.models):
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Model index out of range."
        )
        return
    # update config stored client
    selected_conf = config.ai_client.all[config.ai_client.selected]
    selected_conf["model"]["selected"] = midx - 1
    save_config(config)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"Selected model index {midx} for AI client.",
    )


async def command_config_reload(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    global config

    config = load_config()
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text="Config reloaded."
    )


async def command_config_save(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    save_config(config)
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text="Config saved."
    )


def main():
    global globalvars, token, config

    print("--- step: start telegram bot ---")

    globalvars.context = APIContext(
        messenger=ConsoleMessenger(),
        http_client=httpx.Client(base_url=BASE_URL),
    )

    migrate_config_if_needed()
    config = load_config()
    token = None
    try:
        sel = config.credentials.selected
        cred_obj = None
        if isinstance(sel, int) and 0 <= sel < len(config.credentials.all):
            cred_obj = Credentials.from_dict(config.credentials.all[sel])
        elif len(config.credentials.all) > 0:
            cred_obj = Credentials.from_dict(config.credentials.all[0])

        if cred_obj is not None:
            token = login(cred_obj)
            if token is None:
                print("<warning> telegram bot: login failed with provided credentials")
            else:
                print("<info> telegram bot: logged in to school API")
    except Exception as e:
        print(f"<warning> telegram bot: login attempt failed: {e}")

    telegram_token = getattr(config, "telegram_bot_token", None)
    if not telegram_token:
        print("<error> no telegram bot token configured; aborting")
        return

    application = Application.builder().token(telegram_token).build()

    # basic functionality
    application.add_handler(CommandHandler("list", command_list))
    application.add_handler(CommandHandler("download_audio", command_download_audio))
    application.add_handler(
        CommandHandler("transcribe_audio", command_transcribe_audio)
    )
    application.add_handler(CommandHandler("download_text", command_download_text))

    # answers
    application.add_handler(
        CommandHandler("download_answers", command_download_answers)
    )
    application.add_handler(
        CommandHandler("download_answers_paper", command_download_answers_paper)
    )
    application.add_handler(
        CommandHandler("generate_answers", command_generate_answers)
    )
    application.add_handler(CommandHandler("submit_answers", command_submit_answers))
    application.add_handler(CommandHandler("start_hw", command_start_hw))

    # account / ai / config
    application.add_handler(CommandHandler("account_login", command_account_login))
    application.add_handler(CommandHandler("account_logout", command_account_logout))
    application.add_handler(CommandHandler("ai_select_api", command_ai_select_api))
    application.add_handler(CommandHandler("ai_select_model", command_ai_select_model))
    application.add_handler(CommandHandler("config_reload", command_config_reload))
    application.add_handler(CommandHandler("config_save", command_config_save))

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
