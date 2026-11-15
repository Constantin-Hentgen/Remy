"""The Ciqual builder, on a tiny synthetic extract in the official XML layout (windows-1252, decimal commas)."""

import csv
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_ciqual.py"
spec = importlib.util.spec_from_file_location("build_ciqual", SCRIPT)
build_ciqual = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_ciqual)

ALIM = """<?xml version="1.0" encoding="windows-1252"?>
<TABLE>
<ALIM>
<alim_code> 9104 </alim_code>
<alim_nom_fr> Riz blanc, cuit,  non salé </alim_nom_fr>
<alim_nom_eng> Rice, white, cooked, unsalted </alim_nom_eng>
</ALIM>
<ALIM>
<alim_code> 22010 </alim_code>
<alim_nom_fr> Oeuf, dur </alim_nom_fr>
<alim_nom_eng> Egg, hard-boiled </alim_nom_eng>
</ALIM>
<ALIM>
<alim_code> 1 </alim_code>
<alim_nom_fr> Sans énergie </alim_nom_fr>
<alim_nom_eng> No energy </alim_nom_eng>
</ALIM>
</TABLE>
"""


def compo(code: str, const: str, value: str) -> str:
    return (
        f"<COMPO>\n<alim_code> {code} </alim_code>\n<const_code> {const} </const_code>\n"
        f"<teneur>{value}</teneur>\n</COMPO>\n"
    )


COMPO = (
    '<?xml version="1.0" encoding="windows-1252"?>\n<TABLE>\n'
    + compo("9104", "328", "146")
    + compo("9104", "25000", "2,88")
    + compo("9104", "10004", "< 0,05")
    + compo("9104", "34100", "-")
    + compo("22010", "333", "134")  # only the fallback energy
    + compo("22010", "32000", "traces")
    + "</TABLE>\n"
)


@pytest.mark.parametrize(
    ("text", "value"), [("12,3", 12.3), ("< 0,5", 0.25), ("traces", 0.0), ("-", None), ("", None), ("n/a", None)]
)
def test_value(text, value):
    assert build_ciqual.value(text) == value


def test_build(tmp_path, monkeypatch):
    (tmp_path / "alim_2020_07_07.xml").write_bytes(ALIM.encode("cp1252"))
    (tmp_path / "compo_2020_07_07.xml").write_bytes(COMPO.encode("cp1252"))
    out = tmp_path / "out.csv"
    monkeypatch.setattr(build_ciqual, "OUT", out)
    build_ciqual.main(str(tmp_path))
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert [r["code"] for r in rows] == ["9104", "22010"]  # no energy: dropped
    rice, egg = rows
    assert rice["name_fr"] == "Riz blanc, cuit, non salé" and rice["name_en"] == "Rice, white, cooked, unsalted"
    assert (rice["kcal"], rice["protein_g"], rice["salt_g"], rice["fiber_g"]) == ("146", "2.88", "0.025", "")
    assert (egg["kcal"], egg["sugars_g"]) == ("134", "0")


def test_embedded_table_has_the_builder_columns():
    header = (SCRIPT.parent.parent / "src" / "remy" / "data" / "ciqual_2020.csv").read_text().splitlines()[0]
    assert header.split(",") == ["code", "name_fr", "name_en", *build_ciqual.NUTRIENTS.values()]
