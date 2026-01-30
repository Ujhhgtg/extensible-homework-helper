import random
import re
import time
from datetime import datetime
from typing import Optional

import json5
import openai
from bs4 import BeautifulSoup

from ehh.models.homework_kind import HomeworkKind

from . import globalvars
from .models.ai_client import AIClient
from .models.credentials import Credentials
from .models.homework_record import HomeworkRecord
from .models.homework_status import HomeworkStatus
from .models.school_info import SchoolInfo
from .models.token import Token
from .models.user_info import UserInfo
from .utils.constants import (
    FIND_SCHOOLS_URL,
    GENERATE_ANSWERS_PROMPT,
    GENERATE_ANSWERS_WITH_LISTENING_PROMPT,
    GENERATE_TRANSLATION_ANSWERS_PROMPT,
    GET_HW_CONTENT_URL,
    GET_HW_DETAILS_URL,
    GET_HW_LIST_URL,
    GET_TOKEN_URL,
    GET_TRANSLATION_HW_CONTENT_URL,
    GET_TRANSLATION_HW_LIST_URL,
    LOAD_ANSWERS_CACHE_URL,
    SAVE_ANSWERS_CACHE_URL,
    START_HW_URL,
    SUBMIT_ANSWERS_URL,
    TIME_FORMAT,
)
from .utils.crypto import encodeb64_safe, get_md5_str_of_str
from .utils.fs import CACHE_DIR, read_file_text
from .utils.logging import download_file_with_progress, print, print_and_copy_path


def _get_status_enum(status_int: int) -> HomeworkStatus:
    for member in HomeworkStatus:
        if member.value[0] == status_int:
            return member

    return HomeworkStatus.UNKNOWN


def _get_school(name: str) -> Optional[SchoolInfo]:
    response = globalvars.context.http_client.post(
        FIND_SCHOOLS_URL, json={"name": name}
    )
    data = response.json()
    if data.get("success", False) is False:
        print(f"<error> find school failed: {data}")
        return None

    schools = data.get("data", [])
    if len(schools) == 0:
        print(f"<error> no school found with name {name}")
        return None
    first_school = schools[0]
    return SchoolInfo(id=first_school["id"], name=first_school["name"])


def login(credentials: Credentials) -> Optional[Token]:
    school = _get_school(credentials.school)
    if school is None:
        print(f"<error> school '{credentials.school}' not found")
        return None

    payload = {
        "username": credentials.username + "|" + str(school.id),
        "password": get_md5_str_of_str(credentials.password),
        "grant_type": "password",
        "client_id": "fyll",
        "client_secret": "fyll2020",
        "randomCode": "",
    }
    response = globalvars.context.http_client.post(GET_TOKEN_URL, params=payload)
    data = response.json()
    if data.get("success", False) is False:
        print(f"<error> login failed: {data}")
        return None

    return Token(
        access_token=data["access_token"],
        type=data["token_type"],
        refresh_token=data["refresh_token"],
        expires_in=data["expires_in"],
        scope=data["scope"],
        jti=data["jti"],
        user_info=UserInfo(
            id=data["userInfo"]["id"],
            username=data["userInfo"]["username"],
            full_name=data["userInfo"]["name"],
            type=int(data["userInfo"]["type"]),
            school=school,
        ),
    )


def _get_headers(token: Token) -> Optional[dict[str, str]]:
    if token.type != "bearer":
        print(
            f"<error> unsupported token kind: {token.type}; supported kind(s) are: bearer"
        )
        return None

    return {
        "Authorization": f"Bearer {token.access_token}",
    }


def _get_all_kind_hw_score(item: dict) -> int:
    score = item.get("score", None)
    if score is None:
        score = item.get("ownerScore", None)
    return score  # type: ignore


