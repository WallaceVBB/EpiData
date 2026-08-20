### Explications du fichier
# Ce fichier gère les chemins et répertoires utilisés par l'application,
# ainsi que quelques utilitaires texte partagés par les autres couches.

### Bibliothèque
import os
import re
import shutil
import sys
import platform
from rich.console import Console

## Préparation du Console pour faciliter debug
console = Console() # console pour enrichir les impressions dans le terminal (complément pour la fonction print)

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
    - variable d'environnement si elle est définie (tests, déploiements particuliers) ;
    - répertoire de données de l'utilisateur quand l'application est empaquetée ;
    - répertoire du projet en développement.
    """
    repertoire_force = os.environ.get(VARIABLE_ENV_USER_DIR)
    if repertoire_force:
        return os.path.abspath(os.path.expanduser(repertoire_force))
    if _est_empaquete():
        return _repertoire_donnees_utilisateur()
    return os.path.dirname(os.path.abspath(__file__))


### Code
USER_APP_DIR = _determiner_user_app_dir() # répertoire utilisateur pour stocker les fichiers de l'application

# Nom du sous-dossier de l'application dans le répertoire de données de l'utilisateur
NOM_APPLICATION = "EpiData"
VERSION = "0.1.0"
FICHIER_VERSION = os.path.join(USER_APP_DIR, ".version") 

# Variable d'environnement permettant de forcer le répertoire de données (utile pour les tests)
VARIABLE_ENV_USER_DIR = "EPIDATA_USER_DIR"

# Définir les chemins vers les sous-dossiers et fichiers
MODELES_DIR = os.path.join(USER_APP_DIR, "modeles") # sous-dossier pour les modèles de machine learning
PARAMETRES_DIR = os.path.join(USER_APP_DIR, "parametres") # sous-dossier pour les paramètres pour le traitement
GUI_DIR = os.path.join(USER_APP_DIR, "gui") # sous-dossier pour les fichiers graphiques
NAVIGATION_DIR = os.path.join(USER_APP_DIR, "navigation") # sous-dossier pour les fichiers python de navigation GUI
BD_DIR = os.path.join(USER_APP_DIR, "bases_de_donnees") # sous-dossier pour les bases de données
USER_DONNEES_DIR = os.path.join(USER_APP_DIR, "donnees") # sous-dossier pour les données utilisateur
BD_ENTRAINEMENT = os.path.join(BD_DIR, "bd_entrainement.db") # chemin vers la base de données d'entrainement
BD_PT = os.path.join(BD_DIR, "bd_pt.db") # chemin vers la base de données des produits traités

# Fichiers de ressources copiés vers le dossier utilisateur au premier lancement
FICHIERS_RESSOURCES = [
    ("pt_base.csv", "donnees"),
    ("categories.csv", "parametres"),
    ("fournisseurs.csv", "parametres"),
    ("labels.csv", "parametres"),
    ("origines.csv", "parametres"),
    ("poids_moyen_fl.csv", "parametres"),
    ("traitement_appertises.csv", "parametres"),
    ("unites_poids.csv", "parametres"),
    ("Accueil.ui", "gui"),
    ("ConvertisseurPDF_resultats.ui", "gui"),
    ("ConvertisseurPDF_selecteur.ui", "gui"),
    ("ConvertisseurPDF_chargement.ui", "gui"),
    ("mainwindow.ui", "gui"),
    ("Parametres.ui", "gui"),
    ("Traitement_chargement.ui", "gui"),
    ("Traitement_resultats.ui", "gui"),
    ("Traitement_selecteur.ui", "gui"),
]

# Créer les répertoires nécessaires si ils n'existent pas
os.makedirs(USER_APP_DIR, exist_ok=True)
os.makedirs(MODELES_DIR, exist_ok=True)
os.makedirs(PARAMETRES_DIR, exist_ok=True)
os.makedirs(BD_DIR, exist_ok=True)
os.makedirs(USER_DONNEES_DIR, exist_ok=True)

def ressource_path (relative_path):
    """Obtient le chemin absolu vers les ressources du programme, que le programme 
    soit empaqueté ou en script."""
    
    if hasattr(sys, '_MEIPASS'): # si le programme est empaqueté (.exe)
        base_path = sys._MEIPASS
    else: # si le programme est lancé en script (.py)
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

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
  
    for nom_fichier, sous_dossier in FICHIERS_RESSOURCES:  
        assurer_fichier_utilisateur(nom_fichier, sous_dossier, forcer=nouvelle_version)  
  
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

