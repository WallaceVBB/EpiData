"""Explicaction du fichier :
Ce fichier fait le lien entre l'interface graphique et le traitement des factures PDF.
Il est utilisé pour lancer le traitement des factures à partir de l'interface graphique.
"""

import os
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QFileDialog, QMessageBox


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
                progress_callback=progress_callback
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
            from extracteur_facture import extracteur_generique
            return extracteur_generique
        if extractor_name == "jardimed":
            from extracteur_facture import extracteur_jardimed
            return extracteur_jardimed
        return None

class FactureNavigation:
    def __init__(self, page_widget, show_page_callback, pages, data_service=None):
        self.page = page_widget
        self.pages = pages
        self.show_page = show_page_callback
        self.data_service = data_service
        self.worker = None
        self._current_output_path = None
        self._current_results_df = None
        self._connect_buttons()

    def _connect_buttons(self):
        if hasattr(self.page, 'b_Convertir_Facture_generique'):
            self.page.b_Convertir_Facture_generique.clicked.connect(
                lambda: self.on_convertir_facture('generique')
            )
        if hasattr(self.page, 'b_Convertir_Facture_JARDIMED'):
            self.page.b_Convertir_Facture_JARDIMED.clicked.connect(
                lambda: self.on_convertir_facture('jardimed')
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
        self._populate_results_table(result_df)
        self._show_results_page()
        QMessageBox.information(self.page, "Conversion terminée", message)

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
                items.append(QStandardItem(value_text))
            model.appendRow(items)

        results_page.Tableau_Resultats.setModel(model)
        results_page.Tableau_Resultats.setAlternatingRowColors(True)
        results_page.Tableau_Resultats.resizeColumnsToContents()

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
        self.show_page('convertisseur_pdf_resultats')

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
        self._current_results_df = None
        self._current_output_path = None
        if self.worker and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait(1000)
        self.show_page('convertir_pdf')