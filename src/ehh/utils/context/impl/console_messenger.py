from rich.console import Console as RichConsole
from rich.highlighter import ReprHighlighter as RichHighlighter
from rich.progress import Progress as RichProgress
from rich.table import Table as RichTable
from rich.theme import Theme as RichTheme

from ..base import Messenger


class ConsoleMessenger(Messenger):
    def __init__(self) -> None:
        super().__init__()
        highlighter = RichHighlighter()
        highlighter.highlights.extend(
            [
                r"(?i)\<(?P<debug>debug)\>",
                r"(?i)\<(?P<success>success)\>",
                r"(?i)\<(?P<info>info)\>",
                r"(?i)\<(?P<warning>warning)\>",
                r"(?i)\<(?P<error>error)\>",
                r"(?i)\<(?P<tip>tip)\>",
            ]
        )
        theme = RichTheme(
            {
                "repr.debug": "dim",
                "repr.success": "bold green",
                "repr.info": "bold blue",
                "repr.warning": "bold yellow",
                "repr.error": "bold red",
                "repr.tip": "bold cyan",
            }
        )
        self.rich_console = RichConsole(highlighter=highlighter, theme=theme)

    def send_text(self, *args, **kwargs):
        self.rich_console.print(*args, **kwargs)

    def send_table(
        self,
        title: str,
        columns: list[tuple[str, str, str] | tuple[str, str]],
        rows: list[tuple],
        show_header: bool = True,
        header_style: str = "bold green",
    ):
        table = RichTable(
            title=title, show_header=show_header, header_style=header_style
        )

        for column in columns:
            try:
                justify = column[2]  # type: ignore
            except IndexError:
                justify = "left"
            table.add_column(
                column[0],
                style=column[1],
                justify=justify,  # type: ignore
            )

        for row in rows:
            table.add_row(*row)

        self.rich_console.print(table)

    def send_progress(self, func, *args, **kwargs):
        with RichProgress(console=self.rich_console) as progress:
            func(progress, *args, **kwargs)

    def send_exception(self, _: Exception) -> None:
        self.rich_console.print_exception(show_locals=True)  # type: ignore
