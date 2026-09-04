#Ce fichier gére la navigation de la page de paramètres (Parametres.ui) de l'application

import os  
from pathlib import Path  
from PySide6.QtCore import QThread, Signal, QObject, Slot, Qt  
from PySide6.QtWidgets import QMessageBox, QProgressDialog, QFileDialog  

from utils import console,_est_empaquete

class TraitementModelesWorker(QThread):
    """Réalise la création des modèles ML hors du thread UI."""
    progress_updated = Signal(int, str)
    finished = Signal(bool, str)

    def __init__(self, data_service, parent=None):
        super().__init__(parent)
        self.data_service = data_service
        self.gestion_ml = None
        self._is_cancelled = False

    def run(self):
        """Exécute la récréation des modèles dans un thread séparé."""
        from gestion_ml import GestionML
        from services import DataService


        try:
            self.progress_updated.emit(0, "Initialisation de la récréation des modèles...")

            data_service_thread = DataService(
                bd_pt=self.data_service.bd_pt,
                bd_entrainement=self.data_service.bd_entrainement,
            )
            self.gestion_ml = GestionML(data_service=data_service_thread)

            if self._is_cancelled:
                self.finished.emit(False, "Opération annulée par l'utilisateur.")
                return

            self.progress_updated.emit(10, "Préparation des données...")

            success = self.gestion_ml.recreer_modeles(
                progress_callback=self._on_progress
            )

            if self._is_cancelled:
                self.finished.emit(False, "Opération annulée par l'utilisateur.")
                return

            if success:
                self.progress_updated.emit(100, "Modèles recréés avec succès !")
                self.finished.emit(True, "La récréation des modèles a été réalisée avec succès.")
            else:
                self.finished.emit(False, "La récréation des modèles a échoué.")

        except Exception as exc:
            console.print(f"[red]Erreur lors de la récréation des modèles : {exc}")
            self.finished.emit(False, f"Erreur lors de la récréation des modèles : {str(exc)}")

    def _on_progress(self, pourcentage, message):
        """Callback de progression appelé par GestionML."""
        if self._is_cancelled:
            raise InterruptedError("Opération annulée par l'utilisateur")
        self.progress_updated.emit(int(pourcentage), message)

    def cancel(self):
        """Demande l'annulation de l'opération en cours."""
        self._is_cancelled = True
        if self.gestion_ml and hasattr(self.gestion_ml, 'cancel'):
            self.gestion_ml.cancel()

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

    def on_recreer_modeles(self):
        """Gère la récréation des modèles avec progression dans un thread séparé."""
        answer = QMessageBox.question(
            self.page,
            "Récréation des modèles de prediction",
            "Êtes-vous sûr(e) de vouloir procéder à la récréation des modèles de prediction ?\n"
            "Cette opération peut durer plusieurs minutes.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        # Création de la barre de progression
        self._modeles_progress = QProgressDialog(
            "Récréation des modèles en cours...", 
            "Annuler", 
            0, 
            100, 
            self.page
        )
        self._modeles_progress.setWindowTitle("Récréation des modèles")
        self._modeles_progress.setWindowModality(Qt.WindowModal)
        self._modeles_progress.setMinimumDuration(0)
        self._modeles_progress.setValue(0)
        self._modeles_progress.show()

        # Création et démarrage du worker
        self._modeles_worker = TraitementModelesWorker(self.data_service)
        self._modeles_worker.progress_updated.connect(self._on_modeles_progress)
        self._modeles_worker.finished.connect(self._on_modeles_fini)
        
        # Connexion du bouton Annuler
        self._modeles_progress.canceled.connect(self._on_modeles_annule)
        
        self._modeles_worker.start()

    @Slot(int, str)
    def _on_modeles_progress(self, pourcentage, message):
        """Met à jour la barre de progression des modèles."""
        dlg = self._modeles_progress
        if dlg is None:
            return
        try:
            dlg.setValue(pourcentage)
            if message:
                dlg.setLabelText(f"{message}\n{pourcentage}%")
        except RuntimeError:
            # L'objet Qt sous-jacent a été détruit entre-temps (réentrance)
            pass

    @Slot(bool, str)
    def _on_modeles_fini(self, success, message):
        """Gère la fin de la récréation des modèles."""
        if getattr(self, '_modeles_progress', None) is not None:
            self._modeles_progress.close()
            self._modeles_progress = None

        if success:
            QMessageBox.information(
                self.page,
                "Récréation des modèles",
                message
            )
        else:
            QMessageBox.critical(
                self.page,
                "Erreur",
                message
            )

        # Nettoyage du worker
        if getattr(self, '_modeles_worker', None) is not None:
            self._modeles_worker.deleteLater()
            self._modeles_worker = None

    @Slot()
    def _on_modeles_annule(self):
        """Gère l'annulation de la récréation des modèles."""
        if getattr(self, '_modeles_worker', None) is not None:
            self._modeles_worker.cancel()
            self._modeles_progress.setLabelText("Annulation en cours...")
            
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
        from maj_logiciel import MajWorker

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

        self._worker.aucune_maj.connect(self._on_aucune_maj)
        self._worker.maj_disponible.connect(self._demander_telechargement)
        self._worker.erreur.connect(self._on_maj_erreur)
        self._worker.annule.connect(self._on_download_annule_confirme)

        self.demande_telechargement.connect(self._worker.telecharger)
        self._worker.termine_download.connect(self._on_download_fini)

        self._thread.start()

        self._worker.aucune_maj.connect(self._thread.quit)
        self._worker.erreur.connect(self._thread.quit)
        self._worker.termine_download.connect(self._thread.quit)
        self._worker.annule.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._worker.deleteLater)

    @Slot()
    def _on_aucune_maj(self):
        QMessageBox.information(self.page, "Mise à jour", "EpiData est déjà à jour.")

    @Slot(str)
    def _on_maj_erreur(self, msg):
        QMessageBox.warning(self.page, "Mise à jour", f"Vérification impossible : {msg}")  

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
        dlg = self._export_progress
        if dlg is None:
            return
        try:
            dlg.setValue(pourcentage)
            if message:
                dlg.setLabelText(message)
        except RuntimeError:
            pass

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

        self._progress = QProgressDialog("Téléchargement...", "Annuler", 0, 100, self.page)
        self._progress.setWindowTitle("Téléchargement de la mise à jour")
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.setMinimumDuration(0)
        self._progress.setValue(0)
        self._progress.show()

        self._worker.progression.connect(self._progress.setValue)
        self._progress.canceled.connect(self._on_download_annule)

        self.demande_telechargement.emit(info)

    @Slot(str)
    def _on_download_fini(self, chemin):
        if getattr(self, '_progress', None) is not None:
            self._progress.close()
            self._progress.deleteLater()
            self._progress = None

        try:
            from maj_logiciel import MajGestion
            MajGestion.appliquer_maj(chemin)
        except Exception as e:
            QMessageBox.critical(self.page, "Erreur", f"Impossible de lancer la mise à jour : {e}")

    @Slot()
    def _on_download_annule(self):
        """Appelé quand l'utilisateur clique sur 'Annuler' dans la barre de progression."""
        if getattr(self, '_worker', None) is not None:
            self._worker.demander_annulation()
        if getattr(self, '_progress', None) is not None:
            self._progress.setLabelText("Annulation en cours...")
            # Empêche un nouveau "canceled" pendant qu'on attend la confirmation du worker
            self._progress.setCancelButton(None)

    @Slot()
    def _on_download_annule_confirme(self):
        """Appelé quand le worker confirme que le téléchargement a bien été arrêté."""
        if getattr(self, '_progress', None) is not None:
            self._progress.close()
            self._progress.deleteLater()
            self._progress = None

        QMessageBox.information(
            self.page, "Téléchargement annulé",
            "Le téléchargement de la mise à jour a été annulé."
        )