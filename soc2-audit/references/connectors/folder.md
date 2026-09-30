# Folder connector

Builds the bundle from files on disk. Use it for platform exports, client uploads, or any source without a dedicated connector.

## Configure

```yaml
source:
  connector: folder
  options:
    path: export          # relative to the engagement folder, or absolute
    obtained: client      # default provenance: client (provided) or direct (auditor pulled it)
```

## Expected layout

```
export/
├── controls.csv          required: id,title,description,criteria[,owner,frequency,nature,population]
├── system.yaml           management's description (see ../engagement-folder.md)
├── populations/<name>.csv   first columns id,date; becomes PO-<name>
├── policies/<file>       policies and procedures (kind: policy)
├── evidence/<control-id>/<file>   evidence, grouped by the control it supports
└── evidence.csv          optional: path,controls,title,date,obtained,kind
```

- In `controls.csv`, `criteria` is space- or comma-separated (`CC6.2 CC6.3`) and `population` names a file in `populations/` (`terminations` or `terminations.csv`).
- Files under `evidence/<control-id>/` are linked to that control automatically. Name item evidence with the item ID first (`T-003_offboarding-ticket.json`) so testers can find it.
- `evidence.csv` adds metadata for any file, keyed by its path relative to the export root: more controls, a title, the artifact's own date, and whether it was obtained directly.

## Converting a platform export

Most platforms can export an audit package (a zip of evidence plus a control list). Unzip it, write `controls.csv` from its control list, and move files into `evidence/<control-id>/`. Keep original file names after the item ID. Record `obtained: direct` in `evidence.csv` for files the firm downloaded itself.