def _get_kind_hw_list(
    url: str, headers: dict[str, str], kind: HomeworkKind
) -> list[HomeworkRecord]:
    hw_list: list[HomeworkRecord] = []

    max_page_index = 0
    cur_page_index = 0
    while cur_page_index <= max_page_index:
        response = globalvars.context.http_client.post(
            url,
            headers=headers,
            json={"pageIndex": cur_page_index + 1, "pageSize": 50},
        )
        data = response.json()
        if data.get("success", False) is False:
            print(f"<error> get homework list failed: {data}")
            break

        max_page_index = data["data"]["pageCount"]

        for item in (
            data["data"].get("userTasks", None) or data["data"].get("tasks", None) or []
        ):
            hw_list.append(
                HomeworkRecord(
                    api_id=item["id"],
                    api_task_id=item.get("taskId", None),
                    api_task_paper_id=item.get("taskPaperId", None),
                    api_batch_id=item.get("batchId", None),
                    title=item.get("taskTitle", None) or item.get("title", None),
                    kind=kind,
                    publisher_name=item["assignerName"],
                    # start_time=item["startTime"],
                    # end_time=item["completeTime"],
                    publish_time=datetime.strptime(item["beginTime"], TIME_FORMAT),
                    # due_time=item["endTime"],
                    current_score=_get_all_kind_hw_score(item),
                    # pass_score=0,  # idk which is pass score
                    total_score=item["totalScore"],
                    # is_pass=True,  # idk which is pass condition
                    # teacher_comment=None,  # idk which is teacher comment
                    status=_get_status_enum(int(item["status"])),
                )
            )

        cur_page_index += 1

    return hw_list


def get_hw_list(token: Token) -> Optional[list[HomeworkRecord]]:
    print("--- step: retrieve homework list ---")

    headers = _get_headers(token)
    if headers is None:
        print("<error> authorization failed")
        return None

    hw_list: list[HomeworkRecord] = []

    hw_list.extend(_get_kind_hw_list(GET_HW_LIST_URL, headers, HomeworkKind.QUESTIONS))
    hw_list.extend(
        _get_kind_hw_list(
            GET_TRANSLATION_HW_LIST_URL, headers, HomeworkKind.TRANSLATION
        )
    )
    hw_list.sort(key=lambda r: r.publish_time, reverse=True)

    return hw_list


def _get_hw_details(token: Token, record: HomeworkRecord) -> Optional[dict]:
    headers = _get_headers(token)
    if headers is None:
        print("<error> authorization failed")
        return None

    response = globalvars.context.http_client.post(
        GET_HW_DETAILS_URL,
        headers=headers,
        json={"id": record.api_id},
    )
    data = response.json()
    if data.get("success", False) is False:
        print(f"<error> get homework details failed: {data}")
        return None

    return data.get("data", None)


def get_answers(
    token: Token, record: HomeworkRecord
) -> Optional[list[dict[str, str | int]]]:
    print(f"--- step: retrieve answers for {record.title}")

    headers = _get_headers(token)
    if headers is None:
        print("<error> authorization failed")
        return None

    hw = _get_hw_details(token, record)
    if hw is None:
        print("<error> failed to get homework details")
        return None

    answers = []
    for index, answer in enumerate(hw["subResults"]):
        if answer["tagId"].startswith("radio"):
            answer_type = "choice"
        elif answer["tagId"].startswith("text"):
            answer_type = "fill-in-blanks"
        else:
            answer_type = "unknown"

        answer_content = answer["standardAnswer"]
        if (
            answer_type == "fill-in-blanks"
            and len(answer_content) >= 2
            and "/" in answer_content
        ):
            answer_content = answer_content.split("/")

        answers.append(
            {
                "index": index + 1,
                "type": answer_type,
                "content": answer_content,
            }
        )
        print(
            f"<info> extracted answer {index + 1}: Type='{answer_type}', Content='{answer_content}'"
        )

    return answers


def _get_hw_paper(token: Token, record: HomeworkRecord) -> Optional[dict]:
    headers = _get_headers(token)
    if headers is None:
        print("<error> authorization failed")
        return None

    response = globalvars.context.http_client.post(
        GET_HW_CONTENT_URL,
        headers=headers,
        json={"id": record.api_task_paper_id},
    )
    data = response.json()
    if data.get("success", False) is False:
        print(f"<error> failed to get homework paper: {data}")
        return None

    return data["data"]


def _get_questions(token: Token, record: HomeworkRecord) -> Optional[list[dict]]:
    headers = _get_headers(token)
    if headers is None:
        print("<error> authorization failed")
        return None

    paper = _get_hw_paper(token, record)
    if paper is None:
        return None

    q_list: list[dict] = list(
        map(
            lambda q: {
                "index": q["sort"],  # starts from 1
                "api_id": q["id"],
                "id": q["tagId"],  # attr 'name' of radio and input in web
                "answer": q["answer"],  # bruh so it just returns the answer directly???
                "score": q["score"],
            },
            paper["flows"],
        )
    )

    q_list.sort(key=lambda elem: elem["index"])
    return q_list


