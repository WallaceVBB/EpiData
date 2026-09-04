# Ce fichier fait le lien entre la GUI et le traitement des produits.
# Il contient les fonctions appelées par les boutons de la GUI pour lancer le traitement.

from pathlib import Path

import pandas as pd
from PySide6.QtCore import QThread, Signal, Qt, QSortFilterProxyModel
from PySide6.QtGui import QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (QFileDialog, QMessageBox, QSizePolicy, QStyledItemDelegate)

from services import DataService
from utils import BD_PT, console

# Rôle personnalisé utilisé pour retenir la dernière valeur "connue" d'une cellule,
# afin de pouvoir détecter une modification réelle.
ROLE_VALEUR_PRECEDENTE = Qt.ItemDataRole.UserRole + 2

# Nom des widgets de filtre définis dans le .ui de la page traitement_resultats
# (label_Filtrer, comboBox_Choic_colonnes, lineEdit_Filtre, b_Reset).
WIDGET_COMBO_COLONNES = 'comboBox_Choic_colonnes'
WIDGET_CHAMP_FILTRE = 'lineEdit_Filtre'
WIDGET_BOUTON_RESET = 'b_Reset'

# Nombre maximum de lignes affichées simultanément dans le tableau de résultats.
# Au-delà, le tableau est paginé (le DataFrame complet reste en mémoire).
TAILLE_PAGE_RESULTATS = 3000


class ComboBoxDelegate(QStyledItemDelegate):
    """Delegate pour afficher un combobox pour les cellules éditables."""

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.items = items

    def createEditor(self, parent, option, index):
        """Crée un combobox pour éditer la cellule."""
        from PySide6.QtWidgets import QComboBox
        combobox = QComboBox(parent)
        combobox.addItems(self.items)
        return combobox

    def setEditorData(self, editor, index):
        """Définit les données du combobox à partir du modèle."""
        value = index.model().data(index, Qt.ItemDataRole.DisplayRole)
        if value:
            index_value = editor.findText(str(value))
            if index_value >= 0:
                editor.setCurrentIndex(index_value)

    def setModelData(self, editor, model, index):
        """Définit les données du modèle à partir du combobox."""
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)


