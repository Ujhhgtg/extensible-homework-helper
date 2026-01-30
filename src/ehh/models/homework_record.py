from dataclasses import dataclass
from datetime import datetime

from ehh.models.homework_kind import HomeworkKind

from .homework_status import HomeworkStatus


@dataclass
class HomeworkRecord:
    title: str
    kind: HomeworkKind
    publisher_name: str
    current_score: float | None
    total_score: float
    publish_time: datetime
    status: HomeworkStatus | None
    api_id: str | None = None
    api_task_id: str | None = None
    api_task_paper_id: str | None = None
    api_batch_id: str | None = None
    api_sentence_id: str | None = None
    # start_time: str | None = None
    # end_time: str | None = None
