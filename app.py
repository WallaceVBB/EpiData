# Fichier qui controle le cycle de vie de l'application

### Bibliothèques
import os
import sys

from PySide6.QtCore import QObject, QVariantAnimation, QEasingCurve, QSettings
from PySide6.QtGui import QIcon, QPixmap, QTransform
from PySide6.QtWidgets import QApplication

from navigation.n_extracteur_factures import FactureNavigation
from navigation.n_parametres import ParametresNavigation
from navigation.n_traitement import TraitementNavigation
from navigation.n_a_propos import ProposNavigation
from navigation.n_maj import MajNavigation
from services import DataService
from utils import copier_fichier_ressource_vers_utilisateur, ressource_path, GUI_DIR


class Application (QObject):
    def __init__(self):
        # Création de l'application Qt
        self.app = QApplication(sys.argv)
        self.app.setWindowIcon(QIcon(ressource_path(os.path.join("icons", "epidata_logo.ico"))))

        # Application du style global (couleurs du logo), partagé par toutes les pages
        self.settings = QSettings("EpiData", "EpiData")
        self.theme = self.settings.value("theme", "light")
        self.charger_style_global()

        # Copie des ressources vers le dossier utilisateur lors de la première exécution
        copier_fichier_ressource_vers_utilisateur()

        # Services applicatifs (persistance et données de référence)
        self.data_service = DataService(app=self)

        # Chargement de la fenêtre principale
        self.window = self.load_gui("mainwindow.ui")
        self.window.setWindowIcon(self.app.windowIcon())

        # Attribution des icônes des boutons de la sidebar
        self.setup_icons()

        # Dictionnaire contenant toutes les pages
        self.pages = {}

        # Dernière sous-page du groupe traitement consultée  
        self.derniere_page_traitement = "traitement_produits"

        # Dernière sous-page du groupe convertisseur facture pdf
        self.derniere_page_convertisseur_pdf = "convertir_pdf"

        self.parametres_navigation = ParametresNavigation(data_service=self.data_service,load_gui=self.load_gui)

        self.maj_navigation = MajNavigation(parent_widget=self.window)

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

    def charger_style_global(self):
        style_dark = os.path.join(GUI_DIR, "styles_dark.qss")
        style_light = os.path.join(GUI_DIR, "styles_light.qss")
        nom_fichier = style_dark if self.theme == "dark" else style_light
        style_path = ressource_path(nom_fichier)
        try:
            with open(style_path, "r", encoding="utf-8") as fichier_style:
                self.app.setStyleSheet(fichier_style.read())
        except OSError:
            # L'app continue de fonctionner sans style personnalisé si le fichier est introuvable
            pass

    def basculer_theme(self):
        self.theme = "dark" if self.theme == "light" else "light"
        self.settings.setValue("theme", self.theme)
        self.charger_style_global()

    def setup_icons(self):
        # Les chemins relatifs (../icons/...) mis dans le .ui ne se résolvent pas de façon
        # fiable au runtime (dépend du cwd, casse une fois l'app packagée). On assigne donc
        # les icônes ici, via ressource_path, comme pour l'icône de l'application.
        icones = {
            self.window.b_Accueil: "i_Accueil.png",
            self.window.b_Traiter_fichier: "i_Traiter_fichier.png",
            self.window.b_Convertir_PDF: "i_Convertir_PDF.png",
            self.window.b_Historique: "i_Historique.png",
            self.window.b_Parametres: "i_Parametres.png",
            self.window.b_A_propos: "i_A_propos.png",
        }

        for bouton, nom_fichier in icones.items():
            bouton.setIcon(QIcon(ressource_path(os.path.join("icons", nom_fichier))))

        # L'icône du bouton toggle n'est pas fixée ici : elle change de sens selon l'état
        # de la sidebar (voir _update_toggle_icon), donc on garde juste le pixmap de base.
        self.toggle_icon_base = QPixmap(ressource_path(os.path.join("icons", "i_Toggle.png")))

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

        # Boutons du bas de la sidebar, qui remplacent l'ancienne barre de menu
        self.window.b_Parametres.clicked.connect(self.parametres_navigation.ouvrir_parametres)

        self.window.b_A_propos.clicked.connect(self.propos_navigation.ouvrir_propos)

        # Rétrécir / élargir la sidebar
        self.setup_sidebar_toggle()

    def setup_sidebar_toggle(self):
        # Largeurs cibles de la sidebar (repliée = icônes seules, dépliée = icônes + texte)
        self.sidebar_collapsed_width = 60
        self.sidebar_expanded_width = 200
        self.sidebar_expanded = True

        frame = self.window.frame_sidebar

        # Largeur exacte au démarrage (équivalent à ce que forçait minimumSize==maximumSize
        # dans le .ui) ; on ne s'appuie plus sur les bornes min/max du .ui à partir d'ici.
        frame.setFixedWidth(self.sidebar_expanded_width)

        # Boutons dont le texte doit disparaître/réapparaître selon l'état de la sidebar
        self.sidebar_nav_buttons = [
            self.window.b_Accueil,
            self.window.b_Traiter_fichier,
            self.window.b_Convertir_PDF,
            self.window.b_Historique,
            self.window.b_Parametres,
            self.window.b_A_propos,
        ]
        # Mémorisation du texte d'origine de chaque bouton, pour pouvoir le restaurer
        self.sidebar_button_labels = {bouton: bouton.text() for bouton in self.sidebar_nav_buttons}

        # QVariantAnimation plutôt que QPropertyAnimation sur maximumWidth : on force
        # min=max (setFixedWidth) à chaque étape, sinon le sizePolicy par défaut laisse
        # Qt choisir la largeur réelle en fonction du contenu (sizeHint), pas de la valeur
        # qu'on lui donne.
        self.sidebar_animation = QVariantAnimation()
        self.sidebar_animation.setDuration(180)
        self.sidebar_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.sidebar_animation.valueChanged.connect(lambda valeur: frame.setFixedWidth(int(valeur)))

        self.window.b_Toggle.clicked.connect(self.toggle_sidebar)

        # Icône de départ (sidebar dépliée -> flèche vers la gauche, pour la replier)
        self._update_toggle_icon()

    def toggle_sidebar(self):
        frame = self.window.frame_sidebar

        if self.sidebar_expanded:
            # On replie : le texte disparaît immédiatement pour ne pas être tronqué pendant l'animation
            for bouton in self.sidebar_nav_buttons:
                bouton.setText("")
            target_width = self.sidebar_collapsed_width
        else:
            # On déplie : le texte réapparaît
            for bouton in self.sidebar_nav_buttons:
                bouton.setText(self.sidebar_button_labels[bouton])
            target_width = self.sidebar_expanded_width

        self.sidebar_animation.stop()
        self.sidebar_animation.setStartValue(frame.width())
        self.sidebar_animation.setEndValue(target_width)
        self.sidebar_animation.start()

        self.sidebar_expanded = not self.sidebar_expanded

        self._update_toggle_icon()

    def _update_toggle_icon(self):
        # Le png de base pointe vers la droite. Sidebar dépliée -> on la retourne pour
        # pointer vers la gauche (replier). Sidebar repliée -> on garde le sens d'origine
        # (déplier).
        if self.sidebar_expanded:
            pixmap = self.toggle_icon_base.transformed(QTransform().scale(-1, 1))
        else:
            pixmap = self.toggle_icon_base

        self.window.b_Toggle.setIcon(QIcon(pixmap))

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