def _get_audio_url(token: Token, record: HomeworkRecord) -> Optional[str]:
    print(f"--- step: retrive audio url for '{record.title}' ---")

    paper = _get_hw_paper(token, record)
    if paper is None:
        print("<error> failed to get homework paper")
        return None

    soup = BeautifulSoup(paper["content"], "html.parser")
    audio_tag = soup.find("audio")
    if audio_tag is None:
        print("<warning> audio tag not found in homework paper")
        return None

    return str(audio_tag.get("src"))


def download_audio(token: Token, record: HomeworkRecord) -> None:
    print(f"--- step: download audio for '{record.title}' ---")

    audio_url = _get_audio_url(token, record)
    if audio_url is None:
        print("<error> failed to retrive audio url")
        return

    path = CACHE_DIR / f"homework_{encodeb64_safe(record.title)}_audio.mp3"
    try:
        print(f"<info> downloading audio from: {audio_url}")
        globalvars.context.messenger.send_progress(
            download_file_with_progress, audio_url, path
        )
        print_and_copy_path(path)
    except Exception as download_e:
        print("<error> failed to download audio:")
        globalvars.context.messenger.send_exception(download_e)
        return


WHITESPACE_PATTERN = re.compile(r"[^\S\n]+")


def get_text_content(token: Token, record: HomeworkRecord) -> Optional[str]:
    print(f"--- step: retrieve text content for '{record.title}' ---")

    if record.kind == HomeworkKind.QUESTIONS:
        paper = _get_hw_paper(token, record)
        if paper is None:
            print("<error> failed to get homework paper")
            return None

        soup = BeautifulSoup(paper["content"], "html.parser")
        text_content = (
            WHITESPACE_PATTERN.sub(" ", soup.get_text(separator="\n").strip())
            .strip()
            .replace("\n \n", "\n")
            .replace("\n\n", "\n")
        )
        print(
            f"<success> extracted text content for '{record.title}'; totaling {len(text_content)} chars in length"
        )
        return text_content

    elif record.kind == HomeworkKind.TRANSLATION:
        headers = _get_headers(token)
        if headers is None:
            print("<error> authorization failed")
            return None

        response = globalvars.context.http_client.post(
            GET_TRANSLATION_HW_CONTENT_URL,
            headers=headers,
            json={"id": record.api_id},
        )

        data = response.json()
        if data.get("success", False) is False:
            print(f"<error> failed to get homework text content: {data}")
            return None

        return "\n".join(
            map(
                lambda e: f"{e['questionNumber']}. {e['question']}",
                data["data"],
            )
        )


def download_text_content(token: Token, record: HomeworkRecord) -> None:
    print(f"--- step: download text content for '{record.title}' ---")

    text_content = get_text_content(token, record)
    if text_content is None:
        print("<error> failed to get text content")
        return

    text_file = CACHE_DIR / f"homework_{encodeb64_safe(record.title)}_text.txt"
    with open(text_file, "w", encoding="utf-8") as f:
        f.write(text_content)
    print_and_copy_path(text_file)


