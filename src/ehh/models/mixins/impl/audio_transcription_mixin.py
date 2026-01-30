from semver import Version

from ...adapters.base import Adapter

from ..base import Mixin


class AudioTranscriptionMixin(Mixin):
    name = "audio-transcription"
    readable_name = "Audio Transcription"
    version = Version.parse("0.0.1")
    dependencies = []
    dependencies_python = ["openai-whisper"]

    def __init__(self) -> None:
        super().__init__()
    
    def 