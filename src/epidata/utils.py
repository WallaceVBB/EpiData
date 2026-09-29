"""Explications du fichier
Ce fichier gère les chemins et répertoires utilisés par l'application,
ainsi que quelques utilitaires texte partagés par les autres couches.
"""

### Bibliothèque
import csv
import os
import platform
import re
import shutil
import sys

from rich.console import Console

## Préparation du Console pour faciliter debug
console = Console() # console pour enrichir les impressions dans le terminal (complément pour la fonction print)

# Variable d'environnement permettant de forcer le répertoire de données (utile pour les tests)
NOM_APPLICATION = "EpiData"
VERSION = "1.1.0"
VARIABLE_ENV_USER_DIR = "EPIDATA_USER_DIR"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESOURCE_ROOT = getattr(sys, "_MEIPASS", PROJECT_ROOT)
RESOURCE_PACKAGE_ROOT = (
    os.path.join(sys._MEIPASS, "epidata", "resources")
    if hasattr(sys, "_MEIPASS")
    else os.path.join(os.path.dirname(__file__), "resources")
)
PACKAGE_RESOURCE_DIRS = ("gui", "icons", "parametres")

def _est_empaquete():
    """Indique si l'application est exécutée depuis un exécutable PyInstaller."""
    return getattr(sys, 'frozen', False) or hasattr(sys, '_MEIPASS')


def _repertoire_donnees_utilisateur():
    """Répertoire de données de l'utilisateur, selon la plateforme."""
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(os.path.join("~", "AppData", "Local"))
    elif platform.system() == "Darwin":  # macOS
        base = os.path.expanduser(os.path.join("~", "Library", "Application Support"))
    else:  # Linux et autres
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser(os.path.join("~", ".local", "share"))
    return os.path.join(base, NOM_APPLICATION)


def _determiner_user_app_dir():
    """Détermine le répertoire de l'application :
    - variable d'environnement si elle est définie (développement, empaqueté) ;
    - répertoire de données de l'utilisateur quand l'application est empaquetée ;
    - répertoire du projet en développement.
    """
    repertoire_force = os.environ.get(VARIABLE_ENV_USER_DIR)
    if repertoire_force:
        return os.path.abspath(os.path.expanduser(repertoire_force))
    if _est_empaquete():
        return _repertoire_donnees_utilisateur()
    return PROJECT_ROOT


### Code
USER_APP_DIR = _determiner_user_app_dir() # répertoire utilisateur pour stocker les fichiers de l'application
FICHIER_VERSION = os.path.join(USER_APP_DIR, ".version") 

# Définir les chemins vers les sous-dossiers et fichiers
MODELES_DIR = os.path.join(USER_APP_DIR, "modeles") # sous-dossier pour les modèles de machine learning
PARAMETRES_DIR = os.path.join(USER_APP_DIR, "parametres") # sous-dossier pour les paramètres pour le traitement
GUI_DIR = os.path.join(USER_APP_DIR, "gui") # sous-dossier pour les fichiers graphiques
NAVIGATION_DIR = os.path.join(os.path.dirname(__file__), "navigation")
BD_DIR = os.path.join(USER_APP_DIR, "bases_de_donnees") # sous-dossier pour les bases de données
BD_ENTRAINEMENT = os.path.join(BD_DIR, "bd_entrainement.db") # chemin vers la base de données d'entrainement
BD_PT = os.path.join(BD_DIR, "bd_pt.db") # chemin vers la base de données des produits traités
TESSERACT_EXE = os.path.join(RESOURCE_ROOT, "tesseract", "tesseract.exe")
TESSDATA_DIR = os.path.join(RESOURCE_ROOT, "tesseract", "tessdata")

# Dossiers dont toutes les ressources sont copiées vers le dossier utilisateur
FICHIERS_RESSOURCES = ("parametres", "gui")

# Créer les répertoires nécessaires si ils n'existent pas
os.makedirs(USER_APP_DIR, exist_ok=True)
os.makedirs(MODELES_DIR, exist_ok=True)
os.makedirs(PARAMETRES_DIR, exist_ok=True)
os.makedirs(BD_DIR, exist_ok=True)

