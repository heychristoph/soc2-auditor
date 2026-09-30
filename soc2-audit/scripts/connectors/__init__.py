"""Connectors turn a source system into an evidence bundle.

A connector is a module in this package with one function:

    def pull(writer: BundleWriter, options: dict, engagement: Engagement) -> None

It reads from its source and calls `writer` to add controls, the system
description, populations and evidence. It never decides audit conclusions.
Add a connector by dropping a new module here and documenting it in
references/connectors/<name>.md; nothing else changes.
"""

import importlib
import pkgutil


def available() -> list[str]:
    return sorted(m.name for m in pkgutil.iter_modules(__path__) if not m.name.startswith("_") and m.name != "base")


def load(name: str):
    if name not in available():
        from core import AuditError

        raise AuditError(f"Unknown connector '{name}'. Available: {', '.join(available())}.")
    return importlib.import_module(f"connectors.{name}")
