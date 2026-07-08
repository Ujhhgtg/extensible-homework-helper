from typing import Optional

import httpx
from munch import Munch

from .. import feature_flags

if feature_flags.WHISPER:
    from whisper.model import Whisper


class Messenger:
    def send_text(self, *args, **kwargs) -> None:
        raise NotImplementedError

    def send_table(self, *args, **kwargs) -> None:
        raise NotImplementedError

    def send_progress(self, *args, **kwargs) -> None:
        raise NotImplementedError

    def send_exception(self, exception: Exception) -> None:
        raise NotImplementedError


class Context:
    def __init__(self, messenger: Messenger) -> None:
        self.messenger = messenger
        self.config: Munch = None  # type: ignore
        if feature_flags.WHISPER:
            self.whisper_model: Optional[Whisper] = None
        self.http_client: httpx.Client = httpx.Client(timeout=30)