class TableModelEditablePersonnalise(QStandardItemModel):
    """Modèle de table personnalisé pour rendre les cellules éditables avec support pour checkbox et combobox."""

    item_changed = Signal(int, int, str)  # row, col, value

    def __init__(self, df, colonnes_visibles, categories_list, parent=None):
        super().__init__(parent)
        self.df = df
        self.colonnes_visibles = colonnes_visibles
        self.categories_list = categories_list
        self._populate_model()

    def _populate_model(self):
        """Remplit le modèle avec les données du DataFrame."""
        self.setColumnCount(len(self.colonnes_visibles))
        self.setHorizontalHeaderLabels(self.colonnes_visibles)

        for row_index, (_, row) in enumerate(self.df.iterrows()):
            for col_index, colonne in enumerate(self.colonnes_visibles):
                value = row.get(colonne, '')

                if colonne == 'est_corrige':
                    # Pour est_corrige, créer un item avec checkbox.
                    # (Bug corrigé : l'ancien code appelait deux fois setCheckable(),
                    # ce qui désactivait la case au lieu de fixer son état initial.)
                    valeur_bool = bool(value)
                    item = QStandardItem()
                    item.setCheckable(True)
                    item.setCheckState(Qt.CheckState.Checked if valeur_bool else Qt.CheckState.Unchecked)
                    item.setData(valeur_bool, ROLE_VALEUR_PRECEDENTE)
                elif colonne == 'base_variante':
                    # Pour base_variante, stocker la valeur et marquer comme combobox.
                    value_str = str(value) if pd.notna(value) else ''
                    item = QStandardItem(value_str)
                    item.setEditable(True)
                    item.setData("combobox", Qt.ItemDataRole.UserRole)
                    item.setData(value_str, ROLE_VALEUR_PRECEDENTE)
                else:
                    # Pour les autres colonnes, créer des items texte éditables.
                    value_str = str(value) if pd.notna(value) else ''
                    item = QStandardItem(value_str)
                    item.setEditable(colonne not in ('id', 'a_reviser'))
                    item.setData(value_str, ROLE_VALEUR_PRECEDENTE)

                self.setItem(row_index, col_index, item)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        """Personnalise l'affichage des données."""
        if not index.isValid():
            return None

        item = self.item(index.row(), index.column())
        if item is None:
            return None

        colonne = self.colonnes_visibles[index.column()] if index.column() < len(self.colonnes_visibles) else ''

        # Pour est_corrige, afficher comme checkbox.
        if colonne == 'est_corrige':
            if role == Qt.ItemDataRole.CheckStateRole:
                return Qt.CheckState.Checked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Unchecked
            elif role == Qt.ItemDataRole.DisplayRole:
                return None
            return super().data(index, role)

        return super().data(index, role)

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        """Gère la modification des données."""
        if not index.isValid():
            return False

        colonne = self.colonnes_visibles[index.column()] if index.column() < len(self.colonnes_visibles) else ''
        item = self.item(index.row(), index.column())

        a_change = False
        nouvelle_valeur = None

        if colonne == 'est_corrige' and role == Qt.ItemDataRole.CheckStateRole:
            nouvelle_valeur = (value == Qt.CheckState.Checked)
            valeur_precedente = item.data(ROLE_VALEUR_PRECEDENTE) if item else None
            a_change = bool(valeur_precedente) != nouvelle_valeur
        elif role == Qt.ItemDataRole.EditRole:
            nouvelle_valeur = str(value)
            valeur_precedente = item.data(ROLE_VALEUR_PRECEDENTE) if item else None
            a_change = str(valeur_precedente) != nouvelle_valeur

        success = super().setData(index, value, role)

        if success and a_change:
            item = self.item(index.row(), index.column())
            if item:
                item.setData(nouvelle_valeur, ROLE_VALEUR_PRECEDENTE)
            self.item_changed.emit(index.row(), index.column(), str(nouvelle_valeur))

        return success

    def flags(self, index):
        """Définit les drapeaux pour les éléments du tableau."""
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags

        colonne = self.colonnes_visibles[index.column()] if index.column() < len(self.colonnes_visibles) else ''

        flags = super().flags(index)

        if colonne == 'est_corrige':
            # est_corrige est une checkbox
            flags |= Qt.ItemFlag.ItemIsUserCheckable
            flags &= ~Qt.ItemFlag.ItemIsEditable  # Pas éditable, juste cochable
        elif colonne in ('id', 'a_reviser'):
            # Ces colonnes ne sont jamais éditables (défensif : elles sont de toute
            # façon toujours masquées, voir colonnes_cachees dans _populate_results_table).
            flags &= ~Qt.ItemFlag.ItemIsEditable
        else:
            flags |= Qt.ItemFlag.ItemIsEditable

        return flags


