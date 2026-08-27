import asyncio
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import anthropic
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
    GENERATE_SENTENCE_TRANSLATION_PROMPT,
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
    SUBMIT_TRANSLATION_URL,
    TIME_FORMAT,
    UPLOAD_URL,
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


def _build_hw_record(
    item: dict, kind: HomeworkKind, group_title: str | None = None
) -> HomeworkRecord:
    return HomeworkRecord(
        group_title=group_title,
        api_id=item["id"],
        api_task_id=item.get("taskId", None),
        api_task_paper_id=item.get("taskPaperId", None),
        api_batch_id=item.get("batchId", None),
        # translation (sentence) tasks: userSentenceId is submit's `oldUserId`
        api_sentence_id=item.get("userSentenceId", None),
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
            # a merged/expandable homework item (mergeType == 1) is only a group
            # header; its real sub-assignments live in `mergeList`. expand them so
            # each sub-assignment becomes an individually operable record. regular
            # items have an empty/absent `mergeList` and are added as-is.
            children = item.get("mergeList", None)
            if children:
                group_title = item.get("taskTitle", None) or item.get("title", None)
                for child in sorted(children, key=lambda c: c.get("taskSort", 0) or 0):
                    hw_list.append(_build_hw_record(child, kind, group_title))
            else:
                hw_list.append(_build_hw_record(item, kind))

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
        answer_kind = _get_answer_kind(answer["tagId"])
        answer_content = _normalize_answer_content(
            answer_kind, answer["standardAnswer"]
        )

        answers.append(
            {
                "index": index + 1,
                "kind": answer_kind,
                "content": answer_content,
            }
        )
        print(
            f"<info> extracted answer {index + 1}: Kind='{answer_kind}', Content='{answer_content}'"
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
                "type": q.get("type"),  # "1"=choice, "3"=speaking
            },
            paper["flows"],
        )
    )

    q_list.sort(key=lambda elem: elem["index"])
    return q_list


DEFAULT_TTS_VOICE = "en-US-AriaNeural"


def _get_tts_voice() -> str:
    tts_conf = getattr(globalvars.context.config, "tts", None)
    if tts_conf is not None:
        voice = getattr(tts_conf, "voice", None)
        if voice:
            return str(voice)
    return DEFAULT_TTS_VOICE


def _speaking_answer_text(answer) -> Optional[str]:
    # a speaking flow answer may hold several acceptable responses separated by
    # "|"; pick the first non-empty one to synthesize.
    if isinstance(answer, str):
        text = answer
    elif isinstance(answer, list):
        text = next((str(a) for a in answer if str(a).strip()), "")
    else:
        text = str(answer) if answer is not None else ""
    text = text.split("|")[0].strip() if "|" in text else text.strip()
    return text or None


def generate_speaking_audio(
    token: Token, record: HomeworkRecord
) -> Optional[list[dict]]:
    """Synthesize reference-answer audio for every speaking question in a paper.

    Returns a list of {index, id, text, path} for the generated clips, or None on
    failure. This only produces the audio files locally; uploading/submitting them
    is a separate step.
    """
    print(f"--- step: generate speaking audio for '{record.title}' ---")

    try:
        import edge_tts
    except ImportError:
        print("<error> edge-tts not installed; install the 'tts' extra requirement")
        return None

    questions = _get_questions(token, record)
    if questions is None:
        print("<error> failed to get questions")
        return None

    speaking = [
        q
        for q in questions
        if _get_answer_kind(q["id"]) == "speaking" or q.get("type") == "3"
    ]
    if not speaking:
        print("<info> no speaking questions found in this homework item")
        return []

    voice = _get_tts_voice()
    print(
        f"<info> synthesizing {len(speaking)} speaking answer(s) with voice '{voice}'"
    )

    results: list[dict] = []
    for q in speaking:
        text = _speaking_answer_text(q["answer"])
        if text is None:
            print(f"<warning> question {q['index']} has no reference answer; skipping")
            continue

        path = (
            CACHE_DIR
            / f"homework_{encodeb64_safe(record.title)}_speaking_{q['id']}.mp3"
        )
        try:
            communicate = edge_tts.Communicate(text, voice)
            asyncio.run(communicate.save(str(path)))
        except Exception as tts_e:
            print(f"<error> failed to synthesize audio for question {q['index']}:")
            globalvars.context.messenger.send_exception(tts_e)
            return None

        size = Path(path).stat().st_size if Path(path).is_file() else 0
        if size == 0:
            print(f"<error> synthesized audio for question {q['index']} is empty")
            return None

        print(
            f"<info> generated audio for question {q['index']} "
            f"({size} bytes): '{text[:50]}{'...' if len(text) > 50 else ''}'"
        )
        results.append(
            {"index": q["index"], "id": q["id"], "text": text, "path": str(path)}
        )

    print(f"<success> generated {len(results)} speaking audio clip(s)")
    return results