def ressource_path (relative_path):
    """Obtient le chemin absolu vers les ressources du programme, que le programme 
    soit empaqueté ou en script."""

    relative_path = os.fspath(relative_path)
    premier_dossier = os.path.normpath(relative_path).split(os.sep, 1)[0]
    racine = (
        RESOURCE_PACKAGE_ROOT
        if premier_dossier in PACKAGE_RESOURCE_DIRS
        else RESOURCE_ROOT
    )
    return os.path.join(racine, relative_path)

def detecter_separateur_csv(chemin_fichier):
    """Détecte le séparateur d'un CSV courant (virgule, point-virgule, tabulation ou pipe)."""
    with open(chemin_fichier, encoding="utf-8-sig", newline="") as fichier:
        extrait = fichier.read(8192)

    try:
        return csv.Sniffer().sniff(extrait, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","

def assurer_fichier_utilisateur(nom_fichier, sous_dossier=None, forcer=False):  
    """Assure que le fichier spécifié existe dans le directoire utilisateur.
    Si le fichier n'existe pas ou est une version ancienne, 
    il est copié depuis les ressources de l'application."""
    if sous_dossier:  
        dossier_utilisateur = os.path.join(USER_APP_DIR, sous_dossier)  
        os.makedirs(dossier_utilisateur, exist_ok=True)  
    else:  
        dossier_utilisateur = USER_APP_DIR  
  
    chemin_fichier_utilisateur = os.path.join(dossier_utilisateur, nom_fichier)  
    chemin_bundle = ressource_path(  
        os.path.join(sous_dossier, nom_fichier) if sous_dossier else nom_fichier  
    )  
  
    doit_copier = forcer or not os.path.exists(chemin_fichier_utilisateur)  
    if doit_copier and os.path.exists(chemin_bundle):  
        if os.path.abspath(chemin_bundle) != os.path.abspath(chemin_fichier_utilisateur):  
            shutil.copy(chemin_bundle, chemin_fichier_utilisateur)  
  
    return chemin_fichier_utilisateur

def copier_fichier_ressource_vers_utilisateur():  
    """Copie les ressources vers le dossier utilisateur.  
    Force la re-copie si la VERSION a changé depuis la dernière fois."""  
    version_installee = _lire_version_installee()  
    nouvelle_version = version_installee != VERSION  # True au 1er lancement ou après MAJ  
  
    for dossier in FICHIERS_RESSOURCES:
        chemin_bundle = ressource_path(dossier)
        dossier_utilisateur = os.path.join(USER_APP_DIR, dossier)
        if not os.path.isdir(chemin_bundle):
            continue
        if os.path.abspath(chemin_bundle) == os.path.abspath(dossier_utilisateur):
            continue

        for racine, _, fichiers in os.walk(chemin_bundle):
            chemin_relatif = os.path.relpath(racine, chemin_bundle)
            destination_racine = (
                dossier_utilisateur
                if chemin_relatif == "."
                else os.path.join(dossier_utilisateur, chemin_relatif)
            )
            os.makedirs(destination_racine, exist_ok=True)
            for nom_fichier in fichiers:
                source = os.path.join(racine, nom_fichier)
                destination = os.path.join(destination_racine, nom_fichier)
                if nouvelle_version or not os.path.exists(destination):
                    shutil.copy2(source, destination)
  
    if nouvelle_version:  
        _ecrire_version_installee()

def nettoyer_texte (texte):
    """Nettoie et normalise le texte (source unique utilisée par le traitement et le ML)."""
    texte = str(texte).lower()
    texte = re.sub(r'[^\w\s-]', '', texte)
    texte = re.sub(r'\s+', ' ', texte).strip()
    return texte

def _lire_version_installee():  
    """Version des ressources déjà copiées dans USER_APP_DIR (None si absente)."""  
    try:  
        with open(FICHIER_VERSION, "r", encoding="utf-8") as f:  
            return f.read().strip()  
    except FileNotFoundError:  
        return None  
  
def _ecrire_version_installee():  
    with open(FICHIER_VERSION, "w", encoding="utf-8") as f:  
        f.write(VERSION)  

