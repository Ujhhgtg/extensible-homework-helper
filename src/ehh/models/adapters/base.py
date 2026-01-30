from typing import Optional


from ...utils.context.base import Messenger
from ..credentials import Credentials
from ..homework_record import HomeworkRecord
from ..credentials import Credentials


class Adapter:
    credentials: Optional[Credentials] = None
    messenger: Messenger

    def __init__(self, messenger: Messenger) -> None:
        self.messenger = messenger

    def login(self, credentials: Credentials) -> bool:
        raise NotImplementedError

    def logout(self) -> bool:
        raise NotImplementedError

    @property
    def is_logged_in(self) -> bool:
        raise NotImplementedError

    def get_hw_list(self) -> list[HomeworkRecord]:
        raise NotImplementedError

    def get_answers(self, record: HomeworkRecord) -> list[dict[str, str | int]]:
        raise NotImplementedError

    def get_text(self, record: HomeworkRecord) -> str:
        raise NotImplementedError

    def fill_in_answers(
        self,
        record: HomeworkRecord,
        answers: list[dict[str, str | int]],
    ) -> bool:

        raise NotImplementedError

    def start_hw_session(self, record: HomeworkRecord) -> bool:
        raise NotImplementedError

    def submit_hw(self, record: HomeworkRecord) -> bool:
        raise NotImplementedError
