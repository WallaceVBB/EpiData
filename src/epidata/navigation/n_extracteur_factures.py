"""Explicaction du fichier :
Ce fichier fait le lien entre l'interface graphique et le traitement des factures PDF.
Il est utilisé pour lancer le traitement des factures à partir de l'interface graphique.
"""

import os
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QFileDialog, QMessageBox, QSizePolicy


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
            from epidata.factures.extracteurs import extracteur_generique
            return extracteur_generique
        if extractor_name == "jardimed":
            from epidata.factures.extracteurs import extracteur_jardimed
            return extracteur_jardimed
        return None

class FactureNavigation:
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
        self._connect_buttons()
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