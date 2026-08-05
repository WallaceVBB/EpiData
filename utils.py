### Explications du fichier
# Ce fichier gère les chemins et répertoires utilisés par l'application.

## TODO's:
# TODO: il manque encore (essentiel) :
#   - USER_DATA_DIR, USER_MODELES_DIR, USER_DONNEES_DIR
#   - CHEMIN_BD, BUNDLE_BD et la copie initiale de la base de données utilisateur
#   - la logique d'initialisation des fichiers CSV et des modèles dans le répertoire utilisateur
#   - les fonctions de copie de ressources utilisateur et de vérification des fichiers existants
# TODO (amèlioration): 
#   - regrouper la gestion des chemins dans un module de configuration de l'environnement.
#   - utiliser un vrai dossier utilisateur selon la plateforme, pas un chemin codé en dur.

## Variables


### Bibliothèque
import os
import sys
import shutil
import platform
from rich.console import Console

## Préparation du Console pour faciliter debug
console = Console() # console pour enrichir les impressions dans le terminal (complément pour la fonction print)

### Code

#### Déterminer le répertoire utilisateur en fonction de la plateforme
'''if platform.system() == "Windows":
    USER_APP_DIR = os.path.expanduser("~\\AppData\\Local\\Cantine-Numerique")
elif platform.system() == "Darwin":  # macOS
    USER_APP_DIR = os.path.expanduser("~/Library/Application Support/Cantine-Numerique")
else:  # Linux
    USER_APP_DIR = os.path.expanduser("~/.local/share/Cantine-Numerique")'''
USER_APP_DIR = os.path.dirname(os.path.abspath(__file__)) # répertoire utilisateur pour stocker les fichiers de l'application

MODELES_DIR = os.path.join(USER_APP_DIR, "modeles") # sous-dossier pour les modèles de machine learning
PARAMETRES_DIR = os.path.join(USER_APP_DIR, "parametres") # sous-dossier pour les paramètres pour le traitement
UI_DIR = os.path.join(USER_APP_DIR, "ui") # sous-dossier pour les fichiers graphiques
BD_DIR = os.path.join(USER_APP_DIR, "bases_de_donnees") # sous-dossier pour les bases de données
USER_DONNEES_DIR = os.path.join(USER_APP_DIR, "donnees") # sous-dossier pour les données utilisateur
bd_entrainement = os.path.join(BD_DIR, "bd_entrainement.db") # chemin vers la base de données d'entrainement
CHEMIN_BD_PT = os.path.join(BD_DIR, "bd_produits.db") # chemin vers la base de données des produits traités

os.makedirs(USER_APP_DIR, exist_ok=True)
os.makedirs(MODELES_DIR, exist_ok=True)
os.makedirs(PARAMETRES_DIR, exist_ok=True)
os.makedirs(UI_DIR, exist_ok=True)
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

def assurer_fichier_utilisateur (nom_fichier, sous_dossier=None):
    """Assure que le fichier spécifié existe dans le directoire utilisateur.
    Si le fichier n'existe pas, il est copié depuis les ressources de l'application."""

    if sous_dossier:
        dossier_utilisateur = os.path.join(USER_APP_DIR, sous_dossier)
        os.makedirs(dossier_utilisateur, exist_ok=True)
    else:
        dossier_utilisateur = USER_APP_DIR

    chemin_fichier_utilisateur = os.path.join(dossier_utilisateur, nom_fichier)
    chemin_bundle = ressource_path(os.path.join(sous_dossier, nom_fichier) if sous_dossier else nom_fichier)

    if not os.path.exists(chemin_fichier_utilisateur):
        shutil.copy(chemin_bundle, chemin_fichier_utilisateur)

    return chemin_fichier_utilisateur

def copier_fichier_ressource_vers_utilisateur ():
    """"Copie les fichiers nécessaires depuis les ressources de l'application vers le
    dossier utilisateur lors de la première exécution."""

    fichiers_a_copier = [
        ("bd_entrainement.db", "bases_de_donnees"),
        ("bd_pt.db", "bases_de_donnees")
    ]

    for nom_fichier, sous_dossier in fichiers_a_copier:
        assurer_fichier_utilisateur(nom_fichier, sous_dossier)
