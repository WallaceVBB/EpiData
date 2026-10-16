"""Explicaction du fichier :
Ce fichier fait le lien entre l'interface graphique et le traitement des factures PDF.
Il est utilisé pour lancer le traitement des factures à partir de l'interface graphique.
"""

import os
import re
import unicodedata
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QThread, Signal, QSize, Qt
from PySide6.QtGui import QIcon, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidgetItem,
    QToolButton,
    QWidget,
)

from epidata.factures.methodes_personnalisees import (
    DEFAULT_IGNORE_TERMS,
    charger_methode,
    charger_methodes,
    creer_signature_table,
    detecter_ligne_entete,
    entetes_colonnes,
    enregistrer_methode,
    lire_tables_pdf,
    modifier_methode,
    supprimer_methode,
    suggerer_colonne_valeurs,
)
from epidata.utils import ressource_path


class FactureWorker(QThread):
    finished = Signal(bool, str, object, str)
    progress_updated = Signal(int, str)

    def __init__(self, pdf_path, output_path, extractor_name, parent=None):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.output_path = output_path
        self.extractor_name = extractor_name

    def run(self):
        try:
            self.progress_updated.emit(1, "Préparation du PDF...")

            module = self._load_extractor_module(self.extractor_name)
            if module is None:
                raise RuntimeError("Impossible de charger l'extracteur demandé.")

            def progress_callback(progress, message):
                self.progress_updated.emit(max(0, min(int(progress), 100)), message)

            result = module.extraire_facture_pdf(
                self.pdf_path,
                self.output_path,
                progress_callback=progress_callback,
                **(
                    {"method_id": self.extractor_name.split(":", 1)[1]}
                    if self.extractor_name.startswith("personnalise:")
                    else {}
                ),
            )

            if result is None:
                raise RuntimeError("L'extraction n'a retourné aucun résultat.")

            self.progress_updated.emit(100, "Conversion terminée")
            self.finished.emit(True, "Conversion terminée avec succès.", result, self.output_path)
        except Exception as exc:
            self.progress_updated.emit(100, f"Erreur: {exc}")
            self.finished.emit(False, str(exc), None, self.output_path)

    def _load_extractor_module(self, extractor_name):
        if extractor_name == "generique":
            from epidata.factures.extracteurs import extracteur_generique
            return extracteur_generique
        if extractor_name == "jardimed":
            from epidata.factures.extracteurs import extracteur_jardimed
            return extracteur_jardimed
        if extractor_name.startswith("personnalise:"):
            from epidata.factures import methodes_personnalisees
            return methodes_personnalisees
        return None