def _upload_speaking_audio(
    token: Token, record: HomeworkRecord, tag_id: str, path: str | Path
) -> Optional[str]:
    """Upload one mp3 for a speaking question; return the attachmentId or None."""
    headers = _get_headers(token)
    if headers is None:
        print("<error> authorization failed")
        return None

    path = Path(path)
    if not path.is_file():
        print(f"<error> audio file not found: {path}")
        return None

    params = {
        "businessId": record.api_id,
        "type": "4",
        "uploadType": "4",
        "attachType": "mp3",
        "attachName": f"{tag_id}-口语答案",
    }
    with open(path, "rb") as f:
        files = {"file": ("blob", f, "audio/mp3")}
        response = globalvars.context.http_client.post(
            UPLOAD_URL, headers=headers, params=params, files=files
        )
    data = response.json()
    if data.get("success", False) is False:
        print(f"<error> failed to upload audio for {tag_id}: {data}")
        return None

    attachment_id = data.get("data", {}).get("id", None)
    if not attachment_id:
        print(f"<error> upload response has no attachment id: {data}")
        return None

    return str(attachment_id)


def _upload_speaking_clips(
    token: Token, record: HomeworkRecord
) -> Optional[dict[str, str]]:
    """Generate + upload reference audio for every speaking question.

    Returns a {tagId: attachmentId} map (empty if there are no speaking questions),
    or None if generation or any upload failed.
    """
    clips = generate_speaking_audio(token, record)
    if clips is None:
        print("<error> failed to generate speaking audio")
        return None

    attachment_by_tag: dict[str, str] = {}
    for clip in clips:
        print(f"<info> uploading audio for question {clip['index']} ({clip['id']})")
        attachment_id = _upload_speaking_audio(token, record, clip["id"], clip["path"])
        if attachment_id is None:
            print(f"<error> upload failed for question {clip['index']}; aborting")
            return None
        attachment_by_tag[clip["id"]] = attachment_id
        print(f"<info> uploaded; attachmentId={attachment_id}")

    return attachment_by_tag


def _build_answers_payload(
    paper_answers: list[dict], attachment_by_tag: dict[str, str]
) -> list[dict]:
    """Assemble the saveCache answers array from paper answers, wiring uploaded
    attachmentIds into speaking questions and text into the rest."""
    payload_answers = []
    for a in paper_answers:
        tag_id = a["id"]
        if a["kind"] == "speaking":
            attachment_id = attachment_by_tag.get(tag_id)
            if attachment_id is None:
                # a speaking question whose audio we couldn't generate/upload
                continue
            payload_answers.append(
                {
                    "tagId": tag_id,
                    "text": None,
                    "attachmentId": attachment_id,
                    "writingAttachmentId": None,
                    "practiceMode": 1,
                    "check": False,
                }
            )
        else:
            content = a["content"]
            if isinstance(content, list):
                content = random.choice(content)
            payload_answers.append(
                {
                    "tagId": tag_id,
                    "text": content,
                    "attachmentId": "",
                    "writingAttachmentId": None,
                    "practiceMode": 1,
                    "check": False,
                }
            )
    return payload_answers


def _save_answers_cache_payload(
    token: Token, record: HomeworkRecord, payload_answers: list[dict]
) -> bool:
    headers = _get_headers(token)
    if headers is None:
        print("<error> authorization failed")
        return False

    payload = {"answers": payload_answers, "id": record.api_id}
    response = globalvars.context.http_client.post(
        SAVE_ANSWERS_CACHE_URL, json=payload, headers=headers
    )
    data = response.json()
    if data.get("success", False) is False:
        print(f"<error> failed to save answers cache: {data}")
        return False

    return True


