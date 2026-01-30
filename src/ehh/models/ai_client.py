from munch import Munch
from openai import OpenAI

from ..utils.convert import mask_string_middle


# TODO: add multiple types of AIClient: ollama, openai
class AIClient:
    kind: str
    api_url: str
    api_key: str
    models: list[str]
    selected_model_index: int
    client: OpenAI

    def __init__(
        self, kind: str, api_url: str, api_key: str, models: list[str], sel_model: int
    ):
        self.kind = kind
        self.api_url = api_url
        self.api_key = api_key
        self.models = models
        self.selected_model_index = sel_model
        self.client = OpenAI(api_key=self.api_key, base_url=self.api_url)

    @classmethod
    def from_dict(cls, data: Munch):
        return cls(
            data.kind, data.api_url, data.api_key, data.model.all, data.model.selected
        )

    def describe(self) -> str:
        return f"{self.kind}: {self.api_url} / {mask_string_middle(self.api_key)} / {self.models}"

    @property
    def selected_model(self) -> str:
        return self.models[self.selected_model_index]
