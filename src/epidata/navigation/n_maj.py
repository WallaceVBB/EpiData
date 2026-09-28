from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from epidata.utils import _est_empaquete, console


class MajNavigation(QObject):
    """Gère la vérification et l'installation des mises à jour du logiciel,
    déclenchées depuis le bouton du menubar."""

    demande_telechargement = Signal(dict)

    def __init__(self, parent_widget=None):
        super().__init__()
        # Widget parent utilisé pour les QMessageBox / QProgressDialog
        self._parent_widget = parent_widget
        self._au_demarrage = False
        self._mise_a_jour_en_cours = False
        self._chemin_installateur = None

    def on_maj_logiciel(self, au_demarrage=False):
        from epidata.maj_logiciel import MajWorker

        if self._mise_a_jour_en_cours:
            return

        if not _est_empaquete():
            if au_demarrage:
                return
            QMessageBox.information(
                self._parent_widget, "Mise à jour",
                "La mise à jour n'est disponible que dans la version installée du logiciel."
            )
            return

        self._au_demarrage = au_demarrage
        self._mise_a_jour_en_cours = True
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
        self._thread.finished.connect(self._on_thread_fini)

        self._worker.aucune_maj.connect(self._thread.quit)
        self._worker.erreur.connect(self._thread.quit)
        self._worker.annule.connect(self._thread.quit)
        self._worker.termine_download.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)

        self._thread.start()

    @Slot()
    def _on_aucune_maj(self):
        if self._au_demarrage:
            console.log("À jour")
            return
        QMessageBox.information(self._parent_widget, "Mise à jour", "EpiData est déjà à jour.")

    @Slot(str)
    def _on_maj_erreur(self, msg):
        self._fermer_progression()
        if self._au_demarrage:
            console.log(f"MAJ ignorée: {msg}")
            return
        QMessageBox.warning(self._parent_widget, "Mise à jour", f"Vérification impossible : {msg}")

    def _demander_telechargement(self, info):
        rep = QMessageBox.question(
            self._parent_widget, "Mise à jour disponible",
            f"La version {info['version']} est disponible. Télécharger et installer ?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if rep != QMessageBox.Yes:
            self._thread.quit()
            return

        self._progress = QProgressDialog("Téléchargement...", "Annuler", 0, 100, self._parent_widget)
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
        self._fermer_progression()
        self._chemin_installateur = chemin

    @Slot()
    def _on_thread_fini(self):
        chemin_installateur = self._chemin_installateur
        self._chemin_installateur = None
        self._mise_a_jour_en_cours = False
        self._au_demarrage = False

        if chemin_installateur is None:
            return
        try:
            from epidata.maj_logiciel import MajGestion
            MajGestion.appliquer_maj(chemin_installateur)
        except Exception as e:
            QMessageBox.critical(self._parent_widget, "Erreur", f"Impossible de lancer la mise à jour : {e}")

    def _fermer_progression(self):
        if getattr(self, '_progress', None) is not None:
            self._progress.close()
            self._progress.deleteLater()
            self._progress = None

    @Slot()
    def _on_download_annule(self):
        """Appelé quand l'utilisateur clique sur 'Annuler' dans la barre de progression."""
        if getattr(self, '_worker', None) is not None:
            self._worker.demander_annulation()
        if getattr(self, '_progress', None) is not None:
            self._progress.setLabelText("Annulation en cours...")
            self._progress.setCancelButton(None)

    @Slot()
    def _on_download_annule_confirme(self):
        """Appelé quand le worker confirme que le téléchargement a bien été arrêté."""
        self._fermer_progression()

        QMessageBox.information(
            self._parent_widget, "Téléchargement annulé",
            "Le téléchargement de la mise à jour a été annulé."
        )