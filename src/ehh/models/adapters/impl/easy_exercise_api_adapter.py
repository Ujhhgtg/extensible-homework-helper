import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from ....utils.logging import print
from ....utils.crypto import get_md5_str_of_str
from ...api.school_info import SchoolInfo
from ...api.token import Token
from ...api.user_info import UserInfo
from ...homework_record import HomeworkRecord
from ...homework_status import HomeworkStatus
from ...credentials import Credentials
from ....utils.context.base import Messenger
from .easy_exercise_adapter import EasyExerciseAdapter


class EasyExerciseApiAdapter(EasyExerciseAdapter):
    http_client: httpx.Client
    token: Optional[Token] = None

    BASE_URL = "https://gateway.jeedu.net"
    FIND_SCHOOLS_URL = "/api/user/anonymousUser/findSchools"
    GET_TOKEN_URL = "/api/auth/oauth/token"
    GET_HW_LIST_URL = "/api/exam/studentApi/userTaskPage"
    GET_HW_DETAILS_URL = "/api/exam/studentApi/userTaskResult"
    GET_HW_PAPER_URL = "/api/exam/taskPaper"
    LOAD_ANSWERS_CACHE_URL = "/api/exam/studentApi/loadCache"
    SAVE_ANSWERS_CACHE_URL = "/api/exam/studentApi/saveCache"
    SUBMIT_ANSWERS_URL = "/api/exam/studentApi/userTaskSubmit"
    START_HW_URL = "/api/exam/studentApi/userTaskStart"

    def __init__(self, messenger: Messenger) -> None:
        super().__init__(messenger)
        self.http_client = httpx.Client(
            base_url=self.BASE_URL,
            timeout=15.0,
        )

    @staticmethod
    def _get_status_enum(status_int: int) -> HomeworkStatus:
        for member in HomeworkStatus:
            if member.value[0] == status_int:
                return member

        return HomeworkStatus.UNKNOWN

    def _get_school(self, name: str) -> Optional[SchoolInfo]:
        response = self.http_client.post(self.FIND_SCHOOLS_URL, json={"name": name})
        data = response.json()
        if data.get("success", False) is False:
            raise ValueError(f"find school failed: {data}")

        schools = data.get("data", [])
        if len(schools) == 0:
            raise ValueError(f"no school found with name '{name}'")

        first_school = schools[0]
        return SchoolInfo(id=first_school["id"], name=first_school["name"])

    def _get_headers(self) -> dict[str, str]:
        if self.token is None:
            raise ValueError("not logged in")

        if self.token.token_type != "bearer":
            raise ValueError(f"unsupported token type: {self.token.token_type}")

        return {
            "Authorization": f"Bearer {self.token.access_token}",
        }

    def login(self, credentials: Credentials) -> bool:
        school = self._get_school(credentials.school)
        if school is None:
            raise ValueError(f"school '{credentials.school}' not found")

        payload = {
            "username": credentials.username + "|" + str(school.id),
            "password": get_md5_str_of_str(credentials.password),
            "grant_type": "password",
            "client_id": "fyll",
            "client_secret": "fyll2020",
            "randomCode": "",
        }
        response = self.http_client.post(self.GET_TOKEN_URL, params=payload)
        data = response.json()
        if data.get("success", False) is False:
            raise ValueError(f"login failed: {data}")

        self.credentials = credentials
        self.token = Token(
            access_token=data["access_token"],
            token_type=data["token_type"],
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
        return True

    def logout(self) -> bool:
        self.credentials = None
        self.token = None
        return True

    @property
    def is_logged_in(self) -> bool:
        return self.token is not None

    def get_hw_list(self) -> list[HomeworkRecord]:
        if self.token is None:
            raise ValueError("not logged in")

        max_page_index = 0
        cur_page_index = 0
        hw_list: list[HomeworkRecord] = []

        while cur_page_index <= max_page_index:
            response = self.http_client.post(
                self.GET_HW_LIST_URL,
                headers=self._get_headers(),
                json={"pageIndex": cur_page_index + 1, "pageSize": 50},
            )
            data = response.json()
            if data.get("success", False) is False:
                print(f"<error> get homework list failed: {data}")
                break

            max_page_index = data["data"]["pageCount"]

            for item in data["data"]["userTasks"]:
                title = item["taskTitle"]
                status = self._get_status_enum(int(item["status"]))
                cur_score = item["score"]
                tot_score = item["totalScore"]

                hw_list.append(
                    HomeworkRecord(
                        api_id=item["id"],
                        api_task_id=item["taskId"],
                        api_task_paper_id=item["taskPaperId"],
                        api_batch_id=item["batchId"],
                        title=title,
                        teacher_name=item["assignerName"],
                        start_time=item["startTime"],
                        end_time=item["completeTime"],
                        publish_time=item["beginTime"],
                        due_time=item["endTime"],
                        current_score=cur_score,
                        pass_score=0,  # idk which is pass score
                        total_score=tot_score,
                        is_pass=True,  # idk which is pass condition
                        teacher_comment=None,  # idk which is teacher comment
                        status=status,
                    )
                )

            cur_page_index += 1

        return hw_list

    def _get_hw_details(self, record: HomeworkRecord) -> dict:
        headers = self._get_headers()

        response = self.http_client.post(
            self.GET_HW_DETAILS_URL,
            headers=headers,
            json={"id": record.api_id},
        )
        data = response.json()
        if data.get("success", False) is False:
            raise ValueError(f"get homework details failed: {data}")

        assert "data" in data
        return data["data"]

    def _get_hw_paper(self, record: HomeworkRecord) -> dict:
        headers = self._get_headers()

        response = self.http_client.post(
            self.GET_HW_PAPER_URL,
            headers=headers,
            json={"id": record.api_task_paper_id},
        )
        data = response.json()
        if data.get("success", False) is False:
            raise ValueError(f"get homework paper failed: {data}")

        return data["data"]

    def _get_questions_with_answers(self, record: HomeworkRecord) -> list[dict]:
        paper = self._get_hw_paper(record)

        q_list: list[dict] = list(
            map(
                lambda q: {
                    "index": q["sort"],  # starts from 1
                    "api_id": q["id"],
                    "id": q["tagId"],  # attr 'name' of radio and input in web
                    "answer": q[
                        "answer"
                    ],  # bruh so it just returns the answer directly???
                    "score": q["score"],
                },
                paper["flows"],
            )
        )

        q_list.sort(key=lambda elem: elem["index"])
        return q_list

    def _get_audio_url(self, record: HomeworkRecord) -> Optional[str]:
        paper = self._get_hw_paper(record)

        soup = BeautifulSoup(paper["content"], "html.parser")
        audio_tag = soup.find("audio")
        if audio_tag is None:
            return None

        return str(audio_tag.get("src"))

    @staticmethod
    def _get_answer_type_from_id(id: str):
        if id.startswith("radio"):
            return "choice"
        if id.startswith("text"):
            return "fill-in-blanks"
        return "unknown"

    def get_answers(
        self, record: HomeworkRecord, from_paper: bool = False
    ) -> list[dict[str, str | int]]:
        if not from_paper:
            hw = self._get_hw_details(record)

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

            return answers
        else:
            questions = self._get_questions_with_answers(record)

            result: list[dict] = []
            for q in questions:
                answer_type = self._get_answer_type_from_id(q["id"])
                answer_content = q["answer"]

                if answer_type == "fill-in-blanks" and "/" in answer_content:
                    answer_content = answer_content.split("/")

                result.append(
                    {
                        "index": q["index"],
                        "id": q["id"],
                        "type": answer_type,
                        "content": answer_content,
                    }
                )
            return result

    WHITESPACE_PATTERN = re.compile(r"[^\S\n]+")

    def get_text(self, record: HomeworkRecord) -> str:
        paper = self._get_hw_paper(record)

        soup = BeautifulSoup(paper["content"], "html.parser")
        text_content = (
            self.WHITESPACE_PATTERN.sub(" ", soup.get_text(separator="\n").strip())
            .strip()
            .replace("\n \n", "\n")
            .replace("\n\n", "\n")
        )
        return text_content

    def _get_answers_cache(self, record: HomeworkRecord) -> list[dict]:
        headers = self._get_headers()

        payload = {"id": record.api_id}
        response = self.http_client.post(
            self.LOAD_ANSWERS_CACHE_URL, json=payload, headers=headers
        )
        data = response.json()
        if data.get("success", False) is False:
            raise ValueError(f"load answers cache failed: {data}")

        return list(
            map(
                lambda a: {
                    "index": a[0] + 1,
                    "id": a[1]["tagId"],
                    "type": self._get_answer_type_from_id(a[1]["tagId"]),
                    "content": a[1]["text"],
                },
                enumerate(data["data"]),
            )
        )

    @staticmethod
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

    def submit_answers(self, record: HomeworkRecord) -> None:
        headers = self._get_headers()
        answers = self._get_answers_cache(record)
        payload = self._create_answers_payload(record, answers)

        response = self.http_client.post(
            self.SUBMIT_ANSWERS_URL, json=payload, headers=headers
        )
        data = response.json()
        if data.get("success", False) is False:
            raise ValueError(f"submit answers failed: {data}")
