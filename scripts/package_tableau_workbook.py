"""Refresh the processed CSVs embedded in the packaged Tableau workbook."""

from __future__ import annotations

import argparse
import tempfile
import zipfile
from pathlib import Path


CSV_ENTRIES = {
    "Data/processed/regime_asset_metrics.csv": Path(
        "data/processed/regime_asset_metrics.csv"
    ),
    "Data/processed/regime_correlations.csv": Path(
        "data/processed/regime_correlations.csv"
    ),
}
FORBIDDEN_REFERENCES = (
    "postgres",
    ".hyper",
    "macro_asset_with_regime",
    "regime_asset_performance_summary",
    "Stress + High Yield",
    "Mixed",
)


def refresh_package(project_root: Path, workbook: Path) -> None:
    workbook = workbook.resolve()
    with zipfile.ZipFile(workbook, "r") as source:
        entries = {info.filename: source.read(info.filename) for info in source.infolist()}

    twb_entries = [name for name in entries if name.endswith(".twb")]
    if len(twb_entries) != 1:
        raise RuntimeError(f"Expected one .twb entry, found {twb_entries}")
    xml = entries[twb_entries[0]].decode("utf-8")
    hits = [term for term in FORBIDDEN_REFERENCES if term.lower() in xml.lower()]
    if hits:
        raise RuntimeError(f"Legacy Tableau references remain: {hits}")

    for entry_name, relative_path in CSV_ENTRIES.items():
        local_path = project_root / relative_path
        entries[entry_name] = local_path.read_bytes()

    with tempfile.NamedTemporaryFile(
        suffix=".twbx", dir=workbook.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(
            temporary_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as destination:
            for name, content in entries.items():
                destination.writestr(name, content)
        temporary_path.replace(workbook)
    finally:
        temporary_path.unlink(missing_ok=True)

    with zipfile.ZipFile(workbook, "r") as packaged:
        for entry_name, relative_path in CSV_ENTRIES.items():
            if packaged.read(entry_name) != (project_root / relative_path).read_bytes():
                raise RuntimeError(f"Packaged CSV mismatch: {entry_name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workbook",
        type=Path,
        default=Path("tableau/asset_performance_across_macro_regimes.twbx"),
    )
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]
    refresh_package(project_root, project_root / args.workbook)
    print(f"Refreshed packaged CSVs in {args.workbook}")


if __name__ == "__main__":
    main()
