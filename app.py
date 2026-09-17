# Fichier qui controle le cycle de vie de l'application

### Bibliothèques
import os
import sys

from PySide6.QtCore import QObject
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from navigation.n_extracteur_factures import FactureNavigation
from navigation.n_parametres import ParametresNavigation
from navigation.n_traitement import TraitementNavigation
from navigation.n_credits import CreditsNavigation
from navigation.n_a_propos import ProposNavigation
from navigation.n_maj import MajNavigation
from services import DataService
from utils import copier_fichier_ressource_vers_utilisateur, ressource_path


class Application (QObject):
    def __init__(self):
        # Création de l'application Qt
        self.app = QApplication(sys.argv)
        self.app.setWindowIcon(QIcon(ressource_path(os.path.join("icons", "epidata_logo.ico"))))

        # Copie des ressources vers le dossier utilisateur lors de la première exécution
        copier_fichier_ressource_vers_utilisateur()

        # Services applicatifs (persistance et données de référence)
        self.data_service = DataService(app=self)

        # Chargement de la fenêtre principale
        self.window = self.load_gui("mainwindow.ui")
        self.window.setWindowIcon(self.app.windowIcon())

        # Dictionnaire contenant toutes les pages
        self.pages = {}

        # Dernière sous-page du groupe traitement consultée  
        self.derniere_page_traitement = "traitement_produits"

        # Dernière sous-page du groupe convertisseur facture pdf
        self.derniere_page_convertisseur_pdf = "convertir_pdf"

        self.parametres_navigation = ParametresNavigation(data_service=self.data_service,load_gui=self.load_gui)

        self.maj_navigation = MajNavigation(parent_widget=self.window)

        self.credits_navigation = CreditsNavigation(load_gui=self.load_gui)

        self.propos_navigation = ProposNavigation(load_gui=self.load_gui)

        # Chargement des pages
        self.load_pages()

        # Configuration des pages
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
        from PySide6.QtUiTools import QUiLoader

        from utils import GUI_DIR

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
        self.pages["convertisseur_pdf_chargement"] = self.load_gui("ConvertisseurPDF_chargement.ui")
        self.pages["convertisseur_pdf_resultats"] = self.load_gui("ConvertisseurPDF_resultats.ui")
        self.pages["parametres"] = self.load_gui("Parametres.ui")

        # Ajout de chaque page au QStackedWidget
        for page in self.pages.values():
            self.window.stackedWidget.addWidget(page)

    def setup_navigation(self):
        # Connexion des boutons de navigation
        self.window.b_Accueil.clicked.connect(lambda: self.show_page("accueil"))

        self.window.b_Traiter_fichier.clicked.connect(lambda: self.show_page(self.derniere_page_traitement))

        self.window.b_Convertir_PDF.clicked.connect(lambda: self.show_page(self.derniere_page_convertisseur_pdf))

        self.window.actionParametres_avances.triggered.connect(self.parametres_navigation.ouvrir_parametres)

        self.window.actionMettre_jour.triggered.connect(self.maj_navigation.on_maj_logiciel)

        self.window.actionCr_dits.triggered.connect(self.credits_navigation.ouvrir_credits)

        self.window.actionA_propos.triggered.connect(self.propos_navigation.ouvrir_propos)

    def show_page(self, page_name):
        # Mémorise la dernière sous-page du groupe traitement  
        if page_name in ("traitement_produits", "traitement_chargement", "traitement_resultats"):  
            self.derniere_page_traitement = page_name  
    
        if page_name in ("convertir_pdf","convertisseur_pdf_chargement","convertisseur_pdf_resultats"):
            self.derniere_page_convertisseur_pdf = page_name

        # Récupération de la page demandée  
        page = self.pages[page_name]  
    
        # Affichage de la page  
        self.window.stackedWidget.setCurrentWidget(page)

    def ouvrir_parametres(self):
        self.show_page("parametres")

    def ouvrir_credits(self):
        self.show_page("credits")

    def ouvrir_propos(self):
        self.show_page("Propos")

    def _verifier_maj_au_demarrage(self):
        self.maj_navigation.on_maj_logiciel(au_demarrage=True)
  
    def run(self):
        # Affichage de la fenêtre principale
        self.window.show()

        self._verifier_maj_au_demarrage()

        # Démarrage de la boucle événementielle Qt
        sys.exit(self.app.exec())