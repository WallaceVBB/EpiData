#Ce fichier gére la navigation de la page de paramètres (Parametres.ui) de l'application

from PySide6.QtWidgets import QMessageBox

from services import DataService
from gestion_ml import GestionML
from utils import console

class ParametresNavigation:
    """Navigation et actions de la page de paramètres du logiciel."""

    def __init__(self, page_widget, show_page_callback, pages, data_service):
        self.page = page_widget
        self.pages = pages
        self.show_page = show_page_callback
        self.data_service = data_service

        self._connect_buttons()


    def _connect_buttons(self):
        self.page.b_Recreer_Modeles.clicked.connect(
            self.on_recreer_modeles
        )

        self.page.b_Recreer_BD_Entrainement.clicked.connect(
            self.on_recreer_bd_entrainement
        )

        self.page.b_Recreer_BD_PT.clicked.connect(
            self.on_recreer_bd_pt
        )

        self.page.b_MAJ_BD_Entrainement.clicked.connect(
            self.on_maj_bd_entrainement
        )

        self.page.b_Supprimer_Donnees_Utilisateur.clicked.connect(
            self.on_supprimer_donnees_utilisateur
        )

        self.page.b_MAJ_Logiciel.clicked.connect(
            self.on_maj_logiciel
        )

    def on_recreer_modeles (self):
        #TODO : mettre en QThread ou rajouter une barre de chargement en deuxième fênetre pour éviter que l'utilisateur ne comprennent pas l'application congelée
        answer = QMessageBox.question(
            self.page,
            "Récréation des modèles de prediction",
            "Êtes-vous sûr(e) de vouloir procéder à la récréation des modèles de prediction ?\nCette opération peut durer plusieurs minutes.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        try:
            GestionML.recreer_modeles()
            
            QMessageBox.information(
                self.page,
                "Recreation des modèles",
                "La récréation des modèles a été réalisée avec succès."
            )

        except Exception as e :
            console.print(f"[yellow]Avertissement: impossible de récreer les modeles de ML: {e}")
            QMessageBox.critical (
                self.page,
                "Erreur",
                f"Erreur lors de la récréation des modèles: {str(e)}"
            )
    def on_recreer_bd_entrainement (self):
            answer = QMessageBox.question(
                self.page,
                "Récréation de la Base d'entraînement",
                "Êtes-vous sûr(e) de vouloir procéder à la récréation de la Base d'entraînement ?\nCette opération supprimera toutes les données de la base actuelle d'entraînement des modèles de predictions.",
                QMessageBox.Yes | QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
    
            try:
                self.data_service.recreer_bd_entrainement()
                
                QMessageBox.information(
                    self.page,
                    "Recreation de la Base d'entraînement",
                    "La récréation de la Base d'entraînement a été réalisée avec succès."
                )
    
            except Exception as e :
                console.print(f"[yellow]Avertissement: impossible de récreer la Base d'entraînement: {e}")
                QMessageBox.critical (
                    self.page,
                    "Erreur",
                    f"Erreur lors de la récréation de la Base d'entraînement : {str(e)}"
                )

    def on_recreer_bd_pt (self):
                answer = QMessageBox.question(
                    self.page,
                    "Récréation de la Base de produits traités",
                    "Êtes-vous sûr(e) de vouloir procéder à la récréation de la Base de produits traités ?\nCette opération supprimera toutes les données de la base actuel de produits traités.",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if answer != QMessageBox.Yes:
                    return
        
                try:
                    self.data_service.recreer_bd_pt()
                    
                    QMessageBox.information(
                        self.page,
                        "Recreation de la Base de produits traités",
                        "La récréation de la Base de produits traités a été réalisée avec succès."
                    )
        
                except Exception as e :
                    console.print(f"[yellow]Avertissement: impossible de récreer la Base de produits traités: {e}")
                    QMessageBox.critical (
                        self.page,
                        "Erreur",
                        f"Erreur lors de la récréation de la Base de produits traités : {str(e)}"
                    )

    def on_maj_bd_entrainement (self):
                    try:
                        self.data_service.maj_bd_entrainement()
                        
                        QMessageBox.information(
                            self.page,
                            "Mise à jour de la Base d'entraînement",
                            "La mise à jour de la Base d'entraînement a été réalisée avec succès."
                        )
            
                    except Exception as e :
                        console.print(f"[yellow]Avertissement: impossible de réaliser la mise à jour de la Base d'entraînement: {e}")
                        QMessageBox.critical (
                            self.page,
                            "Erreur",
                            f"Erreur lors de la mise à jour de la Base d'entraînement : {str(e)}"
                        )

    def on_supprimer_donnees_utilisateur (self):
         QMessageBox.information(
            self.page,
            "En développement...",
            "Cette fonction n'est pas encore mise en place."
        )

    def on_maj_logiciel (self):
             QMessageBox.information(
                self.page,
                "En développement...",
                "Cette fonction n'est pas encore mise en place."
            )