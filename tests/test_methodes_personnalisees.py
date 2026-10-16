from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from epidata.factures import methodes_personnalisees as methodes


class FakePage:
    def extract_tables(self, table_settings=None):
        return [
            [["Adresse"], ["Adresse"]],
            [["Titre", "", ""], ["ligne unique", "", ""]],
            [
                ["N°", "MONTANT", "MODE", "ECHEANCE"],
                ["IBAN FR761234", "3 466,61", "Transport bancaire", "28/07/26"],
            ],
            [
                ["Désignation", "Quantité", "Prix unitaire", "Total HT"],
                ["", "", "", ""],
                ["Pommes", "2", "1,50", "3,00"],
                ["Poires", "1", "2,00", "2,00"],
                ["IBAN FR761234", "12", "1,50", "18,00"],
                ["Frais de transport", "1", "10,00", "10,00"],
                ["Total HT", "", "", "5,00"],
            ],
        ]


class FakePdf:
    def __enter__(self):
        self.pages = [FakePage()]
        return self

    def __exit__(self, *_):
        return None


def test_method_is_persisted_and_extracts_configured_columns(tmp_path, monkeypatch):
    import pdfplumber

    monkeypatch.setattr(methodes, "METHODES_FACTURES_DIR", str(tmp_path / "methods"))
    monkeypatch.setattr(pdfplumber, "open", lambda _path: FakePdf())
    example_pdf = tmp_path / "example.pdf"
    example_pdf.write_bytes(b"fake pdf")

    mappings = {
        "Désignation": 0,
        "Quantité": 1,
        "Prix unitaire HT": 2,
        "Montant net HT": 3,
    }
    tables = methodes.lire_tables_pdf(example_pdf, max_pages=None)
    assert len(tables) == 2
    signature = methodes.creer_signature_table(tables[1], mappings)
    method = methodes.enregistrer_methode(
        "Carrefour",
        mappings,
        ["Total HT"],
        signature,
    )

    loaded, errors = methodes.charger_methodes()
    assert errors == []
    assert loaded == [method]
    assert methodes.charger_methode("carrefour") == method

    output_path = tmp_path / "result.xlsx"
    result = methodes.extraire_facture_pdf(
        example_pdf,
        output_path,
        method_id="carrefour",
    )

    assert output_path.is_file()
    assert result["Désignation"].tolist() == ["Pommes", "Poires"]
    assert result["Quantité"].tolist() == ["2", "1"]
    assert result["Prix unitaire HT"].tolist() == ["1,50", "2,00"]
    assert result["Source extraction"].unique().tolist() == [
        "Méthode personnalisée : Carrefour"
    ]


def test_method_requires_description_and_a_numeric_column(tmp_path, monkeypatch):
    monkeypatch.setattr(methodes, "METHODES_FACTURES_DIR", str(tmp_path))

    with pytest.raises(ValueError, match="quantité ou de prix"):
        methodes.enregistrer_methode("Carrefour", {"Désignation": 0}, [])


@pytest.mark.parametrize(
    ("filename", "mappings", "ignore_terms", "expected_rows"),
    [
        (
            "facture_teste2.pdf",
            {"Désignation": 0, "Quantité": 1, "Prix unitaire HT": 2, "Montant net HT": 4},
            ["total ht", "transport"],
            6,
        ),
        (
            "facture_teste3.pdf",
            {
                "Désignation": 3,
                "Quantité": 5,
                "Unité": 7,
                "Prix unitaire HT": 10,
                "Montant net HT": 16,
            },
            ["total ht", "total ttc", "net a payer", "total tva", "frais de transport"],
            37,
        ),
    ],
)
def test_real_sample_invoices_extract_product_rows(
    tmp_path,
    monkeypatch,
    filename,
    mappings,
    ignore_terms,
    expected_rows,
):
    root = Path(__file__).parents[1]
    pdf_path = root / "tests" / filename
    tables = methodes.lire_tables_pdf(pdf_path, max_pages=None)
    product_table = next(
        table
        for table in tables
        if any(
            "signation" in cell.casefold()
            for row in table[:8]
            for cell in row
        )
    )
    signature = methodes.creer_signature_table(product_table, mappings)
    monkeypatch.setattr(methodes, "METHODES_FACTURES_DIR", str(tmp_path / "methods"))
    method = methodes.enregistrer_methode(
        filename.removesuffix(".pdf"),
        mappings,
        ignore_terms,
        signature,
    )

    result = methodes.extraire_facture_pdf(
        pdf_path,
        tmp_path / f"{filename}.xlsx",
        method_id=method["id"],
    )

    assert len(result) == expected_rows
    assert result["Désignation"].str.strip().ne("").all()
    assert result["Source extraction"].eq(
        f"Méthode personnalisée : {filename.removesuffix('.pdf')}"
    ).all()
    if filename == "facture_teste2.pdf":
        assert result["Désignation"].iloc[0] == "LENTILLES VERTES BONDUELLE 400grs"
        assert result["Quantité"].tolist() == ["864", "864", "864", "864", "432", "432"]
        assert result["Montant net HT"].tolist() == [
            "561,92",
            "544,63",
            "726,17",
            "596,50",
            "488,44",
            "548,95",
        ]
    if filename == "facture_teste3.pdf":
        descriptions = result["Désignation"].str.casefold().tolist()
        assert any("subventionn" in value for value in descriptions)
        assert any("(12x1l)" in value for value in descriptions)
        assert not any("transport" in value for value in descriptions)
        tables = methodes.lire_tables_pdf(pdf_path, max_pages=None)
        product_table = next(
            table
            for table in tables
            if any("signation" in cell.casefold() for row in table[:10] for cell in row)
        )
        header_row = methodes.detecter_ligne_entete(product_table)
        assert header_row == 4
        assert methodes.suggerer_colonne_valeurs(product_table, header_row, 2, False) == 3
        assert methodes.suggerer_colonne_valeurs(product_table, header_row, 6, False) == 7
        assert methodes.suggerer_colonne_valeurs(product_table, header_row, 9, True) == 10


def test_custom_invoice_ui_files_are_well_formed():
    root = Path(__file__).parents[1]
    for name in ("ConvertisseurPDF_selecteur.ui", "ConvertisseurPDF_creation.ui"):
        ET.parse(root / "src" / "epidata" / "resources" / "gui" / name)
