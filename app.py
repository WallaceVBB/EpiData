# Fichier qui controle le cycle de vie de l'application

### Bibliothèques
import sys
import os
from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QSplashScreen,
    QVBoxLayout,
    QWidget,
)
from navigation.n_traitement import TraitementNavigation
from navigation.n_extracteur_factures import FactureNavigation
from services import DataService
from utils import console, GUI_DIR, NAVIGATION_DIR, copier_fichier_ressource_vers_utilisateur

class Application:
    def __init__(self):
        # Création de l'application Qt
        self.app = QApplication(sys.argv)

        # Copie des ressources vers le dossier utilisateur lors de la première exécution
        copier_fichier_ressource_vers_utilisateur()

        # Services applicatifs (persistance et données de référence)
        self.data_service = DataService(app=self)

        # Chargement de la fenêtre principale
        self.window = self.load_gui("mainwindow.ui")

        # Dictionnaire contenant toutes les pages
        self.pages = {}

        # Chargement des pages
        self.load_pages()

        # Configuration des traitements
        self.traitement_navigation = TraitementNavigation(
            self.pages["traitement_produits"],
            self.show_page,
            self.pages,
            data_service=self.data_service
        )
        self.facture_navigation = FactureNavigation(
            self.pages["convertir_pdf"],
            self.show_page,
            self.pages,
            data_service=self.data_service
        )

        # Configuration de la navigation
        self.setup_navigation()

        # Afficher la page d'accueil au démarrage
        self.show_page("accueil")

    def load_gui(self, filename):
        # Création du chargeur Qt
        loader = QUiLoader()

        # Construction du chemin vers le fichier .ui
        gui_path = os.path.join(GUI_DIR, filename)

        # Chargement de l'interface
        widget = loader.load(gui_path)

        if widget is None:
            raise RuntimeError(
                f"Impossible de charger l'interface : {gui_path}"
            )

        return widget

    def load_pages(self):
        # Chargement de chaque page
        self.pages["accueil"] = self.load_gui("Accueil.ui")
        self.pages["traitement_produits"] = self.load_gui("Traitement_selecteur.ui")
        self.pages["traitement_chargement"] = self.load_gui("Traitement_chargement.ui")
        self.pages["traitement_resultats"] = self.load_gui("Traitement_resultats.ui")
        self.pages["convertir_pdf"] = self.load_gui("ConvertisseurPDF_selecteur.ui")
        self.pages["convertisseur_pdf_chargement"] = self.load_gui("ConvetisseurPDF_chargement.ui")
        self.pages["convertisseur_pdf_resultats"] = self.load_gui("Convertisseur_PDF_resultats.ui")
        self.pages["parametres"] = self.load_gui("Parametres.ui")

        # Ajout de chaque page au QStackedWidget
        for page in self.pages.values():
            self.window.stackedWidget.addWidget(page)

    def setup_navigation(self):
        # Connexion des boutons de navigation
        self.window.b_Accueil.clicked.connect(
            lambda: self.show_page("accueil")
        )

        self.window.b_Traiter_fichier.clicked.connect(
            lambda: self.show_page("traitement_produits")
        )

        self.window.b_Convertir_PDF.clicked.connect(
            lambda: self.show_page("convertir_pdf")
        )

        self.window.b_Parametres.clicked.connect(
            lambda: self.show_page("parametres")
        )

    def show_page(self, page_name):
        # Récupération de la page demandée
        page = self.pages[page_name]

        # Affichage de la page
        self.window.stackedWidget.setCurrentWidget(page)

    def run(self):
        # Affichage de la fenêtre principale
        self.window.show()

        # Démarrage de la boucle événementielle Qt
        sys.exit(self.app.exec())