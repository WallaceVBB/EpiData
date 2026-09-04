# Ce fichier va gérer le lancement de la mise à jour du logiciel

import os  
import sys  
import platform  
import subprocess  
import requests  
from packaging import version
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
  
from utils import VERSION, USER_APP_DIR, console  
  
REPO = "WallaceVBB/EpiData"  
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"  

class MajWorker(QObject):
    progression = Signal(int)          # % de téléchargement
    maj_disponible = Signal(dict)      # infos de la release
    aucune_maj = Signal()
    termine_download = Signal(str)     # chemin de l'installeur
    erreur = Signal(str)
    annule = Signal()                  # téléchargement annulé par l'utilisateur

    def __init__(self):
        super().__init__()
        self._is_cancelled = False

    def verifier(self):
        try:
            info = MajGestion.verifier_maj()
            if info:
                self.maj_disponible.emit(info)
            else:
                self.aucune_maj.emit()
        except Exception as e:
            self.erreur.emit(str(e))

    def telecharger(self, info):
        self._is_cancelled = False
        chemin_partiel = None
        try:
            chemin_partiel = os.path.join(USER_APP_DIR, info["nom_fichier"])
            chemin = MajGestion.telecharger_asset(
                info["url"], info["nom_fichier"],
                callback_progression=self.progression.emit,
                cancel_check=lambda: self._is_cancelled
            )
            self.termine_download.emit(chemin)
        except InterruptedError:
            # Nettoyage du fichier partiellement téléchargé
            if chemin_partiel and os.path.exists(chemin_partiel):
                try:
                    os.remove(chemin_partiel)
                except OSError:
                    pass
            self.annule.emit()
        except Exception as e:
            self.erreur.emit(str(e))

    def demander_annulation(self):
        """Thread-safe : simple flag lu par le thread worker entre deux chunks."""
        self._is_cancelled = True

class MajGestion ():
    @staticmethod
    def _extension_asset_attendue():  
        """Extension de l'asset selon l'OS courant."""  
        if platform.system() == "Windows":  
            return ".exe"      # installeur Inno Setup  
        return ".AppImage"     # Linux  
    
    @staticmethod
    def verifier_maj():  
        """Interroge GitHub. Retourne un dict si une MAJ existe, sinon None.  
        Lève une exception en cas d'erreur réseau."""  
        reponse = requests.get(API_LATEST, timeout=10)  
        reponse.raise_for_status()  
        data = reponse.json()  
    
        tag = data["tag_name"].lstrip("v")        # "v1.2.0" -> "1.2.0"  
        if version.parse(tag) <= version.parse(VERSION):  
            return None                            # déjà à jour  
    
        ext = MajGestion._extension_asset_attendue()  
        asset = next(  
            (a for a in data.get("assets", []) if a["name"].endswith(ext)),  
            None  
        )  
        if asset is None:  
            raise RuntimeError(f"Aucun asset {ext} trouvé dans la release {tag}.")  
    
        return {  
            "version": tag,  
            "url": asset["browser_download_url"],  
            "nom_fichier": asset["name"],  
            "taille": asset.get("size", 0),  
        }  
    
    @staticmethod
    def telecharger_asset(url, nom_fichier, callback_progression=None):  
        """Télécharge l'asset dans USER_APP_DIR. Retourne le chemin local."""  
        destination = os.path.join(USER_APP_DIR, nom_fichier)  
        with requests.get(url, stream=True, timeout=30) as r:  
            r.raise_for_status()  
            total = int(r.headers.get("content-length", 0))  
            telecharge = 0  
            with open(destination, "wb") as f:  
                for chunk in r.iter_content(chunk_size=8192):  
                    f.write(chunk)  
                    telecharge += len(chunk)  
                    if callback_progression and total:  
                        callback_progression(int(telecharge * 100 / total))  
        return destination  
    
    @staticmethod
    def appliquer_maj(chemin_installeur):
        """Lance l'installeur/AppImage puis ferme proprement l'application."""
        systeme = platform.system()

        if systeme == "Windows":
            MajGestion._lancer_updater_windows(chemin_installeur)
        else:  # Linux : remplacer l'AppImage en cours d'exécution
            appimage_courant = os.environ.get("APPIMAGE")
            os.chmod(chemin_installeur, 0o755)
            if appimage_courant:
                MajGestion._lancer_updater_linux(chemin_installeur, appimage_courant)
            else:
                subprocess.Popen([chemin_installeur], close_fds=True)

        app = QApplication.instance()
        if app is not None:
            app.quit()
        else:
            sys.exit(0)

    @staticmethod
    def _lancer_updater_windows(chemin_installeur):
        """Écrit un script .bat qui attend que l'appli soit bien fermée (verrou
        libéré sur l'exe) avant de lancer l'installeur."""
        script = os.path.join(USER_APP_DIR, "updater.bat")
        
        # Chemin du fichier log
        log_file = os.path.join(USER_APP_DIR, "installer_log.txt")
        
        contenu = f'''@echo off
timeout /t 2 /nobreak >nul
start "" "{chemin_installeur}" /SILENT /LOG="{log_file}"
'''
        with open(script, "w") as f:
            f.write(contenu)

        subprocess.Popen(
            ["cmd", "/c", script],
            close_fds=True,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        
        # Pour debug : affiche où le log sera écrit
        console.log(f"Installeur lancé. Log attendu à : {log_file}")

    @staticmethod
    def _lancer_updater_linux(nouveau, ancien):  
        """Écrit un script shell qui attend la fermeture, remplace l'AppImage, relance."""  
        script = os.path.join(USER_APP_DIR, "updater.sh")  
        contenu = f"""#!/usr/bin/env bash
sleep 2  
mv -f "{nouveau}" "{ancien}"  
chmod +x "{ancien}"  
exec "{ancien}" &  
"""  
        with open(script, "w") as f:  
            f.write(contenu)  
        os.chmod(script, 0o755)  
        subprocess.Popen(["bash", script], close_fds=True)