"""
Build the labelled phrase set for component B (the ML auditor). Run once, output committed.

    uv run python scripts/build_dataset.py <path-to-moysi-api/provisioning>

Sources:
  1. The first turn of every synthetic chat test in Moysi Voice AI's test suites whose
     target is a procedure agent; the label is that procedure's family mapped to one of the
     16 Moysi call categories (the same FAMILIA_A_CATEGORIA map as src/utils/motivos.js).
     These suites are private and synthetic (written by the Moysi author, no real callers),
     so the professor cannot rerun this step; data/phrases.csv is the committed result.
  2. data/extra_phrases.csv, written by the team for the categories the suites do not cover.

Real municipality names are replaced by the fictional "Valdeolmo" / "Montealto", and any
phrase with digits that could be a phone or ID number is dropped.
"""

import csv
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

FAMILIA_A_CATEGORIA = {
    "padron-y-residencia": "Padrón y residencia",
    "registro-general": "Registro y certificados",
    "registros": "Registro y certificados",
    "urbanismo": "Urbanismo y obras",
    "via-publica": "Vía pública y servicios",
    "responsabilidad": "Vía pública y servicios",
    "actividades": "Actividades y negocios",
    "cementerios": "Cementerio",
    "animales": "Animales",
    "consumo": "Consumo",
    "rgpd": "Datos personales y transparencia",
    "transparencia": "Datos personales y transparencia",
    "accesibilidad": "Datos personales y transparencia",
    "tributos": "Tributos e impuestos",
    "subvenciones": "Subvenciones y ayudas",
    "servicios-sociales": "Servicios sociales",
    "medio-ambiente": "Vía pública y servicios",
    "patrimonio": "Vía pública y servicios",
    "cultura-deportes": "Cultura, deportes y fiestas",
}

PLACES = [
    (r"Santa Mar[ií]a de Gu[ií]a", "Valdeolmo"),
    (r"Villa de Moya", "Valdeolmo"),
    (r"\bGu[ií]a\b", "Valdeolmo"),
    (r"\bMoya\b", "Valdeolmo"),
    (r"\b(G[áa]ldar|Arucas|Firgas|Agaete|Valleseco|Teror|Las Palmas)\b", "Montealto"),
]
ID_LIKE = re.compile(r"\d{5,}|\d{3}[ .]?\d{3}[ .]?\d{3}|\b\d{8}[A-Za-z]\b")
TEST_SHARE = 0.25
SEED = 7


def anonymise(text: str) -> str:
    for pattern, repl in PLACES:
        text = re.sub(pattern, repl, text)
    return " ".join(text.split())


def from_suites(provisioning: Path) -> list[dict]:
    familia = {}
    for client in ("guia", "moya"):
        manifest = json.loads((provisioning / "clients" / f"{client}.json").read_text(encoding="utf-8"))
        familia |= {t["assistant_name"]: t["familia"] for t in manifest["tramites"]}
    rows = []
    for path in sorted((provisioning / "suites").glob("*.json")):
        for case in json.loads(path.read_text(encoding="utf-8")).get("casos", []):
            turns = case.get("turnos") or []
            fam = familia.get(case.get("assistant"))
            if not turns or not isinstance(turns[0], str) or fam not in FAMILIA_A_CATEGORIA:
                continue
            rows.append({"text": anonymise(turns[0]), "categoria": FAMILIA_A_CATEGORIA[fam], "source": "moysi_suites"})
    return rows


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    rows = from_suites(Path(sys.argv[1]))
    with (DATA / "extra_phrases.csv").open(newline="", encoding="utf-8") as f:
        rows += [{"text": anonymise(r["text"]), "categoria": r["categoria"], "source": "team"} for r in csv.DictReader(f)]

    seen, clean = set(), []
    for r in rows:
        key = r["text"].lower().strip(" .,¿?¡!")
        if key and key not in seen and not ID_LIKE.search(r["text"]):
            seen.add(key)
            clean.append(r)

    random.Random(SEED).shuffle(clean)
    by_cat: dict[str, list[dict]] = {}
    for r in clean:
        by_cat.setdefault(r["categoria"], []).append(r)
    for items in by_cat.values():  # stratified split
        n_test = max(1, round(len(items) * TEST_SHARE))
        for i, r in enumerate(items):
            r["split"] = "test" if i < n_test else "train"

    with (DATA / "phrases.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["text", "categoria", "source", "split"])
        writer.writeheader()
        writer.writerows(sorted(clean, key=lambda r: (r["split"], r["categoria"])))
    counts = Counter((r["categoria"], r["split"]) for r in clean)
    for cat in sorted(by_cat):
        print(f"{cat:<35} train {counts[(cat, 'train')]:>3}  test {counts[(cat, 'test')]:>3}")
    print(f"Wrote data/phrases.csv: {len(clean)} phrases.")


if __name__ == "__main__":
    main()