def transcribe_audio(record: HomeworkRecord):
    print(f"--- step: transcribe audio for '{record.title}' ---")

    path = CACHE_DIR / f"homework_{encodeb64_safe(record.title)}_audio.mp3"

    # if whisper_model is None:
    #     print("<info> loading Whisper model (this may take a while)...")
    #     whisper_model = faster_whisper.WhisperModel(
    #         globalvars.context.config.whisper.model, device="cuda", compute_type="float16"
    #     )
    # else:
    #     print("<info> Whisper model already loaded")

    # print(f"<info> transcribing audio file: {audio_file} (this may take a while)...")
    # segments, info = whisper_model.transcribe(audio_file, language="en", beam_size=5)
    # total_duration = round(info.duration, 2)
    # transcription_file = f"{audio_file}.txt"

    # with open(transcription_file, "w", encoding="utf-8") as f:
    #     with Progress() as progress:
    #         task_id = progress.add_task(
    #             "[bold_cyan]Transcribing...", total=total_duration
    #         )
    #         for segment in segments:
    #             progress.update(task_id, completed=round(segment.end, 2))
    #             f.write(segment.text)

    # print(f"<success> transcription saved to '{transcription_file}'")

    try:
        import whisper
    except ImportError:
        print(
            "<error> whisper not installed; install the 'transcription' extra requirement"
        )
        return

    if globalvars.context.whisper_model is None:
        print(
            f"<info> loading Whisper model{' into memory' if globalvars.context.config.whisper.in_memory else ''} (this may take a while)..."
        )
        whisper_device = None
        if globalvars.context.config.whisper.device == "cuda":
            whisper_device = "cuda"
        elif globalvars.context.config.whisper.device == "cpu":
            whisper_device = "cpu"
        elif globalvars.context.config.whisper.device != "auto":
            print(
                f"<warning> unrecognized whisper device '{globalvars.context.config.whisper.device}'; falling back to 'auto'..."
            )
        globalvars.context.whisper_model = whisper.load_model(
            globalvars.context.config.whisper.model,
            device=whisper_device,
            in_memory=globalvars.context.config.whisper.in_memory,
        )
    else:
        print("<info> Whisper model already loaded")

    start = time.perf_counter()
    print(f"<info> transcribing audio file: {path} (this may take a while)...")
    result = globalvars.context.whisper_model.transcribe(
        str(path), language="en", verbose=False
    )
    end = time.perf_counter()
    print(f"<info> transcription completed in {end - start:.2f} seconds")
    transcription = result.get("text", None)
    if transcription is None or (transcription is str and transcription.strip() == ""):
        print("<error> transcription failed or returned empty result")
        return

    transcription_file = f"{path}.txt"
    with open(transcription_file, "w", encoding="utf-8") as f:
        if isinstance(transcription, str):
            f.write(transcription)
            print(
                f"<success> transcription saved to '{transcription_file}'; totalling {len(transcription)} chars in length"
            )
        if isinstance(transcription, list):
            trans_str = "\n".join(transcription)
            f.write(trans_str)
            print(
                f"<success> transcription saved to '{transcription_file}'; totallin {len(trans_str)} chars in length"
            )


def generate_answers(
    token: Token | None,
    record: HomeworkRecord,
    client: AIClient,
    has_audio_manual: bool | None,
) -> Optional[list[dict]]:
    print(f"--- step: generate answers for '{record.title}' ---")

    if record.kind == HomeworkKind.QUESTIONS:
        if token is None:
            if has_audio_manual is not None:
                has_audio = has_audio_manual
            else:
                print(
                    "<error> not logged in; could not determine whether hw item has listening"
                )
                return None
        else:
            has_audio = _get_audio_url(token, record)
    else:
        has_audio = False

    transcription_file = (
        CACHE_DIR / f"homework_{encodeb64_safe(record.title)}_audio.mp3.txt"
    )
    if has_audio:
        if not transcription_file.is_file():
            print(
                "<error> transcription does not exist; please transcribe the audio first"
            )
            return None
    else:
        print("<info> homework item seems not to have listening part; skipping that")

    text_file = CACHE_DIR / f"homework_{encodeb64_safe(record.title)}_text.txt"
    if not text_file.is_file():
        print("<error> text content does not exist; please download it first")
        return None

    if has_audio:
        prompt = GENERATE_ANSWERS_WITH_LISTENING_PROMPT.replace(
            "{transcription}", read_file_text(transcription_file)
        ).replace("{questions}", read_file_text(text_file))
    elif record.kind == HomeworkKind.QUESTIONS:
        prompt = GENERATE_ANSWERS_PROMPT.replace(
            "{questions}", read_file_text(text_file)
        )
    elif record.kind == HomeworkKind.TRANSLATION:
        prompt = GENERATE_TRANSLATION_ANSWERS_PROMPT.replace(
            "{questions}", read_file_text(text_file)
        )
    else:
        raise NotImplementedError()

    print(f"<info> current AI client: {client.describe()}")
    print("<info> requesting model for a response (this may take a while)...")
    try:
        response = client.client.chat.completions.create(
            model=client.selected_model,
            messages=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": "You are a professional English teacher.",
                        }
                    ],
                },
                {"role": "user", "content": [{"type": "text", "text": prompt}]},
            ],
        )
    except openai.APIError as e:
        print(f"<error> api returned error: {e}")
        return None

    raw_data = response.choices[0].message.content
    if raw_data is None:
        print("<error> model returned null")
        return None

    try:
        answers: list[dict] = json5.loads(raw_data)  # type: ignore
        print(
            f"<success> model result is valid; totalling {len(raw_data)} chars in length"
        )

        print("<info> post-processing model result...")
        post_process_count = 0
        if record.kind == HomeworkKind.QUESTIONS:
            for answer in answers:
                if len(answer["content"]) >= 2:
                    if answer["kind"] != "fill-in-blanks":
                        post_process_count += 1
                        answer["kind"] = "fill-in-blanks"
                    else:
                        if "/" in answer["content"]:
                            post_process_count += 1
                            answer["content"] = answer["content"].split("/")
                elif "A" <= answer["content"].upper() <= "D":
                    post_process_count += 1
                    answer["kind"] = "choice|fill-in-blanks"
                elif "E" <= answer["content"].upper() <= "Z":
                    post_process_count += 1
                    answer["kind"] = "fill-in-blanks"
        elif record.kind == HomeworkKind.TRANSLATION:
            for answer in answers:
                answer["kind"] = "translation"

        print(f"<info> post-processed model result for {post_process_count} times")
        return answers

    except ValueError:
        print("<error> model result is not valid json")
        return None


