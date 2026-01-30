from typing import Optional
from importlib.metadata import distributions


_cached_pkg_names: Optional[list[str]] = None


def _installed_pkgs() -> list[str]:
    return list(map(lambda dist: dist.metadata["Name"].lower(), distributions()))


def installed_pkgs() -> list[str]:
    global _cached_pkg_names

    if _cached_pkg_names is None:
        _cached_pkg_names = _installed_pkgs()

    return _cached_pkg_names


def is_pkg_installed(package_name: str) -> bool:
    global _cached_pkg_names

    if _cached_pkg_names is None:
        _cached_pkg_names = _installed_pkgs()

    lower_package_name = package_name.lower()

    return lower_package_name in _cached_pkg_names
