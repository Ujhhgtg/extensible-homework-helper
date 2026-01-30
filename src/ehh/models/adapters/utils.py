from importlib.metadata import entry_points

from ..mixins.base import Mixin
from .base import Adapter


def discover_adapters() -> dict[str, Adapter]:
    discovered_adapters: dict[str, Adapter] = {}
    for entry_point in entry_points(group="ehh.adapters"):
        try:
            adapter_class = entry_point.load()
            discovered_adapters[entry_point.name] = adapter_class
        except Exception as e:
            print(f"load adapter failed: {e}")
    return discovered_adapters


def discover_mixins() -> dict[str, Mixin]:
    discovered_mixins: dict[str, Mixin] = {}
    for entry_point in entry_points(group="ehh.mixins"):
        try:
            mixin_class = entry_point.load()
            discovered_mixins[entry_point.name] = mixin_class
        except Exception as e:
            print(f"load mixin failed: {e}")
    return discovered_mixins