def complete_homework(
    token: Token,
    record: HomeworkRecord,
    submit: bool = False,
    ai_client: Optional[AIClient] = None,
    expected_correctness: Optional[float | int] = None,
) -> Optional[list[dict]]:
    """Full pipeline for a homework item, handling any question type.

    - Questions: pull every answer from the paper, synthesize + upload audio for
      speaking questions, and cache the whole answer set via saveCache.
    - Translation: use the LLM (ai_client required) to translate every sentence and
      save a local draft.

    Does NOT submit unless `submit` is explicitly True.
    """
    print(f"--- step: complete homework '{record.title}' ---")

    if record.kind == HomeworkKind.TRANSLATION:
        if ai_client is None:
            print("<error> Translation items need an AI client; select one first")
            return None
        answered = generate_translation_answers(token, record, ai_client)
        if answered is None:
            print("<error> failed to generate translation answers")
            return None
        if submit:
            print("<info> submitting translation...")
            submit_translation(token, record)
        else:
            print(
                "<info> translation draft saved but NOT submitted; review and submit manually"
            )
        return answered

    paper_answers = get_paper_answers(token, record)
    if paper_answers is None:
        print("<error> failed to get paper answers")
        return None

    if expected_correctness is not None:
        total_questions = len(paper_answers)
        total_choices = sum(1 for a in paper_answers if _is_flippable_choice(a))
        if isinstance(expected_correctness, float):
            expected_wrong_questions = int(total_questions * (1.0 - expected_correctness))
        elif expected_correctness >= 0:
            # positive int: count of correct questions
            if expected_correctness > total_questions:
                print(
                    f"<error> correct count ({expected_correctness}) exceeds total questions ({total_questions})"
                )
                return None
            expected_wrong_questions = total_questions - expected_correctness
        else:
            # negative int: absolute value is count of wrong questions
            expected_wrong_questions = -expected_correctness
        if total_choices < expected_wrong_questions:
            print(
                f"<error> not enough choices ({total_choices}) to be wrong ({expected_wrong_questions})"
            )
            return None

        if expected_wrong_questions > 0:
            print(
                f"<info> questions: {total_questions}; choices: {total_choices}; expected wrong questions/choices: {expected_wrong_questions}"
            )
            print(
                f"<info> adjusting {expected_wrong_questions} answer(s) to be wrong..."
            )
            wrong_answer_indices = sorted(
                random.sample(
                    [i for i, a in enumerate(paper_answers) if _is_flippable_choice(a)],
                    expected_wrong_questions,
                )
            )
            print(
                f"<info> selected question indices for wrong answers: {wrong_answer_indices}"
            )
            for i in wrong_answer_indices:
                a = paper_answers[i]
                original_answer = a["content"].upper() if isinstance(a["content"], str) else str(a["content"]).upper()
                wrong_option = random.choice(
                    [opt for opt in ["A", "B", "C", "D"] if opt != original_answer]
                )
                paper_answers[i]["content"] = wrong_option
                print(
                    f"<info> changed answer for question {a['index']} from '{original_answer}' to '{wrong_option}' to reduce correctness rate"
                )

    attachment_by_tag = _upload_speaking_clips(token, record)
    if attachment_by_tag is None:
        return None

    payload_answers = _build_answers_payload(paper_answers, attachment_by_tag)
    if not payload_answers:
        print("<error> no answers to cache")
        return None

    if not _save_answers_cache_payload(token, record, payload_answers):
        return None

    print(
        f"<success> completed '{record.title}': uploaded "
        f"{len(attachment_by_tag)} speaking clip(s), cached "
        f"{len(payload_answers)} answer(s)"
    )

    if submit:
        print("<info> submitting homework...")
        submit_answers(token, record)
    else:
        print("<info> answers cached but NOT submitted; review and submit manually")

    return payload_answers


def fill_in_speaking_answers(
    token: Token, record: HomeworkRecord, submit: bool = False
) -> Optional[list[dict]]:
    """Generate reference-answer audio for every speaking question, upload each,
    and cache the full answer set via saveCache. Thin wrapper over
    complete_homework that no-ops when the item has no speaking questions.
    """
    print(f"--- step: fill in speaking answers for '{record.title}' ---")

    if record.kind == HomeworkKind.TRANSLATION:
        print("<error> Translation items have no speaking questions")
        return None

    paper_answers = get_paper_answers(token, record)
    if paper_answers is None:
        print("<error> failed to get paper answers")
        return None
    if not any(a["kind"] == "speaking" for a in paper_answers):
        print("<info> no speaking questions to fill in")
        return []

    return complete_homework(token, record, submit=submit)


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


def _get_translation_questions(
    token: Token, record: HomeworkRecord
) -> Optional[list[dict]]:
    """Fetch the sentence-translation questions for a Translation task. Each item
    carries: id, sentenceId, questionNumber, word, pattern, question (Chinese),
    answer (reference), score."""
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
        print(f"<error> failed to get translation questions: {data}")
        return None

    questions = data.get("data", []) or []
    questions.sort(key=lambda q: q.get("questionNumber", 0))
    return questions


def _translation_draft_path(record: HomeworkRecord):
    return CACHE_DIR / f"homework_{encodeb64_safe(record.title)}_translation.json"


