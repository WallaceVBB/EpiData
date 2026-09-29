"""Stockage et navigation des derniers résultats de l'application."""

from datetime import datetime
from pathlib import Path
import re
import shutil

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidgetItem,
    QMessageBox,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from epidata.utils import USER_APP_DIR, ressource_path


class HistoriqueNavigation:
    """Conserve les cinq derniers résultats de chaque type dans le dossier utilisateur."""

    MAX_RESULTATS_PAR_TYPE = 5

    def __init__(self, page, show_page, pages):
        self.page = page
        self.show_page = show_page
        self.pages = pages
        self.traitement_navigation = None
        self.facture_navigation = None
        self._derniere_entree_ouverte = None
        self.dossier_historique = Path(USER_APP_DIR) / "historique"
        self.dossier_historique.mkdir(parents=True, exist_ok=True)

        self.actualiser()

    def connecter_navigations(self, traitement_navigation, facture_navigation):
        self.traitement_navigation = traitement_navigation
        self.facture_navigation = facture_navigation

    def ouvrir_historique(self):
        self.actualiser()
        if self._derniere_entree_ouverte is not None:
            type_resultat, chemin = self._derniere_entree_ouverte
            if Path(chemin).is_file():
                self._ouvrir_entree(type_resultat, chemin)
                return
            self._derniere_entree_ouverte = None
        self.show_page("historique")

    def ouvrir_selecteur(self):
        self._derniere_entree_ouverte = None
        self.actualiser()
        self.show_page("historique")

    def actualiser(self):
        self._actualiser_liste(self.page.listWidget, "traitement", ".csv")
        self._actualiser_liste(self.page.listWidget_2, "conversion", ".xlsx")

    def enregistrer_traitement(self, dataframe, fichier_source):
        chemin = self._nouveau_chemin("traitement", fichier_source, ".csv")
        temporaire = chemin.with_name(chemin.name + ".tmp")
        dataframe.to_csv(temporaire, index=False, encoding="utf-8-sig")
        temporaire.replace(chemin)
        self._conserver_limite("traitement", ".csv")
        self.actualiser()
        return str(chemin)

    def mettre_a_jour_traitement(self, chemin, dataframe):
        chemin = Path(chemin)
        if not chemin.is_file():
            raise FileNotFoundError(f"Archive introuvable : {chemin}")
        temporaire = chemin.with_name(chemin.name + ".tmp")
        dataframe.to_csv(temporaire, index=False, encoding="utf-8-sig")
        temporaire.replace(chemin)
        self.actualiser()

    def enregistrer_conversion(self, fichier_excel, fichier_source):
        chemin = self._nouveau_chemin("conversion", fichier_source, ".xlsx")
        temporaire = chemin.with_name(chemin.name + ".tmp")
        shutil.copy2(fichier_excel, temporaire)
        temporaire.replace(chemin)
        self._conserver_limite("conversion", ".xlsx")
        self.actualiser()
        return str(chemin)

    def _nouveau_chemin(self, type_resultat, fichier_source, extension):
        nom_source = Path(fichier_source or "resultat").stem
        nom_source = re.sub(r"[^\w.-]+", "_", nom_source, flags=re.UNICODE).strip("._")
        nom_source = nom_source or "resultat"
        horodatage = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return self.dossier_historique / f"{type_resultat}_{horodatage}__{nom_source}{extension}"

    def _fichiers_recents(self, type_resultat, extension):
        motif = f"{type_resultat}_*__*{extension}"
        fichiers = sorted(
            self.dossier_historique.glob(motif),
            key=lambda chemin: chemin.name,
            reverse=True,
        )
        for ancien in fichiers[self.MAX_RESULTATS_PAR_TYPE:]:
            ancien.unlink(missing_ok=True)
        return fichiers[:self.MAX_RESULTATS_PAR_TYPE]

    def _conserver_limite(self, type_resultat, extension):
        self._fichiers_recents(type_resultat, extension)

    def _actualiser_liste(self, liste, type_resultat, extension):
        liste.clear()
        for chemin in self._fichiers_recents(type_resultat, extension):
            horodatage_nom, _, nom_source = chemin.stem.partition("__")
            horodatage = horodatage_nom.removeprefix(f"{type_resultat}_")
            try:
                date_resultat = datetime.strptime(horodatage, "%Y%m%d_%H%M%S_%f")
                date_affichee = date_resultat.strftime("%d/%m/%Y %H:%M")
            except ValueError:
                date_affichee = datetime.fromtimestamp(chemin.stat().st_mtime).strftime("%d/%m/%Y %H:%M")

            texte = f"{date_affichee} - {nom_source.replace('_', ' ')}"
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, str(chemin))
            liste.addItem(item)

            ligne = QWidget(liste)
            layout = QHBoxLayout(ligne)
            layout.setContentsMargins(4, 0, 4, 0)

            ouvrir = QToolButton(ligne)
            ouvrir.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            ouvrir.setText(texte)
            ouvrir.setToolTip(texte)
            ouvrir.setAutoRaise(True)
            ouvrir.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            ouvrir.setMinimumHeight(28)
            ouvrir.clicked.connect(
                lambda checked=False, entree=item: self._ouvrir_entree(type_resultat, entree)
            )

            supprimer = QToolButton(ligne)
            supprimer.setIcon(QIcon(ressource_path("icons/i_Poubelle.png")))
            supprimer.setToolTip("Supprimer cet élément de l'historique")
            supprimer.setAccessibleName("Supprimer de l'historique")
            supprimer.setAutoRaise(True)
            supprimer.setFixedSize(30, 30)
            supprimer.clicked.connect(
                lambda checked=False, fichier=chemin, type_fichier=type_resultat:
                    self._supprimer_resultat(fichier, type_fichier)
            )

            layout.addWidget(ouvrir, 1)
            layout.addWidget(supprimer)
            ligne.setFixedHeight(32)
            item.setSizeHint(ligne.sizeHint())
            liste.setItemWidget(item, ligne)

    def _ouvrir_entree(self, type_resultat, item):
        chemin = item.data(Qt.ItemDataRole.UserRole) if isinstance(item, QListWidgetItem) else str(item)
        self._derniere_entree_ouverte = (type_resultat, chemin)
        if type_resultat == "traitement":
            self._ouvrir_traitement(chemin)
        else:
            self._ouvrir_conversion(chemin)

    def _supprimer_resultat(self, chemin, type_resultat):
        nom_type = "ce traitement" if type_resultat == "traitement" else "cette conversion"
        reponse = QMessageBox.question(
            self.page,
            "Supprimer de l'historique",
            f"Supprimer {nom_type} de l'historique ?\n{chemin.name}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reponse != QMessageBox.StandardButton.Yes:
            return

        try:
            chemin.unlink()
            if self._derniere_entree_ouverte is not None and Path(
                self._derniere_entree_ouverte[1]
            ) == chemin:
                self._derniere_entree_ouverte = None
            self.actualiser()
        except OSError as exc:
            QMessageBox.critical(self.page, "Historique", f"Impossible de supprimer cet élément : {exc}")

    def _ouvrir_traitement(self, item):
        if self.traitement_navigation is None:
            return
        try:
            chemin = (
                item.data(Qt.ItemDataRole.UserRole)
                if isinstance(item, QListWidgetItem)
                else str(item)
            )
            dataframe = pd.read_csv(chemin, encoding="utf-8-sig")
            self.traitement_navigation.charger_historique(
                dataframe,
                chemin,
            )
        except Exception as exc:
            QMessageBox.critical(self.page, "Historique", f"Impossible d'ouvrir ce traitement : {exc}")

    def _ouvrir_conversion(self, item):
        if self.facture_navigation is None:
            return
        chemin = (
            item.data(Qt.ItemDataRole.UserRole)
            if isinstance(item, QListWidgetItem)
            else str(item)
        )
        try:
            dataframe = pd.read_excel(chemin)
            self.facture_navigation.charger_historique(dataframe, chemin)
        except Exception as exc:
            QMessageBox.critical(self.page, "Historique", f"Impossible d'ouvrir cette conversion : {exc}")