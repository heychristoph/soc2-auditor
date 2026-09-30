"""Folder connector: build the bundle from an export folder on disk.

This is the universal path. Any platform export, or files the client uploads,
can be arranged into this layout (see references/connectors/folder.md):

    <path>/
      controls.csv            required: id,title,description,criteria[,owner,frequency,nature,population]
      system.yaml             management's system description inputs
      populations/<name>.csv  first columns: id,date
      policies/<file>         policies and procedures
      evidence/<control-id>/<file>   evidence, grouped by the control it supports
      evidence.csv            optional metadata: path,controls,title,date,obtained
"""

from __future__ import annotations

from pathlib import Path

from core import AuditError, load_yaml, read_csv

from .base import BundleWriter, slug


def pull(writer: BundleWriter, options: dict, engagement) -> None:
    root = Path(options.get("path", "export"))
    if not root.is_absolute():
        root = engagement.root / root
    if not root.is_dir():
        raise AuditError(f"Folder connector: {root} does not exist. Set source.options.path in engagement.yaml.")
    writer.source = str(root)
    obtained_default = options.get("obtained", "client")

    controls_csv = root / "controls.csv"
    if not controls_csv.exists():
        raise AuditError(f"Folder connector: {controls_csv} is required (the control matrix).")
    rows = read_csv(controls_csv)
    missing = [c for c in ("id", "description", "criteria") if rows and c not in rows[0]]
    if missing:
        raise AuditError(f"controls.csv is missing columns: {', '.join(missing)}")
    control_ids = {r["id"] for r in rows}

    # Populations first, so controls.csv can reference them by file name or artifact ID.
    population_ids = {}
    for path in sorted((root / "populations").glob("*.csv")):
        pop_rows = read_csv(path)
        population_ids[path.stem] = writer.add_population(
            path.stem, pop_rows, title=f"Population: {path.stem.replace('-', ' ')}", obtained=obtained_default, source_ref=path.name
        )
    for row in rows:
        ref = row.get("population", "")
        if ref and not ref.startswith("PO-"):
            row["population"] = population_ids.get(Path(ref).stem, f"PO-{slug(Path(ref).stem)}")
    writer.set_controls(rows)

    if (root / "system.yaml").exists():
        writer.set_system(load_yaml(root / "system.yaml"))
    else:
        writer.warn("no system.yaml in export; management must provide the system description")

    meta = {}
    if (root / "evidence.csv").exists():
        for m in read_csv(root / "evidence.csv"):
            meta[m["path"].strip("/")] = m

    for folder, kind in (("policies", "policy"), ("evidence", "evidence")):
        base = root / folder
        for path in sorted(p for p in base.rglob("*") if p.is_file() and not p.name.startswith(".")):
            rel = path.relative_to(root).as_posix()
            m = meta.get(rel, {})
            controls = m.get("controls", "").replace(",", " ").split()
            if not controls and kind == "evidence":
                first = path.relative_to(base).parts[0]
                if first in control_ids:
                    controls = [first]
            unknown = [c for c in controls if c not in control_ids]
            if unknown:
                writer.warn(f"{rel} references unknown controls {unknown}")
            writer.add_file(
                path,
                title=m.get("title") or path.stem.replace("_", " ").replace("-", " "),
                kind=m.get("kind") or kind,
                controls=[c for c in controls if c in control_ids],
                date=m.get("date") or None,
                obtained=m.get("obtained") or obtained_default,
                source_ref=rel,
            )