class FactureNavigation:
    def _charger_methodes_personnalisees(self):
        self._methodes_personnalisees, erreurs = charger_methodes()
        self._afficher_boutons_methodes()
        if erreurs:
            QMessageBox.warning(
                self.page,
                "Méthodes de facture",
                "Certaines méthodes enregistrées n'ont pas pu être chargées :\n\n"
                + "\n".join(erreurs),
            )

    def _afficher_boutons_methodes(self):
        layout = self.page.findChild(QGridLayout, "gridLayout")
        bouton_creation = getattr(self.page, "b_Ajouter_Methode_Facture", None)
        if layout is None or bouton_creation is None:
            return

        for ligne in self._lignes_methodes:
            layout.removeWidget(ligne)
            ligne.deleteLater()
        self._lignes_methodes.clear()

        for row, methode in enumerate(self._methodes_personnalisees, start=2):
            convertir = QPushButton(f"Convertir facture {methode['name']}", self.page)
            convertir.setObjectName(f"b_methode_{methode['id']}")
            convertir.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            convertir.clicked.connect(
                lambda checked=False, method_id=methode["id"]: self.on_convertir_facture(
                    f"personnalise:{method_id}"
                )
            )
            actions = QWidget(self.page)
            row_layout = QHBoxLayout(actions)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)
            modifier = QToolButton(actions)
            modifier.setIcon(QIcon(ressource_path("icons/i_Parametres.png")))
            modifier.setToolTip(f"Modifier la méthode {methode['name']}")
            modifier.setAccessibleName(f"Modifier la méthode {methode['name']}")
            modifier.setFixedSize(34, 34)
            modifier.setIconSize(QSize(22, 22))
            modifier.setAutoRaise(True)
            modifier.setStyleSheet(
                "QToolButton { background: transparent; border: none; padding: 0; }"
                "QToolButton:hover, QToolButton:pressed { background: transparent; }"
            )
            modifier.clicked.connect(
                lambda checked=False, method_id=methode["id"]:
                    self._modifier_methode(method_id)
            )
            supprimer = QToolButton(actions)
            supprimer.setIcon(QIcon(ressource_path("icons/i_Poubelle.png")))
            supprimer.setToolTip(f"Supprimer la méthode {methode['name']}")
            supprimer.setAccessibleName(f"Supprimer la méthode {methode['name']}")
            supprimer.setFixedSize(34, 34)
            supprimer.setIconSize(QSize(22, 22))
            supprimer.setAutoRaise(True)
            supprimer.setStyleSheet(
                "QToolButton { background: transparent; border: none; padding: 0; }"
                "QToolButton:hover, QToolButton:pressed { background: transparent; }"
            )
            supprimer.clicked.connect(
                lambda checked=False, method_id=methode["id"]:
                    self._supprimer_methode(method_id)
            )
            row_layout.addWidget(modifier)
            row_layout.addWidget(supprimer)
            actions.setSizePolicy(
                QSizePolicy.Policy.Maximum,
                QSizePolicy.Policy.Fixed,
            )
            actions.adjustSize()
            actions.setFixedWidth(actions.sizeHint().width())
            layout.addWidget(convertir, row, 1)
            layout.addWidget(actions, row, 2, alignment=Qt.AlignmentFlag.AlignLeft)
            self._lignes_methodes.extend((convertir, actions))

        layout.removeWidget(bouton_creation)
        layout.addWidget(bouton_creation, len(self._methodes_personnalisees) + 3, 1)

    def _ouvrir_creation_methode(self):
        page = self.pages.get("convertisseur_pdf_creation")
        if page is None:
            QMessageBox.critical(self.page, "Création de méthode", "La page de configuration est introuvable.")
            return

        self._methode_en_modification = None
        page.label_titre.setText("Créer un type de facture")
        page.lineEdit_fournisseur.clear()
        page.label_chemin_pdf.setText("Aucun fichier sélectionné")
        page.comboBox_tableau.clear()
        page.comboBox_ligne_entete.clear()
        page.tableWidget_apercu.clear()
        page.tableWidget_apercu.setRowCount(0)
        page.tableWidget_apercu.setColumnCount(0)
        page.plainTextEdit_ignorer.setPlainText("\n".join(DEFAULT_IGNORE_TERMS))
        for _, _, widget_name in self._champs_mapping():
            getattr(page, widget_name).clear()
        self._tables_exemple = []
        self._chemin_exemple = None
        self.show_page("convertisseur_pdf_creation")

    def _modifier_methode(self, method_id):
        try:
            method = charger_methode(method_id)
        except (FileNotFoundError, OSError, ValueError) as exc:
            QMessageBox.warning(
                self.page,
                "Modifier une méthode",
                f"Impossible de lire la méthode enregistrée : {exc}",
            )
            self._charger_methodes_personnalisees()
            return

        self._methodes_personnalisees = [
            method if item["id"] == method_id else item
            for item in self._methodes_personnalisees
        ]
        self._methode_en_modification = method
        page = self.pages["convertisseur_pdf_creation"]
        page.label_titre.setText(f"Modifier la méthode « {method['name']} »")
        page.lineEdit_fournisseur.setText(method["name"])
        page.label_chemin_pdf.setText(
            "Facultatif : choisissez un PDF pour modifier aussi les colonnes."
        )
        page.comboBox_tableau.clear()
        page.comboBox_ligne_entete.clear()
        page.tableWidget_apercu.clear()
        page.tableWidget_apercu.setRowCount(0)
        page.tableWidget_apercu.setColumnCount(0)
        page.plainTextEdit_ignorer.setPlainText("\n".join(method.get("ignore_terms", [])))
        self._tables_exemple = []
        self._chemin_exemple = None
        self._charger_mappings_existants(page, method)
        self.show_page("convertisseur_pdf_creation")

    def _charger_mappings_existants(self, page, method):
        labels = method.get("column_labels", [])
        mappings = method["mappings"]
        width = max(len(labels), max(mappings.values(), default=-1) + 1)
        for field, required, widget_name in self._champs_mapping():
            combo = getattr(page, widget_name)
            combo.clear()
            if not required:
                combo.addItem("Ne pas importer", -1)
            for column_index in range(width):
                label = (
                    labels[column_index]
                    if column_index < len(labels) and labels[column_index]
                    else f"Colonne {column_index + 1}"
                )
                combo.addItem(f"Colonne {column_index + 1} — {label[:45]}", column_index)
            selected_index = mappings.get(field, -1)
            combo.setCurrentIndex(combo.findData(selected_index))

    def _supprimer_methode(self, method_id):
        method = next(
            (item for item in self._methodes_personnalisees if item["id"] == method_id),
            None,
        )
        if method is None:
            QMessageBox.warning(self.page, "Supprimer une méthode", "Cette méthode est introuvable.")
            self._charger_methodes_personnalisees()
            return

        confirmation = QMessageBox.question(
            self.page,
            "Supprimer une méthode",
            f"Supprimer définitivement la méthode « {method['name']} » ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        try:
            supprimer_methode(method_id)
            self._charger_methodes_personnalisees()
        except OSError as exc:
            QMessageBox.critical(
                self.page,
                "Suppression impossible",
                f"La méthode n'a pas pu être supprimée : {exc}",
            )

    def _annuler_creation_methode(self):
        self._methode_en_modification = None
        self._tables_exemple = []
        self._chemin_exemple = None
        self.show_page("convertir_pdf")

    @staticmethod
    def _champs_mapping():
        return (
            ("Désignation", True, "cb_designation"),
            ("Quantité", False, "cb_quantite"),
            ("Unité", False, "cb_unite"),
            ("Nb. colis", False, "cb_colis"),
            ("Qté Livrée", False, "cb_livree"),
            ("Prix unitaire HT", False, "cb_prix"),
            ("Montant net HT", False, "cb_montant"),
            ("Taux TVA", False, "cb_tva"),
        )

    def _choisir_pdf_exemple(self):
        path, _ = QFileDialog.getOpenFileName(
            self.pages["convertisseur_pdf_creation"],
            "Choisir une facture exemple",
            "",
            "Fichiers PDF (*.pdf)",
        )
        if path:
            self._chemin_exemple = path
            self.pages["convertisseur_pdf_creation"].label_chemin_pdf.setText(path)
            self._tables_exemple = []
            self._analyser_pdf_exemple()

    def _analyser_pdf_exemple(self):
        from pdfminer.pdfexceptions import PDFException

        page = self.pages["convertisseur_pdf_creation"]
        if not self._chemin_exemple:
            QMessageBox.information(page, "Facture exemple", "Choisissez d'abord un fichier PDF.")
            return

        try:
            self._tables_exemple = lire_tables_pdf(self._chemin_exemple)
            if not self._tables_exemple:
                raise ValueError(
                    "Aucun tableau n'a été détecté dans les trois premières pages. "
                    "Vérifiez que le PDF contient du texte sélectionnable."
                )
            page.comboBox_tableau.blockSignals(True)
            page.comboBox_tableau.clear()
            for index, table in enumerate(self._tables_exemple, start=1):
                width = max((len(row) for row in table), default=0)
                page.comboBox_tableau.addItem(
                    f"Tableau {index} ({len(table)} lignes, {width} colonnes)",
                    index - 1,
                )
            largest_table = max(
                range(len(self._tables_exemple)),
                key=lambda index: len(self._tables_exemple[index]),
            )
            page.comboBox_tableau.setCurrentIndex(largest_table)
            page.comboBox_tableau.blockSignals(False)
            self._mettre_a_jour_apercu()
        except (OSError, ValueError, PDFException) as exc:
            self._tables_exemple = []
            page.comboBox_tableau.clear()
            page.comboBox_ligne_entete.clear()
            page.tableWidget_apercu.clear()
            page.tableWidget_apercu.setRowCount(0)
            page.tableWidget_apercu.setColumnCount(0)
            QMessageBox.warning(page, "Analyse du PDF", str(exc))

    def _mettre_a_jour_apercu(self, *_):
        page = self.pages.get("convertisseur_pdf_creation")
        if page is None or not self._tables_exemple:
            return
        table_index = page.comboBox_tableau.currentData()
        if table_index is None or table_index >= len(self._tables_exemple):
            return

        rows = self._tables_exemple[table_index]
        width = max((len(row) for row in rows), default=0)
        page.comboBox_ligne_entete.blockSignals(True)
        page.comboBox_ligne_entete.clear()
        for row_index, row in enumerate(rows[:30]):
            visible_text = " | ".join(cell for cell in row if cell)
            if visible_text:
                page.comboBox_ligne_entete.addItem(
                    f"Ligne {row_index + 1} : {visible_text[:100]}",
                    row_index,
                )
        detected_header = detecter_ligne_entete(rows)
        header_combo_index = page.comboBox_ligne_entete.findData(detected_header)
        if header_combo_index >= 0:
            page.comboBox_ligne_entete.setCurrentIndex(header_combo_index)
        page.comboBox_ligne_entete.blockSignals(False)

        preview = page.tableWidget_apercu
        preview.clear()
        preview.setColumnCount(width)
        preview.setRowCount(min(len(rows), 30))
        preview.setHorizontalHeaderLabels([f"Colonne {i + 1}" for i in range(width)])
        for row_index, row in enumerate(rows[:30]):
            for column_index in range(width):
                value = row[column_index] if column_index < len(row) else ""
                preview.setItem(row_index, column_index, QTableWidgetItem(value))
        preview.resizeColumnsToContents()
        self._remplir_choix_colonnes(rows, width, detected_header)

    def _mettre_a_jour_choix_colonnes(self, *_):
        page = self.pages.get("convertisseur_pdf_creation")
        if page is None:
            return
        table_index = page.comboBox_tableau.currentData()
        header_row = page.comboBox_ligne_entete.currentData()
        if table_index is None or header_row is None or table_index >= len(self._tables_exemple):
            return
        rows = self._tables_exemple[table_index]
        width = max((len(row) for row in rows), default=0)
        self._remplir_choix_colonnes(rows, width, header_row)

    def _remplir_choix_colonnes(self, rows, width, header_row):
        page = self.pages["convertisseur_pdf_creation"]
        headers = entetes_colonnes(rows, header_row)
        sample_row = next(
            (
                row
                for row in rows[header_row + 1 :]
                if sum(
                    bool(re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?", cell.strip()))
                    for cell in row
                    if cell
                ) >= 2
            ),
            [],
        )
        for _, required, widget_name in self._champs_mapping():
            combo = getattr(page, widget_name)
            combo.clear()
            if not required:
                combo.addItem("Ne pas importer", -1)
            for column_index in range(width):
                header = headers[column_index] if column_index < len(headers) else ""
                sample = (
                    sample_row[column_index].strip()
                    if column_index < len(sample_row)
                    else ""
                )
                label = f"Colonne {column_index + 1}"
                if header:
                    label += f" — {header[:45]}"
                if sample:
                    label += f" (ex. {sample[:30]})"
                combo.addItem(label, column_index)

        aliases = {
            "designation": (
                ("designation", 110),
                ("signation", 95),
                ("libelle", 90),
                ("produit", 80),
                ("article", 50),
                ("description", 80),
            ),
            "quantite": (("quantite", 100), ("qte", 90), ("qty", 90), ("quantity", 90)),
            "unite": (("unite", 100), ("unit", 90), ("livraison", 55)),
            "colis": (("colis", 100),),
            "livree": (("quantite livree", 110), ("qte livree", 110), ("livree", 80)),
            "prix": (("prix unitaire", 110), ("prix", 90), ("pu", 75), ("unitaire", 80)),
            "montant": (
                ("montant net ht", 120),
                ("montant ht", 110),
                ("net ht", 100),
                ("montant", 90),
                ("total ht", 80),
            ),
            "tva": (("tva", 100), ("vat", 90)),
        }
        for field, _, widget_name in self._champs_mapping():
            combo = getattr(page, widget_name)
            field_key = widget_name.removeprefix("cb_")
            candidates = []
            for column_index, header in enumerate(headers[:width]):
                normalized = unicodedata.normalize("NFKD", header.casefold())
                normalized = normalized.encode("ascii", "ignore").decode("ascii")
                normalized = re.sub(r"[^a-z0-9]+", " ", normalized).strip()
                score = max(
                    (
                        weight
                        for alias, weight in aliases[field_key]
                        if (
                            alias in normalized
                            if alias == "signation"
                            else f" {alias} " in f" {normalized} "
                        )
                    ),
                    default=0,
                )
                if score:
                    candidates.append((score, column_index))
            if candidates:
                _, column_index = max(candidates)
                is_numeric = field in {
                    "Quantité",
                    "Nb. colis",
                    "Qté Livrée",
                    "Prix unitaire HT",
                    "Montant net HT",
                    "Taux TVA",
                }
                suggested_index = suggerer_colonne_valeurs(
                    rows,
                    header_row,
                    column_index,
                    is_numeric,
                )
                combo.setCurrentIndex(combo.findData(suggested_index))

    def _enregistrer_methode(self):
        page = self.pages["convertisseur_pdf_creation"]
        name = page.lineEdit_fournisseur.text().strip()
        if not name:
            QMessageBox.information(page, "Nom du fournisseur", "Saisissez le nom du fournisseur.")
            page.lineEdit_fournisseur.setFocus()
            return
        if not self._tables_exemple and self._methode_en_modification is None:
            QMessageBox.information(
                page,
                "Facture exemple",
                "Choisissez une facture exemple. Son analyse démarre automatiquement.",
            )
            return

        try:
            ignore_terms = page.plainTextEdit_ignorer.toPlainText().splitlines()
            if self._methode_en_modification is not None:
                old_method = self._methode_en_modification
                if self._tables_exemple:
                    mappings = self._lire_mappings_selectionnes(page)
                    table_index = page.comboBox_tableau.currentData()
                    header_row = page.comboBox_ligne_entete.currentData()
                    table = self._tables_exemple[table_index]
                    signature = creer_signature_table(
                        table,
                        mappings,
                        header_row,
                    )
                    column_labels = entetes_colonnes(table, header_row)
                else:
                    mappings = self._lire_mappings_selectionnes(page)
                    signature = old_method.get("table_signature", [])
                    column_labels = old_method.get("column_labels", [])
                modifier_methode(
                    old_method["id"],
                    name,
                    mappings,
                    ignore_terms,
                    signature,
                    column_labels,
                )
            else:
                mappings = self._lire_mappings_selectionnes(page)
                table_index = page.comboBox_tableau.currentData()
                table = self._tables_exemple[table_index]
                header_row = page.comboBox_ligne_entete.currentData()
                enregistrer_methode(
                    name,
                    mappings,
                    ignore_terms,
                    creer_signature_table(
                        table,
                        mappings,
                        header_row,
                    ),
                    entetes_colonnes(table, header_row),
                )
            self._charger_methodes_personnalisees()
            self._methode_en_modification = None
            QMessageBox.information(
                page,
                "Méthode enregistrée",
                f"Le type de facture « {name} » a été enregistré.",
            )
            self.show_page("convertir_pdf")
        except (ValueError, FileExistsError, OSError) as exc:
            QMessageBox.warning(page, "Impossible d'enregistrer", str(exc))

    def _lire_mappings_selectionnes(self, page):
        mappings = {}
        for field, _, widget_name in self._champs_mapping():
            index = getattr(page, widget_name).currentData()
            if index is not None and index >= 0:
                mappings[field] = index
        return mappings

    def __init__(
        self,
        page_widget,
        show_page_callback,
        pages,
        data_service=None,
        history_navigation=None,
        show_history_page_callback=None,
    ):
        self.page = page_widget
        self.pages = pages
        self.show_page = show_page_callback
        self.data_service = data_service
        self.history_navigation = history_navigation
        self.show_history_page = show_history_page_callback
        self.worker = None
        self._current_output_path = None
        self._current_results_df = None
        self._current_source_path = None
        self._historique_mode = False
        self._etat_avant_historique = None
        self._methodes_personnalisees = []
        self._lignes_methodes = []
        self._tables_exemple = []
        self._chemin_exemple = None
        self._methode_en_modification = None
        self._connect_buttons()
        self._charger_methodes_personnalisees()
        self._configurer_redimensionnement()

    def _connect_buttons(self):
        if hasattr(self.page, 'b_Convertir_Facture_generique'):
            self.page.b_Convertir_Facture_generique.clicked.connect(
                lambda: self.on_convertir_facture('generique')
            )
        if hasattr(self.page, 'b_Convertir_Facture_JARDIMED'):
            self.page.b_Convertir_Facture_JARDIMED.clicked.connect(
                lambda: self.on_convertir_facture('jardimed')
            )
        if hasattr(self.page, "b_Ajouter_Methode_Facture"):
            self.page.b_Ajouter_Methode_Facture.clicked.connect(self._ouvrir_creation_methode)

        creation_page = self.pages.get("convertisseur_pdf_creation")
        if creation_page:
            creation_page.b_Choisir_PDF.clicked.connect(self._choisir_pdf_exemple)
            creation_page.comboBox_tableau.currentIndexChanged.connect(
                self._mettre_a_jour_apercu
            )
            creation_page.comboBox_ligne_entete.currentIndexChanged.connect(
                self._mettre_a_jour_choix_colonnes
            )
            creation_page.b_Enregistrer_Methode.clicked.connect(self._enregistrer_methode)
            creation_page.b_Annuler_Creation.clicked.connect(
                self._annuler_creation_methode
            )

        loading_page = self.pages.get('convertisseur_pdf_chargement')
        if loading_page and hasattr(loading_page, 'b_Annuler'):
            loading_page.b_Annuler.clicked.connect(self.on_cancel_loading)

        results_page = self.pages.get('convertisseur_pdf_resultats')
        if results_page:
            if hasattr(results_page, 'b_Telecharger_Facture_Excel'):
                results_page.b_Telecharger_Facture_Excel.clicked.connect(self.on_telecharger_excel)
            if hasattr(results_page, 'b_Convertir_Autre_Facture'):
                results_page.b_Convertir_Autre_Facture.clicked.connect(self.on_autre_fichier)

    def on_convertir_facture(self, extractor_name):
        pdf_path, _ = QFileDialog.getOpenFileName(
            self.page,
            "Sélectionner un fichier PDF",
            "",
            "Fichiers PDF (*.pdf);;Tous les fichiers (*)"
        )
        if not pdf_path:
            return

        self._current_results_df = None
        self._current_source_path = pdf_path
        self._historique_mode = False
        self._etat_avant_historique = None
        self._current_output_path = str(Path.home() / "facture_extraite.xlsx")
        self._show_loading_page()

        self.worker = FactureWorker(pdf_path, self._current_output_path, extractor_name, parent=self.page)
        self.worker.finished.connect(self.on_finished)
        self.worker.progress_updated.connect(self.on_progress_update)
        self.worker.start()

    def on_finished(self, success, message, result_df, output_path):
        self._update_loading_progress(100)
        self._update_loading_label("Conversion terminée")

        if not success:
            QMessageBox.critical(self.page, "Erreur de conversion", message)
            self.show_page('convertir_pdf')
            return

        self._current_results_df = result_df
        self._current_output_path = output_path
        if self.history_navigation is not None:
            try:
                self._current_output_path = self.history_navigation.enregistrer_conversion(
                    output_path,
                    self._current_source_path,
                )
            except Exception as exc:
                QMessageBox.warning(self.page, "Historique", f"La conversion n'a pas pu être archivée : {exc}")
        self._populate_results_table(result_df)
        self._show_results_page()
        QMessageBox.information(self.page, "Conversion terminée", message)

    def charger_historique(self, result_df, output_path):
        if not self._historique_mode:
            self._etat_avant_historique = {
                "resultats": self._current_results_df,
                "fichier_sortie": self._current_output_path,
                "fichier_source": self._current_source_path,
            }
        self._current_results_df = result_df
        self._current_output_path = output_path
        self._current_source_path = None
        self._historique_mode = True
        self._populate_results_table(result_df)
        self._show_results_page()

    def restaurer_etat_normal(self):
        if not self._historique_mode:
            return

        etat = self._etat_avant_historique or {}
        self._current_results_df = etat.get("resultats")
        self._current_output_path = etat.get("fichier_sortie")
        self._current_source_path = etat.get("fichier_source")
        self._historique_mode = False
        self._etat_avant_historique = None
        self._populate_results_table(
            self._current_results_df
            if self._current_results_df is not None
            else pd.DataFrame()
        )

        results_page = self.pages.get('convertisseur_pdf_resultats')
        bouton_autre = getattr(results_page, 'b_Convertir_Autre_Facture', None) if results_page else None
        if bouton_autre is not None:
            bouton_autre.setText("Convertir autre fichier")

    def _populate_results_table(self, result_df):
        results_page = self.pages.get('convertisseur_pdf_resultats')
        if not results_page or not hasattr(results_page, 'Tableau_Resultats'):
            return

        if not isinstance(result_df, pd.DataFrame):
            raise TypeError("Le résultat de la conversion doit être un DataFrame pandas.")

        model = QStandardItemModel(results_page.Tableau_Resultats)
        model.setColumnCount(len(result_df.columns))
        model.setHorizontalHeaderLabels([str(column) for column in result_df.columns])

        for row_index, (_, row) in enumerate(result_df.iterrows()):
            items = []
            for value in row:
                value_text = '' if pd.isna(value) else str(value)
                item = QStandardItem(value_text)
                item.setEditable(True)
                items.append(item)
            model.appendRow(items)

        model.itemChanged.connect(self._on_result_item_changed)
        results_page.Tableau_Resultats.setModel(model)
        results_page.Tableau_Resultats.setAlternatingRowColors(True)
        results_page.Tableau_Resultats.setSortingEnabled(False)
        results_page.Tableau_Resultats.resizeColumnsToContents()

    def _on_result_item_changed(self, item):
        if self._current_results_df is None:
            return

        self._current_results_df.iat[item.row(), item.column()] = item.text()
        try:
            self._sauvegarder_resultats_excel()
        except Exception as exc:
            QMessageBox.warning(self.page, "Historique", f"La modification n'a pas pu être enregistrée : {exc}")

    def _sauvegarder_resultats_excel(self):
        if not self._current_output_path or self._current_results_df is None:
            return

        chemin = Path(self._current_output_path)
        temporaire = chemin.with_name(f"{chemin.stem}.tmp{chemin.suffix}")
        try:
            self._current_results_df.to_excel(temporaire, sheet_name="Produits", index=False)
            temporaire.replace(chemin)
        except Exception:
            temporaire.unlink(missing_ok=True)
            raise

    def on_progress_update(self, value, message):
        if value is not None:
            self._update_loading_progress(int(value))
        self._update_loading_label(message)

    def on_cancel_loading(self):
        if self.worker and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait(1000)
        self.show_page('convertir_pdf')

    def _show_loading_page(self):
        loading_page = self.pages.get('convertisseur_pdf_chargement')
        if not loading_page:
            return
        self.show_page('convertisseur_pdf_chargement')
        if hasattr(loading_page, 'progressBar'):
            loading_page.progressBar.setValue(0)
        self._update_loading_label("Préparation de la conversion...")

    def _update_loading_progress(self, value):
        loading_page = self.pages.get('convertisseur_pdf_chargement')
        if loading_page and hasattr(loading_page, 'progressBar'):
            loading_page.progressBar.setValue(int(value))

    def _update_loading_label(self, message=None):
        loading_page = self.pages.get('convertisseur_pdf_chargement')
        if not loading_page or not hasattr(loading_page, 'label_3'):
            return
        loading_page.label_3.setText(message or "Conversion en cours...")

    def _show_results_page(self):
        results_page = self.pages.get('convertisseur_pdf_resultats')
        if not results_page:
            return
        bouton_autre = getattr(results_page, 'b_Convertir_Autre_Facture', None)
        if bouton_autre is not None:
            bouton_autre.setText(
                "Revenir à l'historique" if self._historique_mode else "Convertir autre fichier"
            )
        afficher_page = (
            self.show_history_page
            if self._historique_mode and self.show_history_page is not None
            else self.show_page
        )
        afficher_page('convertisseur_pdf_resultats')

    def _configurer_redimensionnement(self):
        # Colonnes redimensionnables à la souris (Interactive) + dernière colonne qui
        # absorbe l'espace restant quand la fenêtre est redimensionnée (stretchLastSection).
        # Combo suffisant : pas besoin d'un redimensionnement proportionnel personnalisé.
        results_page = self.pages.get('traitement_resultats')
        if not results_page:
            return

        results_page.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        if hasattr(results_page, 'Tableau_Results'):
            table_view = results_page.Tableau_Results
            table_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            table_view.horizontalHeader().setStretchLastSection(True)

    def on_telecharger_excel(self):
        if not self._current_output_path or not os.path.exists(self._current_output_path):
            QMessageBox.information(self.page, "Télécharger", "Aucun fichier Excel disponible à exporter.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self.page,
            "Enregistrer la facture convertie",
            str(Path.home() / "facture_extraite.xlsx"),
            "Fichiers Excel (*.xlsx)"
        )
        if not path:
            return

        try:
            import shutil
            shutil.copyfile(self._current_output_path, path)
            QMessageBox.information(self.page, "Export Excel", "Fichier Excel enregistré avec succès.")
        except Exception as exc:
            QMessageBox.critical(self.page, "Erreur", f"Impossible d'enregistrer le fichier Excel : {exc}")

    def on_autre_fichier(self):
        if self._historique_mode:
            if self.history_navigation is not None:
                self.history_navigation.ouvrir_selecteur()
            else:
                self.show_page('historique')
            return

        self._current_results_df = None
        self._current_output_path = None
        self._current_source_path = None
        self._historique_mode = False
        if self.worker and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait(1000)
        self.show_page('convertir_pdf')