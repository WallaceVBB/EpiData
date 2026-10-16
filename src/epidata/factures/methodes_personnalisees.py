"""Création, persistance et exécution des méthodes de facture personnalisées."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from epidata.utils import METHODES_FACTURES_DIR

COLUMNS = (
    ("Désignation", True),
    ("Quantité", False),
    ("Unité", False),
    ("Nb. colis", False),
    ("Qté Livrée", False),
    ("Prix unitaire HT", False),
    ("Montant net HT", False),
    ("Taux TVA", False),
)
NUMERIC_COLUMNS = {
    "Quantité",
    "Nb. colis",
    "Qté Livrée",
    "Prix unitaire HT",
    "Montant net HT",
    "Taux TVA",
}
STANDARD_COLUMNS = [
    "Date Facture",
    "Désignation",
    "Quantité",
    "Unité",
    "Nb. colis",
    "Qté Livrée",
    "Prix unitaire HT",
    "Montant net HT",
    "Taux TVA",
    "Source extraction",
]
DEFAULT_IGNORE_TERMS = [
    "iban",
    "transport",
    "total ht",
    "total ttc",
    "net à payer",
    "net a payer",
    "total tva",
    "sous-total",
    "sous total",
]
TABLE_SETTINGS = {
    "vertical_strategy": "lines",
    "horizontal_strategy": "text",
}
NUMBER_PATTERN = re.compile(
    r"^[+-]?(?:\d+(?:[.,]\d+)?|\d{1,3}(?:[ .]\d{3})+(?:[.,]\d+)?)\s*%?$"
)


def lire_tables_pdf(chemin_pdf: str | Path, max_pages: int | None = 3) -> list[list[list[str]]]:
    """Retourne les tableaux natifs du PDF, page par page, sans lancer d'OCR."""
    import pdfplumber

    pdf_path = Path(chemin_pdf).expanduser()
    if not pdf_path.is_file():
        raise FileNotFoundError(f"Fichier PDF introuvable : {pdf_path}")

    tables = []
    with pdfplumber.open(pdf_path) as pdf:
        pages = pdf.pages if max_pages is None else pdf.pages[:max_pages]
        for page in pages:
            tables.extend(_extraire_tables_page(page))
    return tables


def _extraire_tables_page(page) -> list[list[list[str]]]:
    tables = []
    words = None
    for detected_table in page.find_tables(table_settings=TABLE_SETTINGS):
        rows = [
            [re.sub(r"\s+", " ", str(cell or "")).strip() for cell in row]
            for row in detected_table.extract()
        ]
        for row_index, table_row in enumerate(detected_table.rows):
            if row_index >= len(rows) or not table_row.cells:
                continue
            cell = table_row.cells[0]
            if cell is None:
                continue
            x0, top, x1, bottom = cell
            if words is None:
                words = page.extract_words(use_text_flow=True)
            if not any(
                word["x0"] < detected_table.bbox[0] < word["x1"]
                and top <= (word["top"] + word["bottom"]) / 2 < bottom
                for word in words
            ):
                continue
            cell_words = [
                word
                for word in words
                if x0 <= word["x0"] < x1
                and top <= (word["top"] + word["bottom"]) / 2 < bottom
            ]
            cell_words.sort(key=lambda word: (round(word["top"], 1), word["x0"]))
            rows[row_index][0] = " ".join(word["text"] for word in cell_words)

        width = max((len(row) for row in rows), default=0)
        populated_columns = {
            column_index
            for row in rows
            for column_index, cell in enumerate(row)
            if cell
        }
        if (
            len(rows) >= 2
            and width >= 3
            and len(populated_columns) >= 3
            and any(any(cell for cell in row) for row in rows)
        ):
            tables.append(rows)
    return tables


