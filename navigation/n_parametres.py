#Ce fichier gére la navigation de la page de paramètres (Parametres.ui) de l'application

import os  
from pathlib import Path  
from PySide6.QtCore import QThread, Signal, QObject, Slot, Qt  
from PySide6.QtWidgets import QMessageBox, QProgressDialog, QFileDialog  

from services import DataService
from gestion_ml import GestionML
from utils import console,_est_empaquete
from maj_logiciel import MajWorker, MajGestion

class ExportBdPtWorker(QThread):
    """Exporte la base de produits traités (CSV par lots ou Excel) hors du thread UI."""

    progress_updated = Signal(int, str)
    finished = Signal(bool, str)

    def __init__(self, data_service, chemin, format_export, parent=None):
        super().__init__(parent)
        self.data_service = data_service
        self.chemin = chemin
        self.format_export = format_export

    def run(self):
        def progress_callback(pourcentage, message):
            self.progress_updated.emit(int(pourcentage), message)

        try:
            if self.format_export == 'csv':
                success = self.data_service.exporter_bd_pt_csv(
                    self.chemin, progress_callback=progress_callback
                )
            else:
                success = self.data_service.exporter_bd_pt_excel(
                    self.chemin, progress_callback=progress_callback
                )

            if success:
                message = f"Fichier enregistré avec succès :\n{self.chemin}"
            else:
                message = "Aucune donnée à exporter : la base de produits traités est vide."
        except Exception as exc:
            console.print(f"[red]Erreur lors de l'export de la base de produits traités : {exc}")
            success = False
            message = f"Impossible d'enregistrer le fichier : {exc}"

        self.finished.emit(success, message)


class ParametresNavigation(QObject):
    """Navigation et actions de la page de paramètres du logiciel."""

    demande_telechargement = Signal(dict) # signal qui déclenchera telecharger() dans le worker  

    def __init__(self, page_widget, show_page_callback, pages, data_service):
        super().__init__()
        self.page = page_widget
        self.pages = pages
        self.show_page = show_page_callback
        self.data_service = data_service
        self._export_worker = None
        self._export_progress = None

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
                self.data_service.creer_bd_entrainement()
                
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
        
                path, filtre = QFileDialog.getSaveFileName(
                    self.page,
                    "Enregistrer la Base de produits traités",
                    str(Path.home() / "base_produits_traites.csv"),
                    "Fichiers CSV (*.csv);;Fichiers Excel (*.xlsx)"
                )
                if not path:
                    return

                format_export = 'xlsx' if 'xlsx' in (filtre or '') else 'csv'
                extension = f".{format_export}"
                if not path.lower().endswith(extension):
                    path = str(Path(path).with_suffix(extension))

                if format_export == 'xlsx':
                    answer = QMessageBox.question(
                        self.page,
                        "Export Excel",
                        "L'export Excel charge toute la base en mémoire : sur une base très "
                        "volumineuse, l'opération peut durer plusieurs minutes et consommer "
                        "beaucoup de mémoire.\nLe format CSV est recommandé pour les gros "
                        "volumes.\n\nContinuer en Excel ?",
                        QMessageBox.Yes | QMessageBox.No,
                    )
                    if answer != QMessageBox.Yes:
                        return

                self._export_progress = QProgressDialog("Export en cours...", "Annuler", 0, 100, self.page)
                self._export_progress.setWindowTitle("Export de la Base de produits traités")
                self._export_progress.setWindowModality(Qt.WindowModal)
                self._export_progress.setValue(0)
                self._export_progress.show()
                # L'export n'est pas interruptible : annuler ne masque que la progression.
                self._export_progress.canceled.connect(self._on_export_bd_pt_annule)

                self._export_worker = ExportBdPtWorker(self.data_service, path, format_export)
                self._export_worker.progress_updated.connect(self._on_export_bd_pt_progress)
                self._export_worker.finished.connect(self._on_export_bd_pt_fini)
                self._export_worker.start()

    @Slot()
    def _on_export_bd_pt_annule(self):
        self._export_progress = None

    @Slot(int, str)
    def _on_export_bd_pt_progress(self, pourcentage, message):
        if getattr(self, '_export_progress', None) is None:
            return
        self._export_progress.setValue(pourcentage)
        if message:
            self._export_progress.setLabelText(message)

    @Slot(bool, str)
    def _on_export_bd_pt_fini(self, success, message):
        if getattr(self, '_export_progress', None) is not None:
            self._export_progress.close()
            self._export_progress = None

        if success:
            QMessageBox.information(self.page, "Export terminé", message)
        else:
            QMessageBox.critical(self.page, "Erreur", message)

        if getattr(self, '_export_worker', None) is not None:
            self._export_worker.deleteLater()
            self._export_worker = None


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
    