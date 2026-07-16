"""Build a self-contained Tableau Public-compatible packaged workbook."""

from __future__ import annotations

import argparse
import csv
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from tableauhyperapi import (
    Connection,
    CreateMode,
    HyperProcess,
    Inserter,
    SqlType,
    TableDefinition,
    TableName,
    Telemetry,
)


@dataclass(frozen=True)
class ExtractSpec:
    csv_path: Path
    package_csv: str
    package_hyper: str
    columns: tuple[tuple[str, str], ...]


EXTRACTS = {
    "regime_asset_metrics": ExtractSpec(
        csv_path=Path("data/processed/regime_asset_metrics.csv"),
        package_csv="Data/processed/regime_asset_metrics.csv",
        package_hyper="Data/Extracts/regime_asset_metrics.hyper",
        columns=(
            ("regime", "text"),
            ("ticker", "text"),
            ("observations", "big_int"),
            ("annualized_return", "double"),
            ("annualized_volatility", "double"),
            ("max_drawdown", "double"),
            ("sharpe_ratio_rf0", "double"),
            ("win_rate", "double"),
            ("conditional_cumulative_return", "double"),
        ),
    ),
    "regime_correlations": ExtractSpec(
        csv_path=Path("data/processed/regime_correlations.csv"),
        package_csv="Data/processed/regime_correlations.csv",
        package_hyper="Data/Extracts/regime_correlations.hyper",
        columns=(
            ("regime", "text"),
            ("asset_1", "text"),
            ("asset_2", "text"),
            ("observations", "big_int"),
            ("correlation", "double"),
        ),
    ),
}
FORBIDDEN_REFERENCES = (
    "postgres",
    "macro_asset_with_regime",
    "regime_asset_performance_summary",
    "Stress + High Yield",
    "Mixed",
)
HYPER_TABLE = TableName("Extract", "Extract")
TABLEAU_ASSET_COLORS = {
    "SPY": "#4C78A8",
    "IEF": "#F28E2B",
    "GLD": "#D4A72C",
}
ASSET_COLOR_WORKSHEETS = (
    "Annualized Return",
    "Annualized Volatility",
    "Maximum Drawdown",
)


def _sql_type(kind: str) -> SqlType:
    return {
        "text": SqlType.text(),
        "big_int": SqlType.big_int(),
        "double": SqlType.double(),
    }[kind]


def _convert_value(value: str, kind: str) -> str | int | float | None:
    if value == "":
        return None
    if kind == "text":
        return value
    if kind == "big_int":
        return int(value)
    if kind == "double":
        return float(value)
    raise ValueError(f"Unsupported Hyper type: {kind}")


def _build_hyper(csv_path: Path, hyper_path: Path, spec: ExtractSpec) -> int:
    table = TableDefinition(
        HYPER_TABLE,
        [
            TableDefinition.Column(column_name, _sql_type(kind))
            for column_name, kind in spec.columns
        ],
    )
    with csv_path.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    expected_columns = [name for name, _ in spec.columns]
    if list(rows[0].keys()) != expected_columns:
        raise RuntimeError(
            f"Unexpected columns in {csv_path}: {list(rows[0].keys())}"
        )

    with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as process:
        with Connection(
            process.endpoint, hyper_path, CreateMode.CREATE_AND_REPLACE
        ) as connection:
            connection.catalog.create_schema("Extract")
            connection.catalog.create_table(table)
            with Inserter(connection, table) as inserter:
                inserter.add_rows(
                    [
                        [
                            _convert_value(row[column_name], kind)
                            for column_name, kind in spec.columns
                        ]
                        for row in rows
                    ]
                )
                inserter.execute()
            actual_rows = connection.execute_scalar_query(
                'SELECT count(*) FROM "Extract"."Extract"'
            )
    if actual_rows != len(rows):
        raise RuntimeError(
            f"Hyper row mismatch for {csv_path}: {actual_rows} != {len(rows)}"
        )
    return len(rows)