def _valider_methode(methode: dict) -> None:
    if not isinstance(methode, dict):
        raise TypeError("La méthode de facture doit être un objet JSON.")
    name = methode.get("name")
    method_id = methode.get("id")
    mappings = methode.get("mappings")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Le nom du fournisseur est obligatoire.")
    if not isinstance(method_id, str) or not re.fullmatch(r"[a-z0-9_-]+", method_id):
        raise ValueError("Identifiant de méthode de facture invalide.")
    if not isinstance(mappings, dict):
        raise TypeError("Les colonnes de la méthode sont manquantes.")

    for column, index in mappings.items():
        if column not in {label for label, _ in COLUMNS}:
            raise ValueError(f"Colonne de sortie inconnue : {column}.")
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError(f"Index de colonne invalide pour {column}.")
    if "Désignation" not in mappings:
        raise ValueError("Associez au minimum une colonne à la désignation.")
    if not NUMERIC_COLUMNS.intersection(mappings):
        raise ValueError("Associez au moins une colonne de quantité ou de prix.")

    ignore_terms = methode.get("ignore_terms", [])
    if not isinstance(ignore_terms, list) or any(not isinstance(term, str) for term in ignore_terms):
        raise ValueError("La liste des lignes à ignorer est invalide.")
    table_signature = methode.get("table_signature", [])
    if not isinstance(table_signature, list) or any(
        not isinstance(term, str) for term in table_signature
    ):
        raise ValueError("La signature du tableau est invalide.")
    column_labels = methode.get("column_labels", [])
    if not isinstance(column_labels, list) or any(
        not isinstance(label, str) for label in column_labels
    ):
        raise ValueError("Les libellés de colonnes sont invalides.")


def creer_identifiant(nom: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode("ascii")
    identifier = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_name.lower()).strip("-")
    if not identifier:
        raise ValueError("Le nom du fournisseur doit contenir des lettres ou des chiffres.")
    return identifier


