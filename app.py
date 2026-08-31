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
    QMessageBox,
)
from navigation.n_traitement import TraitementNavigation
from navigation.n_extracteur_factures import FactureNavigation
from navigation.n_parametres import ParametresNavigation
from services import DataService
from utils import console, GUI_DIR, NAVIGATION_DIR, copier_fichier_ressource_vers_utilisateur,  _est_empaquete
from maj_logiciel import MajWorker, MajGestion 

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

        # Dernière sous-page du groupe traitement consultée  
        self.derniere_page_traitement = "traitement_produits"

        # Dernière sous-page du groupe convertisseur facture pdf
        self.derniere_page_convertisseur_pdf = "convertir_pdf"

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
        self.parametres_navigation = ParametresNavigation(
            self.pages["parametres"],
            self.show_page,
            self.pages,
            data_service=self.data_service
        )

        # Configuration de la navigation
        self.setup_navigation()

        # Afficher la page d'accueil au démarrage
        self.show_page("accueil")

        self._verifier_maj_au_demarrage()

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
        self.pages["convertisseur_pdf_chargement"] = self.load_gui("ConvertisseurPDF_chargement.ui")
        self.pages["convertisseur_pdf_resultats"] = self.load_gui("ConvertisseurPDF_resultats.ui")
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
            lambda: self.show_page(self.derniere_page_traitement)
        )

        self.window.b_Convertir_PDF.clicked.connect(
            lambda: self.show_page(self.derniere_page_convertisseur_pdf)
        )

        self.window.b_Parametres.clicked.connect(
            lambda: self.show_page("parametres")
        )

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

    def _verifier_maj_au_demarrage(self):  
        # Ne rien faire en développement (sys.executable = python)  
        if not _est_empaquete():  
            return  
  
        self._thread_maj = QThread()  
        self._worker_maj = MajWorker()  
        self._worker_maj.moveToThread(self._thread_maj)  
  
        # Déclenche verifier() DANS le thread  
        self._thread_maj.started.connect(self._worker_maj.verifier)  
  
        # SILENCIEUX : on ne connecte QUE le cas "mise à jour disponible"  
        self._worker_maj.maj_disponible.connect(self._proposer_maj_demarrage)  
  
        # aucune_maj et erreur : on ne fait rien (ou un simple log)  
        self._worker_maj.aucune_maj.connect(lambda: console.log("À jour"))  
        self._worker_maj.erreur.connect(lambda msg: console.log(f"MAJ ignorée: {msg}"))  
  
        # Nettoyage du thread  
        self._worker_maj.maj_disponible.connect(self._thread_maj.quit)  
        self._worker_maj.aucune_maj.connect(self._thread_maj.quit)  
        self._worker_maj.erreur.connect(self._thread_maj.quit)  
        self._thread_maj.finished.connect(self._thread_maj.deleteLater)  
  
        self._thread_maj.start()  
  
    def _proposer_maj_demarrage(self, info):  
        rep = QMessageBox.question(  
            self.window, "Mise à jour disponible",  
            f"La version {info['version']} est disponible. Télécharger et installer ?",  
            QMessageBox.Yes | QMessageBox.No,  
        )  
        if rep != QMessageBox.Yes:
            return

        # télécharger dans un thread pour ne pas geler l'UI  
        self._thread_dl = QThread()  
        self._worker_dl = MajWorker()  
        self._worker_dl.moveToThread(self._thread_dl)  
        self._thread_dl.started.connect(lambda: self._worker_dl.telecharger(info))  
        self._worker_dl.termine_download.connect(MajGestion.appliquer_maj)  
        self._worker_dl.termine_download.connect(self._thread_dl.quit)  
        self._worker_dl.erreur.connect(self._thread_dl.quit)  
        self._thread_dl.start()

    def run(self):
        # Affichage de la fenêtre principale
        self.window.show()

        # Démarrage de la boucle événementielle Qt
        sys.exit(self.app.exec())