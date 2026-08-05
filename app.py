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

from utils import console, UI_DIR

class Application:
    def __init__(self):
        # Création de l'application Qt
        self.app = QApplication(sys.argv)

        # Chargement de la fenêtre principale
        self.window = self.load_ui("mainwindow.ui")

        # Dictionnaire contenant toutes les pages
        self.pages = {}

        # Chargement des pages
        self.load_pages()

        # Configuration de la navigation
        self.setup_navigation()

        # Afficher la page d'accueil au démarrage
        self.show_page("accueil")

    def load_ui(self, filename):
        # Création du chargeur Qt
        loader = QUiLoader()

        # Construction du chemin vers le fichier .ui
        ui_path = os.path.join(UI_DIR, filename)

        # Chargement de l'interface
        widget = loader.load(ui_path)

        if widget is None:
            raise RuntimeError(
                f"Impossible de charger l'interface : {ui_path}"
            )

        return widget

    def load_pages(self):
        # Chargement de chaque page
        self.pages["accueil"] = self.load_ui("Accueil.ui")
        self.pages["traitement_produits"] = self.load_ui("Traitement_selecteur.ui")
        self.pages["convertir_pdf"] = self.load_ui("ConvertisseurPDF_selecteur.ui")
        self.pages["parametres"] = self.load_ui("Parametres.ui")

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