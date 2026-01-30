from importlib.util import find_spec

WHISPER: bool = find_spec("whisper") is not None
SELENIUM: bool = find_spec("selenium") is not None
TEXTUAL: bool = find_spec("textual") is not None
