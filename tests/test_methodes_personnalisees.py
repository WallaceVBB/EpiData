from __future__ import annotations

import json
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


class FakeInvoicePage:
    def __init__(self, text, table):
        self.text = text
        self.table = table

    def extract_text(self, **_kwargs):
        return self.text

    def extract_tables(self, table_settings=None):
        return [self.table]


class FakeMultiPagePdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
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
        ["Désignation", "Quantité", "Prix unitaire", "Total HT"],
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
    assert result["Date Facture"].tolist() == ["", ""]
    assert "Unité" not in result.columns
    assert result["Source extraction"].unique().tolist() == [
        "Méthode personnalisée : Carrefour"
    ]


def test_custom_method_uses_generic_invoice_dates_per_page(tmp_path, monkeypatch):
    import pdfplumber

    monkeypatch.setattr(methodes, "METHODES_FACTURES_DIR", str(tmp_path / "methods"))
    table = [
        ["Désignation", "Quantité", "Prix unitaire"],
        ["Pommes", "2", "3,00"],
    ]
    pages = [
        FakeInvoicePage("FACTURE N° 123 du 04.05.2025\nInformations fournisseur", table),
        FakeInvoicePage("Suite de la facture\nInformations fournisseur", table),
    ]
    monkeypatch.setattr(pdfplumber, "open", lambda _path: FakeMultiPagePdf(pages))
    pdf_path = tmp_path / "invoice.pdf"
    pdf_path.write_bytes(b"fake pdf")
    methodes.enregistrer_methode(
        "Carrefour",
        {"Désignation": 0, "Quantité": 1, "Prix unitaire HT": 2},
        [],
    )

    result = methodes.extraire_facture_pdf(
        pdf_path,
        tmp_path / "result.xlsx",
        method_id="carrefour",
    )

    assert result["Date Facture"].tolist() == ["04/05/2025", "04/05/2025"]


def test_method_can_be_updated_and_deleted(tmp_path, monkeypatch):
    monkeypatch.setattr(methodes, "METHODES_FACTURES_DIR", str(tmp_path / "methods"))
    original = methodes.enregistrer_methode(
        "Carrefour",
        {"Désignation": 0, "Quantité": 1},
        ["IBAN"],
        ["Désignation", "Quantité"],
        ["Référence", "Quantité"],
    )

    updated = methodes.modifier_methode(
        original["id"],
        "Carrefour Market",
        {"Désignation": 2, "Prix unitaire HT": 3},
        ["transport"],
        ["Désignation", "Prix"],
        ["Article", "Prix"],
    )

    assert updated["id"] == original["id"]
    assert updated["column_labels"] == ["Article", "Prix"]
    assert methodes.charger_methode(original["id"]) == updated
    methodes.supprimer_methode(original["id"])
    assert methodes.charger_methodes() == ([], [])


def test_method_row_actions_edit_without_pdf_and_allow_unmapped_fields(tmp_path, monkeypatch):
    from PySide6.QtWidgets import (
        QApplication,
        QFileDialog,
        QMessageBox,
        QPushButton,
        QToolButton,
    )
    from PySide6.QtUiTools import QUiLoader

    from epidata.navigation import n_extracteur_factures
    from epidata.utils import ressource_path

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(methodes, "METHODES_FACTURES_DIR", str(tmp_path / "methods"))
    method = methodes.enregistrer_methode(
        "Carrefour",
        {
            "Désignation": 0,
            "Quantité": 1,
            "Unité": 2,
        },
        [],
        ["Désignation", "Quantité", "Unité"],
        ["Désignation", "Quantité", "Unité"],
    )
    gui_dir = Path(__file__).parents[1] / "src" / "epidata" / "resources" / "gui"
    loader = QUiLoader()
    selector = loader.load(str(gui_dir / "ConvertisseurPDF_selecteur.ui"))
    creation = loader.load(str(gui_dir / "ConvertisseurPDF_creation.ui"))
    navigation = n_extracteur_factures.FactureNavigation(
        selector,
        lambda *_: None,
        {"convertisseur_pdf_creation": creation},
    )

    convert_button = selector.findChild(QPushButton, f"b_methode_{method['id']}")
    assert convert_button is not None
    actions = selector.findChildren(QToolButton)
    assert len(actions) == 2
    assert all(not action.icon().isNull() for action in actions)
    assert all(action.parentWidget() is not convert_button for action in actions)
    assert all("background: transparent" in action.styleSheet() for action in actions)
    assert Path(ressource_path("icons/i_Parametres.png")).is_file()
    assert Path(ressource_path("icons/i_Poubelle.png")).is_file()
    selector.show()
    app.processEvents()

    def center(button):
        return button.mapTo(selector, button.rect().center()).x()

    assert center(convert_button) == center(selector.b_Convertir_Facture_generique)
    assert center(selector.b_Convertir_Facture_generique) == center(
        selector.b_Convertir_Facture_JARDIMED
    )
    assert convert_button.width() == selector.b_Convertir_Facture_generique.width()
    assert convert_button.width() == selector.b_Convertir_Facture_JARDIMED.width()
    assert all(action.mapTo(selector, action.rect().center()).x() > center(convert_button) for action in actions)

    method_path = Path(tmp_path / "methods") / f"{method['id']}.json"
    method_json = json.loads(method_path.read_text(encoding="utf-8"))
    method_json["ignore_terms"] = ["IGNORER DEPUIS LE JSON"]
    method_path.write_text(json.dumps(method_json), encoding="utf-8")
    navigation._modifier_methode(method["id"])
    assert creation.plainTextEdit_ignorer.toPlainText() == "IGNORER DEPUIS LE JSON"

    example_pdf = Path(__file__).parents[1] / "tests" / "facture_teste2.pdf"
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_: (str(example_pdf), "PDF"),
    )
    creation.b_Choisir_PDF.click()
    assert creation.comboBox_tableau.count() > 0

    navigation._modifier_methode(method["id"])
    assert creation.cb_unite.currentData() == 2
    creation.cb_unite.setCurrentIndex(creation.cb_unite.findData(-1))
    monkeypatch.setattr(QMessageBox, "information", lambda *_: QMessageBox.StandardButton.Ok)
    navigation._enregistrer_methode()

    updated = methodes.charger_methode(method["id"])
    assert "Unité" not in updated["mappings"]
    assert updated["column_labels"] == ["Désignation", "Quantité", "Unité"]
    assert not hasattr(creation, "b_Analyser_PDF")
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_: QMessageBox.StandardButton.Yes,
    )
    navigation._supprimer_methode(method["id"])
    assert methodes.charger_methodes() == ([], [])
    app.processEvents()


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
        assert result["Date Facture"].unique().tolist() == ["28/07/2026"]
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
        assert result["Date Facture"].eq("").all()
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
    ui_dir = root / "src" / "epidata" / "resources" / "gui"
    for name in ("ConvertisseurPDF_selecteur.ui", "ConvertisseurPDF_creation.ui"):
        ET.parse(ui_dir / name)
    creation_ui = ET.parse(ui_dir / "ConvertisseurPDF_creation.ui")
    object_names = {
        item.attrib.get("name")
        for item in creation_ui.iter("widget")
    }
    assert "b_Choisir_PDF" in object_names
    assert "b_Analyser_PDF" not in object_names
