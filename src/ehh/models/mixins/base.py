from semver import Version

from ..adapters.base import Adapter
from ...utils.importing import is_pkg_installed
from ...utils.child_of import ChildOf


class Mixin(ChildOf[Adapter]):
    id: str
    name: str
    version: Version
    dependencies: list[str]  # TODO: unused
    dependencies_python: list[str]

    def check_all_dependencies(
        self,
    ) -> tuple[
        bool, list[str], list[str]
    ]:  # are deps complete?, missing deps, missing python pkgs
        py_not_installed = []

        for dep in self.dependencies_python:
            if not is_pkg_installed(dep):
                py_not_installed.append(dep)

        return (len(py_not_installed) == 0, [], py_not_installed)