def _create_answers_payload(record: HomeworkRecord, answers: list[dict]) -> dict:
    return {
        "answers": list(
            map(
                lambda a: {
                    "attachmentId": "",
                    "tagId": a["id"],
                    "text": a["content"],
                },
                answers,
            )
        ),
        "id": record.api_id,
    }


def fill_in_answers(
    token: Token,
    record: HomeworkRecord,
    answers: list[dict],
    expected_correct_rate: Optional[float] = None,
) -> None:
    print(f"--- step: fill in answers for '{record.title}' ---")

    headers = _get_headers(token)
    if headers is None:
        print("<error> authorization failed")
        return

    questions = _get_questions(token, record)
    if questions is None:
        print("<error> failed to get questions")
        return

    if len(questions) > len(answers):
        print(
            f"<error> only {len(answers)} answers provided for {len(questions)} questions"
        )
        return
    elif len(answers) > len(questions):
        print(
            f"<error> {len(answers)} answers provided for only {len(questions)} questions"
        )
        return

    if expected_correct_rate is not None:
        total_questions = len(questions)
        total_choices = sum(1 for a in answers if a["kind"] == "choice")
        expected_wrong_questions = int(total_questions * (1.0 - expected_correct_rate))
        if total_choices < expected_wrong_questions:
            print(
                f"<error> not enough choices ({total_choices}) to be wrong ({expected_wrong_questions})"
            )
            return

        if expected_wrong_questions > 0:
            print(
                f"<info> questions: {total_questions}; choices: {total_choices}; expected wrong questions/choices: {expected_wrong_questions}"
            )
            print(
                f"<info> adjusting answers to achieve expected correctness rate of {expected_correct_rate * 100:.2f}%..."
            )
            wrong_answer_indices = sorted(
                random.sample(
                    [i for i, a in enumerate(answers) if a["kind"] == "choice"],
                    expected_wrong_questions,
                )
            )
            print(
                f"<info> selected question indices for wrong answers: {wrong_answer_indices}"
            )
            for i in wrong_answer_indices:
                q = questions[i]
                a = answers[i]
                if a["kind"] == "choice" and expected_wrong_questions > 0:
                    original_answer = a["content"].upper()
                    wrong_option = random.choice(
                        [opt for opt in ["A", "B", "C", "D"] if opt != original_answer]
                    )
                    answers[i]["content"] = wrong_option
                    print(
                        f"<info> changed answer for question {q['index']} from '{original_answer}' to '{a['content']}' to reduce correctness rate"
                    )

    answers_payload = []
    for q, a in zip(questions, answers):
        answer_content = a["content"]

        if isinstance(answer_content, list):
            answer_content = random.choice(answer_content)
            print(
                f"<info> randomly selected answer '{answer_content}' from list of answers {a['content']}"
            )

        answers_payload.append(
            {
                "attachmentId": "",
                "tagId": q["id"],
                "text": answer_content,
            }
        )

    payload = {"answers": answers_payload, "id": record.api_id}

    response = globalvars.context.http_client.post(
        SAVE_ANSWERS_CACHE_URL, json=payload, headers=headers
    )
    data = response.json()
    if data.get("success", False) is False:
        print(f"<error> failed to fill in answers: {data}")
        return

    print("<success> all answers filled in; please review and submit manually")