def generate_translation_answers(
    token: Token, record: HomeworkRecord, client: AIClient
) -> Optional[list[dict]]:
    """Use the LLM to translate every sentence, obeying the required word/pattern.

    Returns the full question objects (as returned by the API) with each `answer`
    replaced by the generated translation, ready to submit. Also writes them to a
    local draft file so they can be reviewed/submitted separately.
    """
    print(f"--- step: generate translation answers for '{record.title}' ---")

    if record.kind != HomeworkKind.TRANSLATION:
        print("<error> not a Translation homework item")
        return None

    questions = _get_translation_questions(token, record)
    if questions is None:
        print("<error> failed to get translation questions")
        return None
    if not questions:
        print("<error> no translation questions found")
        return None

    model_input = json5.dumps(
        [
            {
                "index": q["questionNumber"],
                "word": q.get("word", ""),
                "pattern": q.get("pattern", ""),
                "question": q["question"],
            }
            for q in questions
        ],
        ensure_ascii=False,
    )
    prompt = GENERATE_SENTENCE_TRANSLATION_PROMPT.replace("{questions}", model_input)

    print(f"<info> current AI client: {client.describe()}")
    print("<info> requesting model for translations (this may take a while)...")
    try:
        raw_data = client.generate(
            "You are a professional English teacher and translator.", prompt
        )
    except (openai.APIError, anthropic.APIError) as e:
        print(f"<error> api returned error: {e}")
        return None

    if raw_data is None:
        print("<error> model returned null")
        return None

    try:
        generated: list[dict] = json5.loads(raw_data)
    except ValueError:
        print("<error> model result is not valid json")
        return None

    if len(generated) != len(questions):
        print(
            f"<error> model returned {len(generated)} translations "
            f"for {len(questions)} questions"
        )
        return None

    # map generated content back onto the questions by index order
    by_index = {g.get("index"): g.get("content") for g in generated}
    answered = []
    for q in questions:
        content = by_index.get(q["questionNumber"])
        if not content:
            print(f"<error> no translation for question {q['questionNumber']}")
            return None
        item = dict(q)
        item["answer"] = content
        answered.append(item)
        print(f"<info> Q{q['questionNumber']} ({q.get('word', '').strip()}): {content}")

    draft_path = _translation_draft_path(record)
    with open(draft_path, "wt", encoding="utf-8") as f:
        f.write(json5.dumps(answered, ensure_ascii=False, indent=4))
    print(f"<success> generated {len(answered)} translation(s)")
    print_and_copy_path(draft_path)
    return answered


def submit_translation(token: Token, record: HomeworkRecord) -> None:
    """Submit a Translation task using the local draft produced by
    generate_translation_answers."""
    print(f"--- step: submit translation for '{record.title}' ---")

    headers = _get_headers(token)
    if headers is None:
        print("<error> authorization failed")
        return

    draft_path = _translation_draft_path(record)
    if not draft_path.is_file():
        print(
            "<error> no translation draft found; run 'answers complete' first to "
            "generate answers"
        )
        return

    with open(draft_path, "rt", encoding="utf-8") as f:
        answered: list[dict] = json5.loads(f.read())

    if record.api_sentence_id is None:
        print("<error> missing userSentenceId; cannot submit translation")
        return

    payload = {
        "id": record.api_id,
        "oldUserId": record.api_sentence_id,
        "imgUrl": "",
        "sentenceUserTaskAnswerDtoList": answered,
    }
    response = globalvars.context.http_client.post(
        SUBMIT_TRANSLATION_URL, json=payload, headers=headers
    )
    data = response.json()
    if data.get("success", False) is False:
        print(f"<error> failed to submit translation: {data}")
        return

    print("<success> translation submitted")


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
        questions = _get_translation_questions(token, record)
        if questions is None:
            print("<error> failed to get translation questions")
            return None

        lines = []
        for q in questions:
            word = (q.get("word") or "").strip()
            pattern = (q.get("pattern") or "").strip()
            hint = f"  [word: {word}]" if word else ""
            if pattern:
                hint += f" [pattern: {pattern}]"
            lines.append(f"{q['questionNumber']}. {q['question']}{hint}")
        return "\n".join(lines)


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
        raw_data = client.generate("You are a professional English teacher.", prompt)
    except (openai.APIError, anthropic.APIError) as e:
        print(f"<error> api returned error: {e}")
        return None

    if raw_data is None:
        print("<error> model returned null")
        return None

    try:
        answers: list[dict] = json5.loads(raw_data)
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
    expected_correctness: Optional[float | int] = None,
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

    if expected_correctness is not None:
        total_questions = len(questions)
        total_choices = sum(1 for a in answers if _is_flippable_choice(a))
        if isinstance(expected_correctness, float):
            expected_wrong_questions = int(total_questions * (1.0 - expected_correctness))
        elif expected_correctness >= 0:
            # positive int: count of correct questions
            if expected_correctness > total_questions:
                print(
                    f"<error> correct count ({expected_correctness}) exceeds total questions ({total_questions})"
                )
                return
            expected_wrong_questions = total_questions - expected_correctness
        else:
            # negative int: absolute value is count of wrong questions
            expected_wrong_questions = -expected_correctness
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
                f"<info> adjusting {expected_wrong_questions} answer(s) to be wrong..."
            )
            wrong_answer_indices = sorted(
                random.sample(
                    [i for i, a in enumerate(answers) if _is_flippable_choice(a)],
                    expected_wrong_questions,
                )
            )
            print(
                f"<info> selected question indices for wrong answers: {wrong_answer_indices}"
            )
            for i in wrong_answer_indices:
                q = questions[i]
                a = answers[i]
                if _is_flippable_choice(a):
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


