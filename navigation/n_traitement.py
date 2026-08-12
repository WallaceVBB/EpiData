# Ce fichier fait le lien entre la GUI et le traitement des produits.
# Il contient les fonctions appelées par les boutons de la GUI pour lancer le traitement.

import os
import sqlite3
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QTimer, QThread, Signal, Qt
from PySide6.QtGui import QStandardItemModel, QStandardItem
from PySide6.QtWidgets import QFileDialog, QMessageBox, QHeaderView

import data_processing as dp
from data_processing import ClassificateurProduits
from services import DataService
from utils import BD_PT, console


class QtController:
    """Contrôleur minimal pour remplacer tkinter after() dans data_processing."""

    def __init__(self, data_service=None):
        self.data_service = data_service

    def after(self, delay, callback):
        QTimer.singleShot(delay, callback)


class TraitementWorker(QThread):
    finished = Signal(bool, str, object)
    progress_updated = Signal(int, str)

    def __init__(self, file_path, bd_pt, data_service=None, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.bd_pt = bd_pt
        self.data_service = data_service

    def run(self):
        original_showinfo = dp.messagebox.showinfo
        original_showerror = dp.messagebox.showerror
        result = {'success': True, 'message': 'Traitement terminé avec succès.'}
        imported_rows = None

        def showinfo(title, message, **kwargs):
            result['success'] = True
            result['message'] = message

        def showerror(title, message, **kwargs):
            result['success'] = False
            result['message'] = message

        def progress_callback(progress, message):
            self.progress_updated.emit(int(progress), message)

        dp.messagebox.showinfo = showinfo
        dp.messagebox.showerror = showerror

        try:
            # Initialisation des services globaux
            self.data_service = DataService(app=self)
            classifier = ClassificateurProduits(
                controller=QtController(data_service=self.data_service),
                bd_pt=self.bd_pt
            )
            self.progress_updated.emit(5, "Création des modèles...")
            imported_df = classifier.classifier_produits(self.file_path, progress_callback=progress_callback)
            if imported_df is None:
                raise RuntimeError("Le traitement du fichier a échoué")
            imported_rows = imported_df
        except Exception as exc:
            console.print(f"[red]Erreur lors du traitement du fichier : {exc}")
            result['success'] = False
            result['message'] = str(exc)
            self.progress_updated.emit(100, f"Erreur: {str(exc)}")
        finally:
            dp.messagebox.showinfo = original_showinfo
            dp.messagebox.showerror = original_showerror

        self.finished.emit(result['success'], result['message'], imported_rows)


class TraitementNavigation:
    """Navigation et actions de la page de traitement de fichier."""

    def __init__(self, page_widget, show_page_callback, pages, data_service=None):
        self.page = page_widget
        self.pages = pages
        self.show_page = show_page_callback
        self.data_service = data_service
        self.worker = None
        self._progress_timer = None
        self.current_results_df = None
        self._current_stage = 'creation_modeles'
        self._last_progress_value = 0
        self._last_progress_message = ''
        self._connect_buttons()
        self._connect_progress_buttons()
        self._connect_results_buttons()

    def _connect_buttons(self):
        if hasattr(self.page, 'Traitement_complet'):
            self.page.Traitement_complet.clicked.connect(self.on_traitement_complet)
        if hasattr(self.page, 'Traitement_simplifie'):
            self.page.Traitement_simplifie.clicked.connect(self.on_traitement_simplifie)

    def _connect_progress_buttons(self):
        loading_page = self.pages.get('traitement_chargement')
        if loading_page and hasattr(loading_page, 'b_Annuler'):
            loading_page.b_Annuler.clicked.connect(self.on_cancel_loading)

    def _connect_results_buttons(self):
        results_page = self.pages.get('traitement_resultats')
        if results_page:
            if hasattr(results_page, 'b_Supprimer_Resultats'):
                results_page.b_Supprimer_Resultats.clicked.connect(self.on_supprimer_resultats)
            if hasattr(results_page, 'b_Telecharger_Excel'):
                results_page.b_Telecharger_Excel.clicked.connect(self.on_telecharger_excel)
            if hasattr(results_page, 'b_Telecharger_CSV'):
                results_page.b_Telecharger_CSV.clicked.connect(self.on_telecharger_csv)
            if hasattr(results_page, 'b_Autre_Fichier'):
                results_page.b_Autre_Fichier.clicked.connect(self.on_autre_fichier)

    def on_traitement_complet(self):
        # TODO : accepter CSV ou Excel, et détecter automatiquement le séparateur pour CSV
        file_path, _ = QFileDialog.getOpenFileName(
            self.page,
            "Sélectionner un fichier CSV",
            "",
            "Fichiers CSV (*.csv);;Tous les fichiers (*)"
        )
        if not file_path:
            return

        self.current_results_df = None
        self._current_stage = 'creation_modeles'
        self._last_progress_value = 0
        self._last_progress_message = ''
        self._show_loading_page()

        # TODO : lancer data_service seulement lors du premier traitement, et le réutiliser pour les traitements suivants
        self.worker = TraitementWorker(file_path, BD_PT, data_service=self.data_service)
        self.worker.finished.connect(self.on_finished)
        self.worker.progress_updated.connect(self.on_progress_update)
        self.worker.start()

    def on_traitement_simplifie(self):
        QMessageBox.information(
            self.page,
            "Traitement simplifié",
            "Le traitement simplifié n'est pas encore pris en charge."
        )

    def on_cancel_loading(self):
        # TODO : Implémenter l'annulation du traitement (arreter le thread et nettoyer les ressources)
        QMessageBox.information(
            self.page,
            "Annuler",
            "Le traitement continue en arrière-plan. Vous pouvez revenir à la page de sélection."
        )
        self.show_page('traitement_produits')

    def on_finished(self, success, message, imported_rows):
        if self._progress_timer and self._progress_timer.isActive():
            self._progress_timer.stop()

        self._update_loading_progress(100)
        self._update_loading_label(100)

        if not success:
            QMessageBox.critical(self.page, "Erreur de traitement", message)
            self.show_page('traitement_produits')
            return

        self.current_results_df = imported_rows if imported_rows is not None else pd.DataFrame()
        self._show_results_page()

        QMessageBox.information(self.page, "Traitement terminé", message)

    def _show_loading_page(self):
        loading_page = self.pages.get('traitement_chargement')
        if not loading_page:
            return

        self.show_page('traitement_chargement')
        if hasattr(loading_page, 'progressBar_Traitement'):
            loading_page.progressBar_Traitement.setValue(0)
        self._update_loading_label(0)

        self._progress_timer = QTimer(self.page)
        self._progress_timer.setInterval(100)
        self._progress_timer.timeout.connect(self._animate_progress)
        self._progress_timer.start()

    def on_progress_update(self, value, message):
        self._last_progress_value = max(0, min(100, int(value)))
        self._last_progress_message = message or ''
        self._current_stage = 'creation_modeles' if 'modèle' in self._last_progress_message.lower() else 'traitement_produits'
        self._update_loading_progress(self._last_progress_value)
        self._update_loading_label(self._last_progress_value)

    def _animate_progress(self):
        loading_page = self.pages.get('traitement_chargement')
        if not loading_page or not hasattr(loading_page, 'progressBar_Traitement'):
            return

        value = loading_page.progressBar_Traitement.value()
        if self._current_stage == 'creation_modeles':
            value = min(20, value + 2)
        elif self._last_progress_value > 0:
            value = max(value, self._last_progress_value)
        elif value < 90:
            value = min(90, value + 1)

        loading_page.progressBar_Traitement.setValue(value)
        self._update_loading_label(value)

    def _update_loading_progress(self, value):
        loading_page = self.pages.get('traitement_chargement')
        if loading_page and hasattr(loading_page, 'progressBar_Traitement'):
            loading_page.progressBar_Traitement.setValue(value)

    def _update_loading_label(self, value):
        loading_page = self.pages.get('traitement_chargement')
        if not loading_page or not hasattr(loading_page, 'label_3'):
            return

        if self._current_stage == 'creation_modeles':
            label_text = f"Création des modèles : {value}%"
        elif value >= 100:
            label_text = "Traitement terminé"
        else:
            label_text = f"Traitement de produits : {value}%" # TODO: remplacer par : XX / XX (produits traités / produits totaux)

        loading_page.label_3.setText(label_text)

    def _show_results_page(self):
        results_page = self.pages.get('traitement_resultats')
        if not results_page:
            return

        self.show_page('traitement_resultats')
        self._populate_results_table(self.current_results_df)

        if hasattr(results_page, 'b_Supprimer_Resultats'):
            results_page.b_Supprimer_Resultats.setEnabled(
                not self.current_results_df.empty if self.current_results_df is not None else False
            )

    def _populate_results_table(self, df):
        results_page = self.pages.get('traitement_resultats')
        if not results_page or not hasattr(results_page, 'Tableau_Results'):
            return

        table_view = results_page.Tableau_Results
        model = QStandardItemModel()

        if df is None or df.empty:
            model.setColumnCount(0)
            model.setRowCount(0)
            table_view.setModel(model)
            return

        columns = list(df.columns)
        model.setColumnCount(len(columns))
        model.setHorizontalHeaderLabels(columns)

        for row_index, row in df.iterrows():
            items = [QStandardItem(str(row[col]) if pd.notna(row[col]) else "") for col in columns]
            for item in items:
                item.setEditable(False)
            model.appendRow(items)

        table_view.setModel(model)
        table_view.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table_view.verticalHeader().setVisible(False)
        table_view.setAlternatingRowColors(True)

    def on_supprimer_resultats(self):
        if self.current_results_df is None or self.current_results_df.empty:
            QMessageBox.information(self.page, "Suppression", "Aucune donnée à supprimer.")
            return

        answer = QMessageBox.question(
            self.page,
            "Supprimer les résultats",
            "Supprimer ces produits de la base de données ?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        with sqlite3.connect(BD_PT) as conn:
            cursor = conn.cursor()
            for _, row in self.current_results_df.iterrows():
                code_produit = row.get('code_produit')
                texte_brut = row.get('texte_brut')
                if pd.notna(code_produit) and str(code_produit).strip() != "":
                    cursor.execute("DELETE FROM produits WHERE code_produit = ?", (code_produit,))
                elif pd.notna(texte_brut):
                    cursor.execute("DELETE FROM produits WHERE texte_brut = ?", (texte_brut,))
            conn.commit()

        QMessageBox.information(self.page, "Suppression", "Les données ont été supprimées de la base.")
        self.current_results_df = pd.DataFrame()
        self._populate_results_table(self.current_results_df)
        if hasattr(self.pages['traitement_resultats'], 'b_Supprimer_Resultats'):
            self.pages['traitement_resultats'].b_Supprimer_Resultats.setEnabled(False)

    def on_telecharger_excel(self):
        if self.current_results_df is None or self.current_results_df.empty:
            QMessageBox.information(self.page, "Télécharger", "Aucun résultat à exporter.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self.page,
            "Enregistrer le résultat en Excel",
            str(Path.home() / "resultats_traitement.xlsx"),
            "Fichiers Excel (*.xlsx)"
        )
        if not path:
            return

        try:
            self.current_results_df.to_excel(path, index=False)
            QMessageBox.information(self.page, "Export Excel", "Fichier Excel enregistré avec succès.")
        except Exception as exc:
            QMessageBox.critical(self.page, "Erreur", f"Impossible d'enregistrer le fichier Excel : {exc}")

    def on_telecharger_csv(self):
        if self.current_results_df is None or self.current_results_df.empty:
            QMessageBox.information(self.page, "Télécharger", "Aucun résultat à exporter.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self.page,
            "Enregistrer le résultat en CSV",
            str(Path.home() / "resultats_traitement.csv"),
            "Fichiers CSV (*.csv)"
        )
        if not path:
            return

        try:
            self.current_results_df.to_csv(path, index=False)
            QMessageBox.information(self.page, "Export CSV", "Fichier CSV enregistré avec succès.")
        except Exception as exc:
            QMessageBox.critical(self.page, "Erreur", f"Impossible d'enregistrer le fichier CSV : {exc}")

    def on_autre_fichier(self):
        self.current_results_df = None
        self.show_page('traitement_produits')