class FiltreProduitsProxyModel(QSortFilterProxyModel):
    """Proxy model permettant de filtrer le tableau de résultats, soit sur une colonne
    précise, soit sur toutes les colonnes à la fois (recherche globale)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filtres_colonnes = {}  # {col_index: texte_filtre_en_minuscule}
        self._filtre_global = ''

    def definir_filtre_colonne(self, col_index, texte):
        texte = (texte or '').strip().lower()
        if texte:
            self._filtres_colonnes[col_index] = texte
        else:
            self._filtres_colonnes.pop(col_index, None)
        self.invalidateFilter()

    def definir_filtre_global(self, texte):
        self._filtre_global = (texte or '').strip().lower()
        self.invalidateFilter()

    def reinitialiser_filtres(self):
        self._filtres_colonnes.clear()
        self._filtre_global = ''
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        model = self.sourceModel()
        if model is None:
            return True

        def valeur_colonne(col_index):
            index = model.index(source_row, col_index, source_parent)
            valeur = model.data(index, Qt.ItemDataRole.DisplayRole)
            if valeur is None:
                valeur = model.data(index, Qt.ItemDataRole.CheckStateRole)
            return str(valeur).lower() if valeur is not None else ''

        for col_index, texte in self._filtres_colonnes.items():
            if texte not in valeur_colonne(col_index):
                return False

        if self._filtre_global:
            if not any(self._filtre_global in valeur_colonne(c) for c in range(model.columnCount())):
                return False

        return True


class TraitementWorker(QThread):
    finished = Signal(bool, str, object)
    progress_updated = Signal(int, str)

    def __init__(self, file_path, bd_pt, data_service=None, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.bd_pt = bd_pt
        self.data_service = data_service

    def run(self):
        from data_processing import ClassificateurProduits
        
        result = {'success': True, 'message': 'Traitement terminé avec succès.'}
        imported_rows = None

        def progress_callback(progress, message):
            self.progress_updated.emit(int(progress), message)

        try:
            # Initialisation des services globaux
            self.data_service = DataService(app=self, bd_pt=self.bd_pt)
            classifier = ClassificateurProduits(data_service=self.data_service)
            self.progress_updated.emit(5, "Création des modèles...")
            imported_df = classifier.classifier_produits(self.file_path, progress_callback=progress_callback)
            if imported_df is None:
                raise RuntimeError("Le traitement du fichier a échoué")
            imported_rows = imported_df
        except Exception as e:
            console.print(f"[red]Erreur lors du traitement du fichier : {e}")
            result['success'] = False
            result['message'] = str(e)
            self.progress_updated.emit(100, f"Erreur: {str(e)}")

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
        # Dictionnaire pour stocker les produits avec leurs IDs
        self._produits_id_map = {}  # {index_row: {'id': int, 'original_data': dict}}
        # Charger les catégories disponibles
        self._categories_list = self._charger_categories()
        # Flag pour éviter les mises à jour récursives
        self._updating_cell = False
        # Modèle source courant (le tableau utilise un proxy de filtrage par-dessus)
        self._results_model = None
        self._filtre_proxy = None
        # Pagination du tableau de résultats
        self._page_courante = 0
        self._nb_pages = 0

        self._connect_buttons()
        self._connect_progress_buttons()
        self._connect_results_buttons()
        self._configurer_redimensionnement()

    def _connect_buttons(self):
        if hasattr(self.page, 'b_Traitement_Stardard'):
            self.page.b_Traitement_Stardard.clicked.connect(self.on_traitement_standard)
        if hasattr(self.page, 'b_Traitement_Choix'):
            self.page.b_Traitement_Choix.clicked.connect(self.on_traitement_choix)

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
            if hasattr(results_page, 'b_Page_Precedente'):
                results_page.b_Page_Precedente.clicked.connect(self.on_page_precedente)
            if hasattr(results_page, 'b_Page_Suivante'):
                results_page.b_Page_Suivante.clicked.connect(self.on_page_suivante)

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

    def _charger_categories(self):
        """Charge les catégories (bases variantes) depuis le service de données."""
        try:
            data_service = self._obtenir_data_service()
            if data_service and data_service.csv_fournisseurs is not None:
                # Charger depuis categories.csv
                import os
                from utils import ressource_path
                csv_categories = ressource_path(os.path.join("parametres", "categories.csv"))
                if os.path.exists(csv_categories):
                    df_categories = pd.read_csv(csv_categories)
                    if 'basevariante' in df_categories.columns:
                        return sorted(df_categories['basevariante'].dropna().unique().tolist())
        except Exception as e:
            console.print(f"[yellow]Avertissement: impossible de charger les catégories: {e}")
        return []

    def on_traitement_standard(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self.page,
            "Sélectionner un fichier CSV",
            str(Path.home()),
            "Fichiers CSV ou Excel (*.csv *.xls *.xlsx);;Fichiers CSV (*.csv);;Fichiers Excel (*.xls *.xlsx);;Tous les fichiers (*)"
        )
        if not file_path:
            return

        self.current_results_df = None
        self._current_stage = 'creation_modeles'
        self._last_progress_value = 0
        self._last_progress_message = ''
        self._show_loading_page()

        # Utilisation du data_service existant s'il existe déjà
        if self.data_service is None:
            self.data_service = self._obtenir_data_service()

        self.worker = TraitementWorker(file_path, BD_PT, data_service=self.data_service)
        self.worker.finished.connect(self.on_finished)
        self.worker.progress_updated.connect(self.on_progress_update)
        self.worker.start()

    def on_traitement_choix(self):
        QMessageBox.information(
            self.page,
            "Traitement choix",
            "Le traitement en choisissant les colonnes n'est pas encore pris en charge."
        )

    def on_cancel_loading(self):
        # NOTE : terminate() est un arrêt forcé et brutal du thread ; il peut laisser
        # des ressources dans un état incohérent. Idéalement, TraitementWorker devrait
        # exposer un indicateur d'annulation coopératif vérifié entre les étapes.
        # Conservé tel quel pour rester dans le périmètre de cette révision.
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait()

        if self._progress_timer and self._progress_timer.isActive():
            self._progress_timer.stop()

        self.worker = None
        self.show_page('traitement_produits')

    def on_finished(self, success, message, imported_rows):
        if self._progress_timer and self._progress_timer.isActive():
            self._progress_timer.stop()

        self._update_loading_progress(100)

        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None

        if not success:
            QMessageBox.critical(self.page, "Erreur de traitement", message)
            self.show_page('traitement_produits')
            return

        self.current_results_df = imported_rows if imported_rows is not None else pd.DataFrame()
        self._show_results_page()

        QMessageBox.information(self.page, "Traitement terminé", message)

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

        data_service = self._obtenir_data_service()
        produits = [
            {
                'code_produit': row.get('code_produit') if pd.notna(row.get('code_produit')) else None,
                'texte_brut': row.get('texte_brut') if pd.notna(row.get('texte_brut')) else None,
            }
            for _, row in self.current_results_df.iterrows()
        ]
        data_service.supprimer_produits(produits)

        QMessageBox.information(self.page, "Suppression", "Les données ont été supprimées de la base.")
        self.current_results_df = pd.DataFrame()
        self._populate_results_table(self.current_results_df)
        if hasattr(self.pages['traitement_resultats'], 'b_Supprimer_Resultats'):
            self.pages['traitement_resultats'].b_Supprimer_Resultats.setEnabled(False)

    def _show_loading_page(self):
        from PySide6.QtCore import QTimer
        loading_page = self.pages.get('traitement_chargement')
        if not loading_page:
            return

        self.show_page('traitement_chargement')
        if hasattr(loading_page, 'progressBar_Traitement'):
            loading_page.progressBar_Traitement.setValue(0)

        self._progress_timer = QTimer(self.page)
        self._progress_timer.setInterval(100)
        self._progress_timer.timeout.connect(self._animate_progress)
        self._progress_timer.start()

    def on_progress_update(self, value, message):
        self._last_progress_value = max(0, min(100, int(value)))
        self._last_progress_message = message or ''
        self._current_stage = 'creation_modeles' if 'modèle' in self._last_progress_message.lower() else 'traitement_produits'
        self._update_loading_progress(self._last_progress_value)

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

    def _update_loading_progress(self, value):
        loading_page = self.pages.get('traitement_chargement')
        if loading_page and hasattr(loading_page, 'progressBar_Traitement'):
            loading_page.progressBar_Traitement.setValue(value)

    def _show_results_page(self):
        results_page = self.pages.get('traitement_resultats')
        if not results_page:
            return

        self.show_page('traitement_resultats')
        self._page_courante = 0
        self._populate_results_table(self.current_results_df)

        if hasattr(results_page, 'b_Supprimer_Resultats'):
            results_page.b_Supprimer_Resultats.setEnabled(
                not self.current_results_df.empty if self.current_results_df is not None else False
            )

    def _populate_results_table(self, df):
        """
        Peuple le tableau des résultats (page courante uniquement) avec des colonnes
        éditables et configure les filtres du .ui.

        `df` est le DataFrame COMPLET (source de vérité) : seule la tranche
        correspondant à `self._page_courante` est chargée dans le modèle Qt, pour ne
        jamais construire des centaines de milliers de QStandardItem.
        """
        from math import ceil
        from PySide6.QtWidgets import QHeaderView

        results_page = self.pages.get('traitement_resultats')
        if not results_page or not hasattr(results_page, 'Tableau_Results'):
            return

        table_view = results_page.Tableau_Results

        # Colonnes à cacher (non affichables à l'utilisateur)
        colonnes_cachees = {'id', 'a_reviser', 'idx_code_produit', 'idx_texte_brut', 'texte_propre','fournisseur','siret',
                            'tva', 'methode_prediction','allergenes', 'aliment', 'variante'}

        if df is None or df.empty:
            model = QStandardItemModel()
            model.setColumnCount(0)
            model.setRowCount(0)
            table_view.setModel(model)
            self._results_model = None
            self._filtre_proxy = None
            self._configurer_filtres([])
            self._definir_etat_filtres(False)
            self._nb_pages = 0
            self._page_courante = 0
            self._maj_label_pagination()
            return

        # Découpage en pages : le DataFrame complet reste intact.
        self._nb_pages = max(1, ceil(len(df) / TAILLE_PAGE_RESULTATS))
        self._page_courante = max(0, min(self._page_courante, self._nb_pages - 1))
        debut = self._page_courante * TAILLE_PAGE_RESULTATS
        fin = debut + TAILLE_PAGE_RESULTATS
        df_page = df.iloc[debut:fin]

        # Filtrer les colonnes visibles
        colonnes_visibles = [col for col in df.columns if col not in colonnes_cachees]

        # est_corrige doit être la première colonne du tableau de correction.
        if 'est_corrige' in colonnes_visibles:
            colonnes_visibles.remove('est_corrige')
            colonnes_visibles.insert(0, 'est_corrige')

        # Créer le modèle de table (source) puis un proxy pour le filtrage
        model = TableModelEditablePersonnalise(df_page, colonnes_visibles, self._categories_list)
        model.item_changed.connect(self._on_model_item_changed)
        self._results_model = model

        # Réinitialiser la carte des produits : les clés sont les indices de ligne du
        # modèle source de la PAGE courante (0 .. len(df_page) - 1), pas les indices globaux.
        self._produits_id_map = {}
        for row_index, (_, row) in enumerate(df_page.iterrows()):
            produit_id = row.get('id') if 'id' in row.index else None
            self._produits_id_map[row_index] = {
                'id': produit_id,
                'original_data': row.to_dict(),
            }

        self._filtre_proxy = FiltreProduitsProxyModel(table_view)
        self._filtre_proxy.setSourceModel(model)
        table_view.setModel(self._filtre_proxy)

        # Assigner le delegate combobox pour la colonne 'base_variante'
        if 'base_variante' in colonnes_visibles:
            base_variante_col_index = colonnes_visibles.index('base_variante')
            delegate = ComboBoxDelegate(self._categories_list, table_view)
            table_view.setItemDelegateForColumn(base_variante_col_index, delegate)

        table_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table_view.resizeColumnsToContents()
        table_view.verticalHeader().setVisible(False)
        table_view.setAlternatingRowColors(True)
        table_view.setSortingEnabled(True)

        self._configurer_filtres(colonnes_visibles)
        self._definir_etat_filtres(True)
        self._maj_label_pagination()

    def _maj_label_pagination(self):
        """Met à jour le label et les boutons de pagination du .ui."""
        results_page = self.pages.get('traitement_resultats')
        if not results_page:
            return

        total = len(self.current_results_df) if self.current_results_df is not None else 0
        debut = self._page_courante * TAILLE_PAGE_RESULTATS
        fin = min(debut + TAILLE_PAGE_RESULTATS, total)

        label = getattr(results_page, 'label_Pagination', None)
        if label is not None:
            if self._nb_pages <= 0 or total == 0:
                label.setText("Aucun résultat")
            else:
                label.setText(
                    f"Page {self._page_courante + 1} / {self._nb_pages} "
                    f"— lignes {debut + 1} à {fin} sur {total}"
                )

        bouton_precedent = getattr(results_page, 'b_Page_Precedente', None)
        if bouton_precedent is not None:
            bouton_precedent.setEnabled(self._page_courante > 0)

        bouton_suivant = getattr(results_page, 'b_Page_Suivante', None)
        if bouton_suivant is not None:
            bouton_suivant.setEnabled(self._page_courante < self._nb_pages - 1)

    def on_page_precedente(self):
        self._changer_page(self._page_courante - 1)

    def on_page_suivante(self):
        self._changer_page(self._page_courante + 1)

    def _changer_page(self, page):
        if self.current_results_df is None or self.current_results_df.empty:
            return

        page = max(0, min(page, self._nb_pages - 1))
        if page == self._page_courante:
            return

        self._page_courante = page
        self._populate_results_table(self.current_results_df)

    def _widgets_filtres(self):
        """Retourne (combo, champ, bouton_reset) issus du .ui, ou None si absents."""
        results_page = self.pages.get('traitement_resultats')
        if not results_page:
            return None, None, None
        combo = getattr(results_page, WIDGET_COMBO_COLONNES, None)
        champ = getattr(results_page, WIDGET_CHAMP_FILTRE, None)
        bouton_reset = getattr(results_page, WIDGET_BOUTON_RESET, None)
        return combo, champ, bouton_reset

    def _definir_etat_filtres(self, actif):
        """Active/désactive les widgets de filtre existants du .ui (aucun résultat = désactivés)."""
        combo, champ, bouton_reset = self._widgets_filtres()
        for widget in (combo, champ, bouton_reset):
            if widget is not None:
                widget.setEnabled(actif)

    def _configurer_filtres(self, colonnes_visibles):
        """
        Réutilise les widgets déjà définis dans le .ui de traitement_resultats
        (comboBox_Choic_colonnes, lineEdit_Filtre, b_Reset) pour piloter le filtrage
        du tableau, plutôt que de créer une barre de filtres dynamiquement.

        Limite connue : le filtrage s'applique au modèle source, donc uniquement à la
        page affichée (au plus TAILLE_PAGE_RESULTATS lignes) et non à l'ensemble de la
        base. Un filtrage global (SQL ou pandas sur le DataFrame complet) est hors
        périmètre.
        """
        combo, champ, bouton_reset = self._widgets_filtres()
        if combo is None or champ is None:
            return

        # Repeupler le combo des colonnes sans déclencher de filtrage pendant l'opération
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Toutes les colonnes", -1)
        for col_index, colonne in enumerate(colonnes_visibles):
            combo.addItem(colonne, col_index)
        combo.setCurrentIndex(0)
        combo.blockSignals(False)

        # Le .ui définit "Texte à chercher..." comme texte (et non comme placeholder) :
        # on vide le champ pour ne pas filtrer sur ce texte par défaut.
        champ.blockSignals(True)
        champ.clear()
        champ.setPlaceholderText("Texte à chercher...")
        champ.blockSignals(False)

        # Éviter les connexions multiples si la page est repeuplée plusieurs fois
        for signal, slot in (
            (champ.textChanged, self._appliquer_filtres),
            (combo.currentIndexChanged, self._appliquer_filtres),
        ):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
            signal.connect(slot)

        if bouton_reset is not None:
            try:
                bouton_reset.clicked.disconnect(self._reinitialiser_filtres)
            except (TypeError, RuntimeError):
                pass
            bouton_reset.clicked.connect(self._reinitialiser_filtres)

        if self._filtre_proxy is not None:
            self._filtre_proxy.reinitialiser_filtres()

    def _appliquer_filtres(self):
        """Applique le filtre courant (champ texte + colonne choisie) au tableau."""
        if self._filtre_proxy is None:
            return

        combo, champ, _ = self._widgets_filtres()
        if combo is None or champ is None:
            return

        texte = champ.text()
        col_selectionnee = combo.currentData()

        self._filtre_proxy.reinitialiser_filtres()
        if not texte:
            return

        if col_selectionnee in (None, -1):
            self._filtre_proxy.definir_filtre_global(texte)
        else:
            self._filtre_proxy.definir_filtre_colonne(col_selectionnee, texte)

    def _reinitialiser_filtres(self):
        """Vide le champ de recherche, remet 'Toutes les colonnes' et retire les filtres actifs."""
        combo, champ, _ = self._widgets_filtres()

        if champ is not None:
            champ.blockSignals(True)
            champ.clear()
            champ.blockSignals(False)

        if combo is not None:
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)

        if self._filtre_proxy is not None:
            self._filtre_proxy.reinitialiser_filtres()

    def _on_model_item_changed(self, row_index, col_index, value):
        """
        Gère les changements d'éléments du modèle de table. N'est déclenché que
        pour de vraies modifications (voir TableModelEditablePersonnalise.setData).
        """
        if self._updating_cell or row_index not in self._produits_id_map:
            return

        try:
            self._updating_cell = True
            self._sauvegarder_modification(row_index)
        finally:
            self._updating_cell = False

    def _sauvegarder_modification(self, row_index):
        """Sauvegarde les modifications d'une ligne à la base de données."""
        if row_index not in self._produits_id_map:
            return

        produit_info = self._produits_id_map[row_index]
        produit_id = produit_info['id']

        if produit_id is None:
            console.print(f"[yellow]Avertissement: ID du produit manquant pour la ligne {row_index}")
            return

        model = self._results_model
        if not isinstance(model, TableModelEditablePersonnalise):
            return

        donnees_modifiees = {}
        for col_index in range(model.columnCount()):
            colonne = model.colonnes_visibles[col_index]
            item = model.item(row_index, col_index)

            if item is None:
                continue

            if colonne == 'est_corrige':
                donnees_modifiees[colonne] = item.checkState() == Qt.CheckState.Checked
            else:
                donnees_modifiees[colonne] = item.text()

        # Appliquer la correction (a_reviser = False, est_corrige = True)
        est_corrige = donnees_modifiees.get('est_corrige', False)  
        donnees_modifiees['est_corrige'] = est_corrige  
        if est_corrige:  
            donnees_modifiees['a_reviser'] = False

        # Mettre à jour la base de données
        try:
            data_service = self._obtenir_data_service()
            success = data_service.mettre_a_jour_produit(produit_id, donnees_modifiees)

            if success:
                console.print(f"[green]Produit {produit_id} mis à jour avec succès")
                # Mettre à jour le DataFrame local (via .loc pour éviter les
                # avertissements/bugs liés à l'indexation chaînée de pandas).
                # row_index est local à la page affichée : il faut le ramener à
                # l'index global du DataFrame complet.
                index_global = self._page_courante * TAILLE_PAGE_RESULTATS + row_index
                if self.current_results_df is not None and index_global < len(self.current_results_df):
                    index_ligne = self.current_results_df.index[index_global]  
                    for col, val in donnees_modifiees.items():  
                        if col in self.current_results_df.columns:  
                            dtype = self.current_results_df[col].dtype  
                            try:  
                                if pd.api.types.is_bool_dtype(dtype):  
                                    cast_val = bool(val)  
                                elif pd.api.types.is_numeric_dtype(dtype):  
                                    # gère les chaînes vides / non numériques -> NaN  
                                    cast_val = pd.to_numeric(val, errors='coerce')  
                                else:  
                                    cast_val = val  
                            except (ValueError, TypeError):  
                                cast_val = val  
                            self.current_results_df.loc[index_ligne, col] = cast_val
            else:
                QMessageBox.warning(self.page, "Erreur", f"Impossible de mettre à jour le produit {produit_id}")
        except Exception as e:
            console.print(f"[red]Erreur lors de la sauvegarde: {e}")
            QMessageBox.critical(self.page, "Erreur", f"Erreur lors de la sauvegarde: {e}")

    def _obtenir_data_service(self):
        """Retourne le service de persistance, en le créant au besoin."""
        if self.data_service is None:
            self.data_service = DataService(bd_pt=BD_PT)
        return self.data_service

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