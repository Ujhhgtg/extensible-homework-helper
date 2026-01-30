from typing import TypeVar, Generic

T = TypeVar("T")


class ChildOf(Generic[T]):
    parent: T

    def __init__(self, parent: T) -> None:
        self.parent = parent
