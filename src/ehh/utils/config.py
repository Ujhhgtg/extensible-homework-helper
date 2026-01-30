from pathlib import Path

import yaml
from munch import Munch, munchify, unmunchify

from .fs import CONFIG_DIR
from .logging import print

CONFIG_FILE = CONFIG_DIR / "config.yaml"


def load_config(path: str | Path = CONFIG_FILE) -> Munch:
    if isinstance(path, str):
        path = Path(path)

    if not path.exists():
        raise FileNotFoundError(
            f"config file not found at {path}. please create one based on config.yaml.example."
        )

    with open(path, "rt", encoding="utf-8") as f:
        return munchify(yaml.load(f, Loader=yaml.FullLoader))  # type: ignore


def save_config(config: Munch, path: str | Path = CONFIG_FILE) -> None:
    with open(path, "wt", encoding="utf-8") as f:
        f.write(yaml.dump(unmunchify(config), allow_unicode=True, indent=2))


def migrate_config_if_needed() -> None:
    old_config_path = Path("config.yaml")
    if old_config_path.exists() and not CONFIG_FILE.exists():
        with open(old_config_path, "rt", encoding="utf-8") as f:
            config = yaml.load(f, Loader=yaml.FullLoader)
        save_config(config, CONFIG_FILE)
        old_config_path.unlink()
        print("<info> migrated config to new location")
