#Ce fichier gére la navigation de la page de paramètres (Parametres.ui) de l'application

import os  
from pathlib import Path  
from PySide6.QtCore import QThread, Signal, QObject, Slot  
from PySide6.QtWidgets import QMessageBox, QProgressDialog, QFileDialog  

from services import DataService
from gestion_ml import GestionML
from utils import console,_est_empaquete
from maj_logiciel import MajWorker, MajGestion

class ParametresNavigation(QObject):
    """Navigation et actions de la page de paramètres du logiciel."""

    demande_telechargement = Signal(dict) # signal qui déclenchera telecharger() dans le worker  

    def __init__(self, page_widget, show_page_callback, pages, data_service):
        super().__init__()
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

        self.page.b_Telecharger_BD_PT.clicked.connect(
              self.on_telecharger_bd_pt
        )

        self.page.b_Telecharger_BD_Entrainement.clicked.connect(
              self.on_telecharger_bd_entrainement
        )

    def on_recreer_modeles (self):
        answer = QMessageBox.question(
            self.page,
            "Récréation des modèles de prediction",
            "Êtes-vous sûr(e) de vouloir procéder à la récréation des modèles de prediction ?\nCette opération peut durer plusieurs minutes.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        try:  
            gestion_ml = GestionML(data_service=self.data_service)  
            gestion_ml.recreer_modeles()  
  
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

    def on_maj_logiciel(self):  
        if not _est_empaquete():  
            QMessageBox.information(  
                self.page, "Mise à jour",  
                "La mise à jour n'est disponible que dans la version installée du logiciel."  
            )  
            return

        self._thread = QThread()  
        self._worker = MajWorker()  
        self._worker.moveToThread(self._thread)  
        self._thread.started.connect(self._worker.verifier)  
  
        self._worker.aucune_maj.connect(  
            lambda: QMessageBox.information(self.page, "Mise à jour",  
                                            "EpiData est déjà à jour.")  
        )  
        self._worker.maj_disponible.connect(self._demander_telechargement)  
        self._worker.erreur.connect(  
            lambda msg: QMessageBox.warning(self.page, "Mise à jour",  
                                            f"Vérification impossible : {msg}")  
        )  

        self.demande_telechargement.connect(self._worker.telecharger) 

        # progression -> barre de chargement  
        self._worker.termine_download.connect(self._on_download_fini)  

        self._thread.start()  

    def on_telecharger_bd_pt (self):
                bd_pt=self.data_service.bd_pt
                if  not os.path.exists (bd_pt) :
                    QMessageBox.information(self.page, "Erreur", "La Base de produits traités n'exist pas encore.")
                    return
        
                path, _ = QFileDialog.getSaveFileName(
                    self.page,
                    "Enregistrer le résultat en Excel",
                    str(Path.home() / "base_produits_traites.xlsx"),
                    "Fichiers Excel (*.xlsx)"
                )
                if not path:
                    return
        
                try:
                    self.data_service.exporter_bd_pt_excel(path)
                    QMessageBox.information(self.page, "Export Excel", "Fichier Excel enregistré avec succès.")
                except Exception as exc:
                    QMessageBox.critical(self.page, "Erreur", f"Impossible d'enregistrer le fichier Excel : {exc}")


    def on_telecharger_bd_entrainement (self):
                    bd_entrainement=self.data_service.bd_entrainement
                    if  not os.path.exists (bd_entrainement) :
                        QMessageBox.information(self.page, "Erreur", "La Base d'entrainement n'exist pas encore.")
                        return
            
                    path, _ = QFileDialog.getSaveFileName(
                        self.page,
                        "Enregistrer le résultat en Excel",
                        str(Path.home() / "base_entrainement.xlsx"),
                        "Fichiers Excel (*.xlsx)"
                    )
                    if not path:
                        return
            
                    try:
                        self.data_service.exporter_bd_entrainement_excel(path)
                        QMessageBox.information(self.page, "Export Excel", "Fichier Excel enregistré avec succès.")
                    except Exception as exc:
                        QMessageBox.critical(self.page, "Erreur", f"Impossible d'enregistrer le fichier Excel : {exc}")
  
    def _demander_telechargement(self, info):  
        rep = QMessageBox.question(  
            self.page, "Mise à jour disponible",  
            f"Version {info['version']} disponible. Télécharger et installer ?",  
            QMessageBox.Yes | QMessageBox.No,  
        )  
        if rep != QMessageBox.Yes:  
            return  

        # barre de progression connectée au signal du worker  
        self._progress = QProgressDialog("Téléchargement...", "Annuler", 0, 100, self.page)  
        self._worker.progression.connect(self._progress.setValue)  
  
        # ✅ on ÉMET un signal au lieu d'appeler directement -> exécution dans le thread worker  
        self.demande_telechargement.emit(info)        

    @Slot(str)  
    def _on_download_fini(self, chemin):  
        self._progress.close()  
        import maj_logiciel  
        maj_logiciel.MajGestion.appliquer_maj(chemin)  
    