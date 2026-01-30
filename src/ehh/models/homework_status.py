from enum import Enum


class HomeworkStatus(Enum):
    COMPLETED = (4, "已完成")
    IN_PROGRESS = (1, "进行中")
    NOT_COMPLETED = (0, "未完成")
    MAKE_UP = (5, "需补做")
    UNKNOWN = (None, "未知")
