# Ce fichier fait le lien entre l'interface graphique et le traitement des factures PDF.
# Il est utilisé pour lancer le traitement des factures à partir de l'interface graphique.

import os
from pathlib import Path

from PySide6.QtCore import QThread, Signal, QTimer
from PySide6.QtWidgets import QFileDialog, QMessageBox

from extracteur_facture import extracteur_generique, extracteur_jardimed

EXTRACTEURS = {
    "generique": extracteur_generique,
    "jardimed": extracteur_jardimed,
}


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
            self.progress_updated.emit(5, "Préparation du PDF...")
            total_pages = self._get_pdf_page_count(self.pdf_path)
            self.progress_updated.emit(10, f"Pages détectées : {total_pages}")

            module = self._load_extractor_module(self.extractor_name)
            if module is None:
                raise RuntimeError("Impossible de charger l'extracteur demandé.")

            self.progress_updated.emit(15, "Extraction en cours...")

            def progress_callback(progress, message):
                self.progress_updated.emit(int(progress), message)

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

    def _get_pdf_page_count(self, pdf_path):
        from pypdf import PdfReader

        reader = PdfReader(pdf_path)
        return len(reader.pages)

    def _load_extractor_module(self, extractor_name):
        return EXTRACTEURS.get(extractor_name)


class FactureNavigation:
    def __init__(self, page_widget, show_page_callback, pages, data_service=None):
        self.page = page_widget
        self.pages = pages
        self.show_page = show_page_callback
        self.data_service = data_service
        self.worker = None
        self._progress_timer = None
        self._total_pages = 1
        self._processed_pages = 0
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
        self._total_pages = self._get_pdf_page_count(pdf_path)
        self._processed_pages = 0
        self._show_loading_page()

        self.worker = FactureWorker(pdf_path, self._current_output_path, extractor_name, parent=self.page)
        self.worker.finished.connect(self.on_finished)
        self.worker.progress_updated.connect(self.on_progress_update)
        self.worker.start()

    def on_finished(self, success, message, result_df, output_path):
        if self._progress_timer and self._progress_timer.isActive():
            self._progress_timer.stop()

        self._processed_pages = self._total_pages
        self._update_loading_progress(100)
        self._update_loading_label(100, "Conversion terminée")

        if not success:
            QMessageBox.critical(self.page, "Erreur de conversion", message)
            self.show_page('convertir_pdf')
            return

        self._current_results_df = result_df
        self._current_output_path = output_path
        self._show_results_page()
        QMessageBox.information(self.page, "Conversion terminée", message)

    def on_progress_update(self, value, message):
        if value is not None:
            self._update_loading_progress(int(value))
        self._update_loading_label(value, message)

    def on_cancel_loading(self):
        if self.worker and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait(1000)
        if self._progress_timer and self._progress_timer.isActive():
            self._progress_timer.stop()
        self.show_page('convertir_pdf')

    def _show_loading_page(self):
        loading_page = self.pages.get('convertisseur_pdf_chargement')
        if not loading_page:
            return

        self.show_page('convertisseur_pdf_chargement')
        if hasattr(loading_page, 'progressBar'):
            loading_page.progressBar.setValue(0)
        self._update_loading_label(0, "Préparation de la conversion...")

        self._progress_timer = QTimer(self.page)
        self._progress_timer.setInterval(200)
        self._progress_timer.timeout.connect(self._animate_progress)
        self._progress_timer.start()

    def _animate_progress(self):
        loading_page = self.pages.get('convertisseur_pdf_chargement')
        if not loading_page or not hasattr(loading_page, 'progressBar'):
            return

        if self._total_pages > 1:
            self._processed_pages = min(self._total_pages, self._processed_pages + 1)
            percent = int((self._processed_pages / self._total_pages) * 100)
            percent = max(5, min(90, percent))
            loading_page.progressBar.setValue(percent)
            self._update_loading_label(percent, f"Pages converties : {self._processed_pages} / {self._total_pages}")
        else:
            current_value = loading_page.progressBar.value()
            next_value = min(90, current_value + 3)
            loading_page.progressBar.setValue(next_value)
            self._update_loading_label(next_value, "Conversion en cours...")

    def _update_loading_progress(self, value):
        loading_page = self.pages.get('convertisseur_pdf_chargement')
        if loading_page and hasattr(loading_page, 'progressBar'):
            loading_page.progressBar.setValue(int(value))

    def _update_loading_label(self, value, message=None):
        loading_page = self.pages.get('convertisseur_pdf_chargement')
        if not loading_page or not hasattr(loading_page, 'label_3'):
            return

        if message is None:
            message = f"Pages converties : {self._processed_pages} / {self._total_pages}"
        if value >= 100:
            label_text = "Conversion terminée"
        else:
            label_text = message
        loading_page.label_3.setText(label_text)

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
        if self._progress_timer and self._progress_timer.isActive():
            self._progress_timer.stop()
        self.show_page('convertir_pdf')

    def _get_pdf_page_count(self, pdf_path):
        from pypdf import PdfReader

        try:
            reader = PdfReader(pdf_path)
            return len(reader.pages) if reader.pages else 1
        except Exception:
            return 1