def _ecrire_methode(methode: dict, path: Path) -> dict:
    _valider_methode(methode)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(methode, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
    return methode


def enregistrer_methode(
    nom: str,
    mappings: dict[str, int],
    ignore_terms: list[str],
    table_signature: list[str] | None = None,
    column_labels: list[str] | None = None,
) -> dict:
    methode = {
        "id": creer_identifiant(nom),
        "name": nom.strip(),
        "mappings": mappings,
        "ignore_terms": [term.strip() for term in ignore_terms if term.strip()],
        "table_signature": table_signature or [],
        "column_labels": column_labels or [],
    }
    _valider_methode(methode)

    path = Path(METHODES_FACTURES_DIR) / f"{methode['id']}.json"
    if path.exists():
        raise FileExistsError(f"Une méthode existe déjà pour « {nom.strip()} ».")

    return _ecrire_methode(methode, path)


def modifier_methode(
    method_id: str,
    nom: str,
    mappings: dict[str, int],
    ignore_terms: list[str],
    table_signature: list[str],
    column_labels: list[str] | None = None,
) -> dict:
    path = Path(METHODES_FACTURES_DIR) / f"{method_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"La méthode de facture « {method_id} » est introuvable.")
    methode = {
        "id": method_id,
        "name": nom.strip(),
        "mappings": mappings,
        "ignore_terms": [term.strip() for term in ignore_terms if term.strip()],
        "table_signature": table_signature,
        "column_labels": column_labels or [],
    }
    return _ecrire_methode(methode, path)


def supprimer_methode(method_id: str) -> None:
    path = Path(METHODES_FACTURES_DIR) / f"{method_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"La méthode de facture « {method_id} » est introuvable.")
    path.unlink()


def charger_methodes() -> tuple[list[dict], list[str]]:
    """Charge les méthodes valides et rapporte les fichiers illisibles à l'interface."""
    methods = []
    errors = []
    for path in sorted(Path(METHODES_FACTURES_DIR).glob("*.json")):
        try:
            method = json.loads(path.read_text(encoding="utf-8"))
            _valider_methode(method)
            if path.stem != method["id"]:
                raise ValueError("Le nom du fichier ne correspond pas à l'identifiant.")
            methods.append(method)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            errors.append(f"{path.name} : {exc}")
    return methods, errors


def charger_methode(method_id: str) -> dict:
    for method in charger_methodes()[0]:
        if method["id"] == method_id:
            return method
    raise FileNotFoundError(f"La méthode de facture « {method_id} » est introuvable.")


def _normaliser_entete(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().casefold()


def _est_nombre(value: str) -> bool:
    return bool(NUMBER_PATTERN.fullmatch(value.replace("\u00a0", " ").strip()))


def detecter_ligne_entete(table: list[list[str]]) -> int:
    """Choisit la ligne qui ressemble le plus à l'en-tête des colonnes."""
    known_headers = (
        "designation", "désignation", "article", "produit", "libelle", "libellé",
        "quantite", "quantité", "qte", "qty", "unite", "unité", "livraison",
        "prix", "unitaire", "montant", "total", "tva", "colis",
    )
    best_index = 0
    best_score = 0
    for row_index, row in enumerate(table[:15]):
        text = _normaliser_entete(" ".join(row))
        score = sum(term in text for term in known_headers)
        if score > best_score:
            best_index = row_index
            best_score = score
    return best_index


def entetes_colonnes(
    table: list[list[str]],
    header_row: int,
    first_product_row: int | None = None,
) -> list[str]:
    """Combine les cellules d'en-tête verticalement pour reconstituer les libellés."""
    if not table:
        return []
    width = max(map(len, table), default=0)
    if first_product_row is None:
        first_product_row = len(table)
        for row_index in range(header_row + 1, len(table)):
            numeric_cells = sum(_est_nombre(cell) for cell in table[row_index] if cell)
            has_text = any(
                cell and not _est_nombre(cell)
                for cell in table[row_index]
            )
            if numeric_cells >= 2 and has_text:
                first_product_row = row_index
                break
    headers = []
    first_header_row = max(0, header_row - 2)
    for column_index in range(width):
        parts = []
        for row in table[first_header_row:first_product_row]:
            if column_index < len(row):
                value = row[column_index].strip()
                if value and value not in parts:
                    parts.append(value)
        headers.append(" ".join(parts))
    return headers


def suggerer_colonne_valeurs(
    table: list[list[str]],
    header_row: int,
    column_index: int,
    is_numeric: bool,
) -> int:
    """Décale une suggestion d'en-tête si les valeurs sont dans la cellule voisine."""
    data_rows = []
    for row in table[header_row + 1 :]:
        numeric_count = sum(_est_nombre(cell) for cell in row if cell)
        has_text = any(cell and not _est_nombre(cell) for cell in row)
        if numeric_count >= 2 and has_text:
            data_rows.append(row)
        if len(data_rows) >= 8:
            break

    width = max(map(len, table), default=0)
    candidates = [
        index
        for index in (column_index, column_index + 1, column_index - 1)
        if 0 <= index < width
    ]

    def score(index: int) -> int:
        values = [row[index].strip() for row in data_rows if index < len(row)]
        if is_numeric:
            return sum(_est_nombre(value) for value in values)
        return sum(bool(value) and not _est_nombre(value) for value in values)

    return max(candidates, key=score) if data_rows else column_index


def creer_signature_table(
    table: list[list[str]],
    mappings: dict[str, int],
    header_row: int | None = None,
) -> list[str]:
    """Capture les cellules d'en-tête proches des colonnes choisies."""
    header_row = detecter_ligne_entete(table) if header_row is None else header_row
    first_product_row = len(table)
    for row_index, row in enumerate(table[header_row + 1 :], start=header_row + 1):
        description = row[mappings["Désignation"]].strip() if mappings["Désignation"] < len(row) else ""
        if not description:
            continue
        if any(
            _est_nombre(row[index].strip())
            for column, index in mappings.items()
            if column in NUMERIC_COLUMNS and index < len(row)
        ):
            first_product_row = row_index
            break

    return list(dict.fromkeys(
        cell.strip()
        for row in table[max(0, header_row - 2) : first_product_row]
        for cell in row
        if len(cell.strip()) >= 3
    ))


def _table_correspond_a_signature(table: list[list[str]], signature: list[str]) -> bool:
    if not signature:
        return True

    header_text = _normaliser_entete(" ".join(
        cell
        for row in table[:8]
        for cell in row
    ))
    matched = sum(_normaliser_entete(term) in header_text for term in signature)
    return matched >= min(3, len(signature))


def extraire_facture_pdf(
    chemin_pdf,
    chemin_sortie_excel="facture_extraite.xlsx",
    progress_callback=None,
    method_id: str | None = None,
):
    """Extrait les lignes d'un tableau PDF selon les colonnes choisies par l'utilisateur."""
    import pandas as pd
    import pdfplumber

    from epidata.factures.extracteurs.extracteur_generique import invoice_dates

    if not method_id:
        raise ValueError("Aucune méthode de facture personnalisée n'a été précisée.")
    methode = charger_methode(method_id)
    pdf_path = Path(chemin_pdf).expanduser()
    if not pdf_path.is_file():
        raise FileNotFoundError(f"Fichier PDF introuvable : {pdf_path}")

    tables = []
    with pdfplumber.open(pdf_path) as pdf:
        pages = list(pdf.pages)
        dates = invoice_dates(pages)
        for page_index, page in enumerate(pages):
            tables.extend(
                (table, dates[page_index])
                for table in _extraire_tables_page(page)
            )
    if not tables:
        raise ValueError(
            "Aucun tableau n'a été détecté dans ce PDF. Les méthodes personnalisées "
            "nécessitent un PDF avec du texte sélectionnable ; essayez l'extracteur générique "
            "pour un document scanné."
        )

    rows = []
    total_tables = len(tables)
    ignore_terms = [
        _normaliser_entete(term)
        for term in [*DEFAULT_IGNORE_TERMS, *methode.get("ignore_terms", [])]
        if term.strip()
    ]
    for table_index, (table, invoice_date) in enumerate(tables, start=1):
        if not _table_correspond_a_signature(
            table,
            methode.get("table_signature", []),
        ):
            if progress_callback:
                progress_callback(
                    int(table_index / total_tables * 90),
                    f"Analyse du tableau {table_index}/{total_tables}",
                )
            continue

        width = max((len(row) for row in table), default=0)
        for raw_row in table:
            row = raw_row + [""] * (width - len(raw_row))
            joined = _normaliser_entete(" ".join(row))
            if not joined or any(term in joined for term in ignore_terms):
                continue

            mapped = {}
            for output_column, source_index in methode["mappings"].items():
                mapped[output_column] = row[source_index].strip() if source_index < len(row) else ""

            description = mapped.get("Désignation", "").strip()
            if not description:
                continue
            if not any(
                _est_nombre(mapped.get(column, ""))
                for column in NUMERIC_COLUMNS.intersection(mapped)
            ):
                other_values = [
                    value
                    for column, value in mapped.items()
                    if column != "Désignation" and value.strip()
                ]
                is_continuation = (
                    not other_values
                    and (
                        re.fullmatch(r"\([^()]{1,40}\)", description)
                        or (
                            len(description) <= 30
                            and not re.search(r"\d|:", description)
                        )
                    )
                )
                if rows and is_continuation:
                    rows[-1]["Désignation"] += f" {description}"
                continue

            output_row = {column: "" for column in STANDARD_COLUMNS}
            output_row.update(mapped)
            output_row["Date Facture"] = invoice_date
            output_row["Source extraction"] = f"Méthode personnalisée : {methode['name']}"
            rows.append(output_row)
        if progress_callback:
            progress_callback(
                int(table_index / total_tables * 90),
                f"Analyse du tableau {table_index}/{total_tables}",
            )

    if not rows:
        raise ValueError(
            f"Aucune ligne de produit n'a été reconnue avec la méthode « {methode['name']} ». "
            "Vérifiez les colonnes choisies et les lignes à ignorer."
        )

    output_columns = [
        "Date Facture",
        *[column for column, _ in COLUMNS if column in methode["mappings"]],
        "Source extraction",
    ]
    dataframe = pd.DataFrame(rows, columns=output_columns)
    output_path = Path(chemin_sortie_excel).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        dataframe.to_excel(writer, sheet_name="Produits", index=False)
    if progress_callback:
        progress_callback(100, f"Extraction réussie : {len(dataframe)} ligne(s)")
    return dataframe
