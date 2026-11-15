"""Build src/remy/data/ciqual_2020.csv from ANSES's official Ciqual 2020 XML.

Source: "Table de composition nutritionnelle des aliments Ciqual 2020", ANSES, Licence Ouverte / Etalab 2.0,
https://www.data.gouv.fr/fr/datasets/table-de-composition-nutritionnelle-des-aliments-ciqual-2020/
(archive XML_2020_07_07.zip, unzipped into a folder).

Usage: uv run python scripts/build_ciqual.py <folder holding alim_2020_07_07.xml and compo_2020_07_07.xml>

Only the energy and the six nutrients Remy tracks are kept, per 100 g. Ported from Bob's builder; this version
also keeps the English names (alim_nom_eng).
"""

import csv
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "src" / "remy" / "data" / "ciqual_2020.csv"
# Ciqual constituent code -> column (per 100 g)
NUTRIENTS = {
    "328": "kcal",  # energy, Regulation EU 1169/2011 (kcal/100 g)
    "25000": "protein_g",  # protein, N x Jones' factor
    "31000": "carbs_g",
    "40000": "fat_g",
    "32000": "sugars_g",
    "34100": "fiber_g",
    "10004": "salt_g",
}
KCAL_FALLBACK = "333"  # energy, N x Jones' factor, with fibres: used when the regulatory value is missing


def _read(path: Path) -> str:
    """The XML files declare their own encoding (windows-1252 in the 2020 release)."""
    raw = path.read_bytes()
    match = re.search(rb'encoding="([^"]+)"', raw[:200])
    return raw.decode(match.group(1).decode() if match else "utf-8")


def _tag(block: str, name: str) -> str:
    match = re.search(rf"<{name}>\s*(.*?)\s*</{name}>", block, re.S)
    return " ".join(match.group(1).split()) if match else ""


def value(text: str) -> float | None:
    """Ciqual values: "12,3" -> 12.3; "< 0,5" -> 0.25 (half the threshold); "traces" -> 0; "-" -> unknown."""
    text = text.strip().replace(",", ".")
    if not text or text == "-":
        return None
    if text.lower() == "traces":
        return 0.0
    if text.startswith("<"):
        try:
            return float(text[1:].strip()) / 2
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


def main(folder: str) -> None:
    root = Path(folder)
    alim = _read(next(root.glob("alim_2*.xml")))
    names: dict[str, tuple[str, str]] = {}
    for block in re.findall(r"<ALIM>(.*?)</ALIM>", alim, re.S):
        names[_tag(block, "alim_code")] = (_tag(block, "alim_nom_fr"), _tag(block, "alim_nom_eng"))
    values: dict[str, dict[str, float | None]] = {code: {} for code in names}
    compo = _read(next(root.glob("compo_2*.xml")))
    for block in re.findall(r"<COMPO>(.*?)</COMPO>", compo, re.S):
        code, const = _tag(block, "alim_code"), _tag(block, "const_code")
        if code in values and (const in NUTRIENTS or const == KCAL_FALLBACK):
            values[code][const] = value(_tag(block, "teneur"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["code", "name_fr", "name_en", *NUTRIENTS.values()])
        for code, (name_fr, name_en) in sorted(names.items(), key=lambda kv: int(kv[0])):
            v = values[code]
            if v.get("328") is None:
                v["328"] = v.get(KCAL_FALLBACK)
            if v.get("328") is None:
                continue  # no energy value: useless for tracking
            writer.writerow([code, name_fr, name_en, *("" if v.get(c) is None else f"{v[c]:g}" for c in NUTRIENTS)])
            rows += 1
    print(f"{rows} foods -> {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])