def _convert_datasource_to_hyper(
    xml: str, datasource_name: str, package_hyper: str
) -> str:
    csv_name = f"{datasource_name}.csv"
    table_name = f"[{datasource_name}#csv]"
    connection_pattern = re.compile(
        rf'<connection class="textscan" directory="Data/processed" '
        rf'filename="{re.escape(csv_name)}" password="" server="" />'
    )
    hyper_connection = (
        f'<connection access_mode="readonly" authentication="auth-none" '
        f'class="hyper" dbname="{package_hyper}" default-settings="yes" '
        f'schema="Extract" />'
    )
    xml, connection_count = connection_pattern.subn(hyper_connection, xml)

    relation_pattern = re.compile(
        rf'<relation connection="([^"]+)" name="{re.escape(csv_name)}" '
        rf'table="{re.escape(table_name)}" type="table">.*?</relation>',
        flags=re.DOTALL,
    )
    xml, relation_count = relation_pattern.subn(
        r'<relation connection="\1" name="Extract" '
        r'table="[Extract].[Extract]" type="table" />',
        xml,
    )
    xml = xml.replace(
        f"<parent-name>[{csv_name}]</parent-name>",
        "<parent-name>[Extract]</parent-name>",
    )
    xml = xml.replace(
        f'<object caption="{csv_name}" ',
        '<object caption="Extract" ',
    )

    already_hyper = (
        f'class="hyper" dbname="{package_hyper}"' in xml
        and f'table="[Extract].[Extract]"' in xml
    )
    if not already_hyper:
        raise RuntimeError(f"Failed to create Hyper connection for {datasource_name}")
    if connection_count not in (0, 1) or relation_count not in (0, 2):
        raise RuntimeError(
            f"Unexpected Tableau XML replacements for {datasource_name}: "
            f"connections={connection_count}, relations={relation_count}"
        )
    return xml


def _apply_asset_palette(xml: str) -> str:
    """Color asset comparison marks consistently without changing layout zones."""
    for worksheet_name in ASSET_COLOR_WORKSHEETS:
        worksheet_pattern = re.compile(
            rf'(<worksheet name="{re.escape(worksheet_name)}">)(.*?)(</worksheet>)',
            flags=re.DOTALL,
        )
        match = worksheet_pattern.search(xml)
        if not match:
            raise RuntimeError(f"Missing Tableau worksheet: {worksheet_name}")
        worksheet = match.group(2)
        datasource_match = re.search(
            r'<datasource caption="regime_asset_metrics" name="([^"]+)"',
            worksheet,
        )
        if not datasource_match:
            raise RuntimeError(
                f"Missing metric datasource in Tableau worksheet: {worksheet_name}"
            )
        ticker_field = (
            f"[{datasource_match.group(1)}].[none:ticker:nk]"
        )
        # Remove the invalid pane-level palette emitted by older versions of
        # this packager. Tableau stores categorical maps at datasource level.
        worksheet = re.sub(
            r'\s*<style>\s*<style-rule element="mark">\s*'
            r'<encoding attr="color"[^>]*type="palette">.*?</encoding>\s*'
            r"</style-rule>\s*</style>",
            "",
            worksheet,
            flags=re.DOTALL,
        )
        color_shelf = f'<color column="{ticker_field}" />'
        if color_shelf not in worksheet:
            mark = '<mark class="Automatic" />'
            replacement = (
                f"{mark}\n"
                "            <encodings>\n"
                f"              {color_shelf}\n"
                "            </encodings>"
            )
            if worksheet.count(mark) != 1:
                raise RuntimeError(
                    f"Unexpected mark structure in Tableau worksheet: {worksheet_name}"
                )
            worksheet = worksheet.replace(mark, replacement, 1)
        xml = (
            xml[: match.start()]
            + match.group(1)
            + worksheet
            + match.group(3)
            + xml[match.end() :]
        )

    datasource_pattern = re.compile(
        r'(<datasource caption="regime_asset_metrics"[^>]*>)(.*?)(</datasource>)',
        flags=re.DOTALL,
    )
    datasource_match = datasource_pattern.search(xml)
    if not datasource_match:
        raise RuntimeError("Missing Tableau regime_asset_metrics datasource")
    datasource_body = datasource_match.group(2)
    palette = (
        '<style>\n'
        '        <style-rule element="mark">\n'
        '          <encoding attr="color" field="[none:ticker:nk]" type="palette">\n'
        + "\n".join(
            f'            <map to="{color}"><bucket>"{ticker}"</bucket></map>'
            for ticker, color in TABLEAU_ASSET_COLORS.items()
        )
        + "\n"
        "          </encoding>\n"
        "        </style-rule>\n"
        "      </style>"
    )
    existing_palette = re.compile(
        r'<style>\s*<style-rule element="mark">\s*'
        r'<encoding attr="color" field="\[none:ticker:nk\]"[^>]*>'
        r".*?</encoding>\s*</style-rule>\s*</style>",
        flags=re.DOTALL,
    )
    datasource_body, palette_count = existing_palette.subn(
        palette, datasource_body
    )
    if palette_count == 0:
        layout_match = re.search(r"<layout\b[^>]*/>", datasource_body)
        if not layout_match:
            raise RuntimeError("Missing Tableau datasource layout anchor")
        datasource_body = (
            datasource_body[: layout_match.end()]
            + "\n      "
            + palette
            + datasource_body[layout_match.end() :]
        )
    xml = (
        xml[: datasource_match.start()]
        + datasource_match.group(1)
        + datasource_body
        + datasource_match.group(3)
        + xml[datasource_match.end() :]
    )
    return xml