def _get_answer_type(id: str):
    if id.startswith("radio"):
        return "choice"
    if id.startswith("text"):
        return "fill-in-blanks"
    return "unknown"


def _get_answers_cache(token: Token, record: HomeworkRecord) -> Optional[list[dict]]:
    print(f"--- step: retrieve answers cache for '{record.title}' ---")

    headers = _get_headers(token)
    if headers is None:
        print("<error> authorization failed")
        return

    payload = {"id": record.api_id}
    response = globalvars.context.http_client.post(
        LOAD_ANSWERS_CACHE_URL, json=payload, headers=headers
    )
    data = response.json()
    if data.get("success", False) is False:
        print(f"<error> failed to get answers cache: {data}")
        return None

    return list(
        map(
            lambda a: {
                "index": a[0] + 1,
                "id": a[1]["tagId"],
                "type": _get_answer_type(a[1]["tagId"]),
                "content": a[1]["text"],
            },
            enumerate(data["data"]),
        )
    )


def get_paper_answers(token: Token, record: HomeworkRecord) -> Optional[list[dict]]:
    print(f"--- step: retrieve answers from paper for '{record.title}' ---")

    headers = _get_headers(token)
    if headers is None:
        print("<error> authorization failed")
        return

    questions = _get_questions(token, record)
    if questions is None:
        print("<error> failed to get questions")
        return

    result: list[dict] = []
    for q in questions:
        answer_type = _get_answer_type(q["id"])
        answer_content = q["answer"]
        if (
            answer_type == "fill-in-blanks"
            and len(answer_content) >= 2
            and "/" in answer_content
        ):
            answer_content = answer_content.split("/")

        print(
            f"<info> extracted answer {q['index']}: Type='{answer_type}', Content='{answer_content}'"
        )
        result.append(
            {
                "index": q["index"],
                "id": q["id"],
                "type": _get_answer_type(q["id"]),
                "content": q["answer"],
            }
        )
    return result


def submit_answers(token: Token, record: HomeworkRecord) -> None:
    print(f"--- step: submit answers from paper for '{record.title}' ---")

    headers = _get_headers(token)
    if headers is None:
        print("<error> authorization failed")
        return

    answers = _get_answers_cache(token, record)
    if answers is None:
        print("<error> failed to retrieve answers cache")
        return

    payload = _create_answers_payload(record, answers)
    response = globalvars.context.http_client.post(
        SUBMIT_ANSWERS_URL, json=payload, headers=headers
    )
    data = response.json()
    if data.get("success", False) is False:
        print(f"<error> failed to submit answers: {data}")
        return

    print("<success> answers submitted")


def start_hw(token: Token, record: HomeworkRecord) -> None:
    print(f"--- step: start homework for '{record.title}' ---")

    headers = _get_headers(token)
    if headers is None:
        print("<error> authorization failed")
        return

    payload = {"id": record.api_id}
    response = globalvars.context.http_client.post(
        START_HW_URL, json=payload, headers=headers
    )
    data = response.json()
    if data.get("success", False) is False:
        print(f"<error> failed to start homework: {data}")
        return

    print("<success> homework started")


def print_hw_list(hw_list: list[HomeworkRecord]) -> None:
    globalvars.context.messenger.send_table(
        title="Homework List",
        show_header=True,
        columns=[
            ("Index", "cyan", "right"),
            ("Publish Time", "white", "center"),
            ("Title", "magenta", "left"),
            ("Status", "yellow"),
            ("Publisher", "green", "center"),
            ("Kind", "blue", "center"),
            ("Score", "red", "center"),
        ],
        rows=list(
            map(
                lambda enum_obj: (
                    str(enum_obj[0]),
                    enum_obj[1].publish_time.strftime(TIME_FORMAT),
                    enum_obj[1].title,
                    enum_obj[1].status.value[1],  # type: ignore
                    enum_obj[1].publisher_name,
                    enum_obj[1].kind.value,
                    f"{enum_obj[1].current_score}/{enum_obj[1].total_score}",
                ),
                enumerate(hw_list),
            )
        ),
    )
