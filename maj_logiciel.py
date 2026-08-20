# Ce fichier va gérer le lancement de la mise à jour du logiciel



def verifier_maj():
    #GET https://api.github.com/repos/WallaceVBB/EpiData/releases/latest, lit tag_name et 
    # l'asset correspondant à l'exécutable Windows, compare avec VERSION via 
    # packaging.version.parse().
    pass

def telecharger_asset(url, destination):
    # télécharge dans USER_APP_DIR 
    # (déjà géré par utils.py, jamais dans le dossier d'install en lecture seule).
    pass

def appliquer_maj():
    #  écrit et lance le script updater externe, puis ferme l'application.
    pass