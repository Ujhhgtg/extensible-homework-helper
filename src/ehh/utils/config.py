from pathlib import Path

import yaml
import json5
from munch import Munch, munchify, unmunchify

from .logging import print
from .fs import CONFIG_DIR

CONFIG_FILE = CONFIG_DIR / "config.yaml"


def load_config(path: str | Path = CONFIG_FILE) -> Munch:
    if isinstance(path, str):
        path = Path(path)

    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found at {path}. Please create one based on config.json.example."
        )

    with open(path, "rt", encoding="utf-8") as f:
        return munchify(yaml.load(f, Loader=yaml.FullLoader))  # type: ignore


def save_config(config: Munch, path: str | Path = CONFIG_FILE) -> None:
    with open(path, "wt", encoding="utf-8") as f:
        f.write(yaml.dump(unmunchify(config), allow_unicode=True, indent=2))


def migrate_config_if_needed() -> None:
    old_config_path = Path("local/config.json")
    if old_config_path.exists() and not CONFIG_FILE.exists():
        with open(old_config_path, "rt", encoding="utf-8") as f:
            config = json5.load(f)
        save_config(config, CONFIG_FILE)
        old_config_path.unlink()
        print("<info> migrated config to new location")
        return

    old_config_path = CONFIG_DIR / "config.json"
    if old_config_path.exists() and not CONFIG_FILE.exists():
        config = load_config(old_config_path)
        save_config(config, CONFIG_FILE)
        old_config_path.unlink()
        print("<info> migrated config to new format")