def _get_answer_kind(id: str):
    if id.startswith("radio"):
        return "choice"
    if id.startswith("text"):
        return "fill-in-blanks"
    # speaking questions (e.g. in 听说训练) use a bare numeric tagId with no prefix
    if id and id[0].isdigit():
        return "speaking"
    return "unknown"


def _is_flippable_choice(a: dict) -> bool:
    """Return True only for single A/B/C/D radio choices that can be safely
    replaced with a different option to introduce a deliberate wrong answer.

    Compound answers like 'B#B#C#B#B' (multiple sub-choices joined by '#',
    as seen in 听说训练 assignments) share the 'choice' kind but must not be
    flipped — replacing them with a single letter would corrupt the answer."""
    return (
        a["kind"] == "choice"
        and isinstance(a["content"], str)
        and len(a["content"]) == 1
        and "A" <= a["content"].upper() <= "D"
    )


def _normalize_answer_content(kind: str, content):
    if not isinstance(content, str):
        return content
    # fill-in-blanks may list acceptable answers separated by "/"
    if kind == "fill-in-blanks" and len(content) >= 2 and "/" in content:
        return content.split("/")
    # speaking questions may list alternative acceptable responses separated by "|"
    if kind == "speaking" and "|" in content:
        parts = [part.strip() for part in content.split("|") if part.strip()]
        return parts if len(parts) >= 2 else content
    return content


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

    cached = data.get("data")
    if not cached:
        # no cache to submit (e.g. the item was never filled in or already submitted)
        print("<warning> no cached answers found for this item")
        return None

    return list(
        map(
            lambda a: {
                "index": a[0] + 1,
                "id": a[1]["tagId"],
                "kind": _get_answer_kind(a[1]["tagId"]),
                "content": a[1]["text"],
            },
            enumerate(cached),
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
        answer_kind = _get_answer_kind(q["id"])
        answer_content = _normalize_answer_content(answer_kind, q["answer"])

        print(
            f"<info> extracted answer {q['index']}: Kind='{answer_kind}', Content='{answer_content}'"
        )
        result.append(
            {
                "index": q["index"],
                "id": q["id"],
                "kind": answer_kind,
                "content": answer_content,
            }
        )
    return result


def submit_answers(token: Token, record: HomeworkRecord) -> None:
    print(f"--- step: submit answers from paper for '{record.title}' ---")

    # translation tasks use a different endpoint and submit a local draft
    if record.kind == HomeworkKind.TRANSLATION:
        submit_translation(token, record)
        return

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
    rows: list[tuple] = []
    cur_group: str | None = None
    for index, record in enumerate(hw_list):
        # emit a non-indexed header row whenever we enter a new expandable group.
        # the group is only a label, so it gets no index and is not operable.
        if record.group_title is not None and record.group_title != cur_group:
            cur_group = record.group_title
            rows.append(
                (
                    "",
                    "",
                    f"[bold cyan]▼ {record.group_title}[/bold cyan]",
                    "",
                    "",
                    "",
                    "",
                )
            )
        elif record.group_title is None:
            cur_group = None

        title = record.title
        if record.group_title is not None:
            title = f"  {title}"  # indent children under their group header

        rows.append(
            (
                str(index),
                record.publish_time.strftime(TIME_FORMAT),
                title,
                record.status.value[1],  # type: ignore
                record.publisher_name,
                record.kind.value,
                f"{record.current_score}/{record.total_score}",
            )
        )

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
        rows=rows,
    )
