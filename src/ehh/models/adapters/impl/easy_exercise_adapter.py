from ...homework_record import HomeworkRecord
from ..base import Adapter


class EasyExerciseAdapter(Adapter):
    def print_hw_list(self, hw_list: list[HomeworkRecord]) -> None:
        self.messenger.send_table(
            title="Homework List",
            show_header=True,
            columns=[
                ("Index", "cyan", "right"),
                ("Title", "magenta", "left"),
                ("Status", "yellow"),
                ("Score", "red", "center"),
            ],
            rows=list(
                map(
                    lambda enum_obj: (
                        str(enum_obj[0]),
                        enum_obj[1].title,
                        f"{enum_obj[1].status} ({enum_obj[1].status.value[1]})",  # type: ignore
                        f"{enum_obj[1].current_score}/{enum_obj[1].total_score}",
                    ),
                    enumerate(hw_list),
                )
            ),
        )