def refresh_package(project_root: Path, workbook: Path) -> None:
    workbook = workbook.resolve()
    with zipfile.ZipFile(workbook, "r") as source:
        entries = {
            info.filename: source.read(info.filename) for info in source.infolist()
        }

    twb_entries = [name for name in entries if name.endswith(".twb")]
    if len(twb_entries) != 1:
        raise RuntimeError(f"Expected one .twb entry, found {twb_entries}")
    twb_name = twb_entries[0]
    xml = entries[twb_name].decode("utf-8")
    hits = [term for term in FORBIDDEN_REFERENCES if term.lower() in xml.lower()]
    if hits:
        raise RuntimeError(f"Legacy Tableau references remain: {hits}")

    with tempfile.TemporaryDirectory(dir=workbook.parent) as temporary_directory:
        temporary_root = Path(temporary_directory)
        for datasource_name, spec in EXTRACTS.items():
            local_csv = project_root / spec.csv_path
            local_hyper = temporary_root / Path(spec.package_hyper).name
            row_count = _build_hyper(local_csv, local_hyper, spec)
            entries[spec.package_csv] = local_csv.read_bytes()
            entries[spec.package_hyper] = local_hyper.read_bytes()
            xml = _convert_datasource_to_hyper(
                xml, datasource_name, spec.package_hyper
            )
            print(f"Built {spec.package_hyper}: {row_count} rows")

        if 'class="textscan"' in xml or "Data/processed" in xml:
            raise RuntimeError("A live CSV connection remains in the Tableau workbook")
        xml = _apply_asset_palette(xml)
        entries[twb_name] = xml.encode("utf-8")

        temporary_path = temporary_root / workbook.name
        with zipfile.ZipFile(
            temporary_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as destination:
            for name, content in entries.items():
                destination.writestr(name, content)
        temporary_path.replace(workbook)

    with zipfile.ZipFile(workbook, "r") as packaged:
        expected_entries = {twb_name}
        for spec in EXTRACTS.values():
            expected_entries.update((spec.package_csv, spec.package_hyper))
            if packaged.read(spec.package_csv) != (
                project_root / spec.csv_path
            ).read_bytes():
                raise RuntimeError(f"Packaged CSV mismatch: {spec.package_csv}")
        unexpected = set(packaged.namelist()) - expected_entries
        missing = expected_entries - set(packaged.namelist())
        if unexpected or missing:
            raise RuntimeError(
                f"Unexpected package entries: extra={unexpected}, missing={missing}"
            )


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
    print(f"Refreshed Tableau Public package: {args.workbook}")


if __name__ == "__main__":
    main()
