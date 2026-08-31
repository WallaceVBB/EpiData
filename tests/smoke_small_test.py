"""Smoke test du refactoring, SANS aucun entraînement de modèle ML.

Ce script vérifie que les couches (navigation → traitement → ML → persistance)
s'importent et fonctionnent, en utilisant un répertoire utilisateur temporaire et
des modèles `.joblib` factices. Toute tentative d'entraînement (`creer_modeles`,
`recreer_modeles`) ou d'appel à `classifier_produits` fait échouer le test.

À l'inverse de `tests/full_test.py` (entraînement réel, plusieurs minutes), ce
script est rapide et peut tourner dans une boucle de développement.

Utilisation : python tests/smoke_test.py
"""

import os
import platform
import shutil
import sys
import tempfile
from unittest.mock import MagicMock, patch

RACINE_PROJET = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE_PROJET not in sys.path:
    sys.path.insert(0, RACINE_PROJET)

# Répertoire utilisateur temporaire : aucune écriture dans le dépôt.
# Choisi AVANT l'import des modules de l'application, comme dans full_test.py :
# utils.py résout tous les chemins à l'import.
REPERTOIRE_TEMPORAIRE = tempfile.mkdtemp(prefix="epidata_smoke_")
os.environ["EPIDATA_USER_DIR"] = REPERTOIRE_TEMPORAIRE

import joblib  # noqa: E402
from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: E402

import data_processing  # noqa: E402
import gestion_ml  # noqa: E402
import services  # noqa: E402
import utils  # noqa: E402
import maj_logiciel  # noqa: E402
from gestion_ml import GestionML  # noqa: E402
from maj_logiciel import MajGestion, MajWorker  # noqa: E402

ENTRAINEMENTS_DETECTES = []


def _garde_entrainement(nom):
    def _refuser(*args, **kwargs):
        ENTRAINEMENTS_DETECTES.append(nom)
        raise AssertionError(f"Le smoke test ne doit jamais appeler {nom}")
    return _refuser


gestion_ml.GestionML.creer_modeles = _garde_entrainement("GestionML.creer_modeles")
gestion_ml.GestionML.recreer_modeles = _garde_entrainement("GestionML.recreer_modeles")
data_processing.ClassificateurProduits.classifier_produits = _garde_entrainement(
    "ClassificateurProduits.classifier_produits"
)


def verifier(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"  ok - {message}")


def etape(numero, titre):
    print(f"\n{numero}. {titre}")


def test_imports():
    etape(1, "Import des modules refactorés")
    import app
    import main
    import navigation.n_traitement
    import navigation.n_extracteur_factures as n_extracteur
    from extracteur_facture import extracteur_generique, extracteur_jardimed

    for module in (app, main, navigation.n_traitement, n_extracteur, extracteur_generique, extracteur_jardimed):
        verifier(module is not None, f"{module.__name__} s'importe sans erreur")

    verifier(hasattr(gestion_ml, "GestionML"), "gestion_ml expose la classe GestionML")
    verifier(
        not any(nom in vars(gestion_ml) for nom in ("creer_modeles", "recreer_modeles", "predire_avec_cosine_similarity")),
        "gestion_ml n'expose plus de fonctions au niveau module",
    )
    verifier(
        not hasattr(data_processing, "ImportationDonnees"),
        "data_processing n'expose plus ImportationDonnees (tkinter)",
    )
    verifier(
        set(n_extracteur.EXTRACTEURS) == {"generique", "jardimed"},
        "les extracteurs sont importés normalement (sans importlib)",
    )
    verifier(
        not any(hasattr(services, nom) and callable(getattr(services, nom)) and not isinstance(getattr(services, nom), type)
                for nom in ("creer_bd_pt", "creer_bd_entrainement", "maj_bd_entrainement")),
        "services n'expose plus de wrappers de compatibilité",
    )

    # Vérifie la présence de l'API réellement exercée par tests/full_test.py.
    # Une régression ici signale que ce smoke test est désynchronisé du reste.
    verifier(
        hasattr(GestionML, "NOMS_MODELES") and len(GestionML.NOMS_MODELES) > 0,
        "GestionML.NOMS_MODELES est défini et non vide",
    )
    verifier(callable(getattr(GestionML, "chemin_modele", None)), "GestionML.chemin_modele existe")
    verifier(callable(getattr(GestionML, "preparer_bd_entrainement", None)), "GestionML.preparer_bd_entrainement existe")
    verifier(callable(getattr(GestionML, "predire_avec_methode_hybride", None)), "GestionML.predire_avec_methode_hybride existe")


def test_sources_propres():
    etape(2, "Absence de dépendances interdites dans les sources")
    for nom_fichier in os.listdir(os.path.join(RACINE_PROJET, "navigation")):
        if not nom_fichier.endswith(".py"):
            continue
        chemin = os.path.join(RACINE_PROJET, "navigation", nom_fichier)
        with open(chemin, encoding="utf-8") as fichier:
            contenu = fichier.read()
        verifier("sqlite3" not in contenu, f"navigation/{nom_fichier} n'utilise pas sqlite3 directement")

    with open(os.path.join(RACINE_PROJET, "data_processing.py"), encoding="utf-8") as fichier:
        contenu = fichier.read()
    verifier("tkinter" not in contenu, "data_processing.py n'importe plus tkinter")
    verifier("sqlite3" not in contenu, "data_processing.py ne contient plus de SQL brut")
    verifier("INSERT INTO" not in contenu.upper(), "data_processing.py ne contient plus d'INSERT SQL")


def test_schema_produits():
    etape(3, "Schéma de la table produits créé par DataService")
    # Comme dans full_test.py : DataService() sans argument, le chemin de la base
    # est résolu via EPIDATA_USER_DIR par utils.py. On ne présume plus ici d'une
    # structure de sous-dossiers codée en dur (c'était la source de désynchro).
    data_service = services.DataService()
    verifier(data_service.conn is not None, f"base de produits ouverte : {data_service.bd_pt}")

    curseur = data_service.conn.cursor()
    curseur.execute("PRAGMA table_info(produits)")
    colonnes = [ligne[1] for ligne in curseur.fetchall()]

    verifier("methode_prediction" in colonnes, "la colonne methode_prediction est créée par creer_bd_pt")
    verifier("conservation" in colonnes and "date_maj" in colonnes, "les colonnes existantes sont préservées")
    for colonne in services.COLONNES_PRODUITS:
        verifier(colonne in colonnes, f"la colonne {colonne} existe dans le schéma")

    # La migration ad-hoc ne doit rien avoir à faire sur une base neuve.
    data_service.migrer_bd_si_necessaire()
    curseur.execute("PRAGMA table_info(produits)")
    verifier(
        [ligne[1] for ligne in curseur.fetchall()] == colonnes,
        "aucune migration ad-hoc n'est nécessaire sur une base neuve",
    )
    return data_service


def test_cycle_persistance(data_service):
    etape(4, "Cycle de persistance via DataService")
    produit = {
        'texte_brut': 'TOMATE GRAPPE FRANCE 5KG',
        'texte_propre': utils.nettoyer_texte('TOMATE GRAPPE FRANCE 5KG'),
        'code_produit': 'TEST-001',
        'base_variante': 'tomate grappe',
        'confiance_basevariante': 99.0,
        'methode_prediction': 'TF-IDF_Cosine',
        'a_reviser': False,
        'est_corrige': False,
    }
    produit_id = data_service.inserer_produit(produit)
    verifier(produit_id is not None, "inserer_produit retourne un identifiant")

    relu = data_service.obtenir_produit_par_code_produit('TEST-001')
    verifier(relu is not None and relu['base_variante'] == 'tomate grappe', "le produit est relu par code produit")
    verifier(relu['methode_prediction'] == 'TF-IDF_Cosine', "methode_prediction est persistée")
    verifier(
        data_service.obtenir_produit_par_texte_brut('TOMATE GRAPPE FRANCE 5KG') is not None,
        "le produit est relu par texte brut",
    )

    produits_en_base = data_service.obtenir_produits()
    verifier(len(produits_en_base) == 1, "obtenir_produits reflète le produit inséré")

    supprimes = data_service.supprimer_produits([produit])
    verifier(supprimes == 1, "supprimer_produits supprime le produit")
    verifier(
        data_service.obtenir_produit_par_code_produit('TEST-001') is None,
        "le produit n'est plus présent après suppression",
    )


def test_nettoyer_texte():
    etape(5, "Source unique de nettoyer_texte")
    texte = "  JUS d'Orange  BIO 1,5L!! "
    attendu = utils.nettoyer_texte(texte)
    verifier(gestion_ml.GestionML.nettoyer_texte(texte) == attendu, "GestionML.nettoyer_texte délègue à utils")
    verifier(attendu == "jus dorange bio 15l", "le nettoyage produit le résultat attendu")


def _fausse_reponse_github(tag_name, assets):
    """Construit un mock de réponse `requests.get` imitant l'API GitHub."""
    reponse = MagicMock()
    reponse.raise_for_status = lambda: None
    reponse.json.return_value = {"tag_name": tag_name, "assets": assets}
    return reponse


def test_maj_logiciel_structure():
    """Vérifie juste que l'API attendue existe (contrat, pas comportement)."""
    etape(6, "Module maj_logiciel - structure et méthodes")

    for signal in ("progression", "maj_disponible", "aucune_maj", "termine_download", "erreur"):
        verifier(hasattr(MajWorker, signal), f"MajWorker expose le signal {signal}")
    for methode in ("verifier", "telecharger"):
        verifier(callable(getattr(MajWorker, methode, None)), f"MajWorker a la méthode {methode}")

    for methode in (
        "verifier_maj", "telecharger_asset", "appliquer_maj",
        "_extension_asset_attendue", "_lancer_updater_windows", "_lancer_updater_linux",
    ):
        verifier(callable(getattr(MajGestion, methode, None)), f"MajGestion.{methode} existe")

    verifier(hasattr(maj_logiciel, 'REPO'), "maj_logiciel expose la constante REPO")
    verifier(hasattr(maj_logiciel, 'API_LATEST'), "maj_logiciel expose la constante API_LATEST")
    verifier("github.com" in maj_logiciel.API_LATEST, "API_LATEST pointe vers GitHub")


def test_verifier_maj_comportement():
    """Teste la vraie logique de comparaison de version et de sélection d'asset,
    sans faire de requête réseau (requests.get est mocké)."""
    etape(7, "MajGestion.verifier_maj - comportement (mocké)")

    ext_attendue = MajGestion._extension_asset_attendue()

    # Cas 1 : une version supérieure est disponible -> doit retourner un dict cohérent
    assets = [
        {"name": f"EpiData-Setup{ext_attendue}", "browser_download_url": "https://x/exe", "size": 42},
        {"name": "readme.txt", "browser_download_url": "https://x/readme.txt", "size": 1},
    ]
    with patch("maj_logiciel.requests.get", return_value=_fausse_reponse_github("v99.0.0", assets)):
        info = MajGestion.verifier_maj()
    verifier(info is not None, "verifier_maj détecte une version strictement supérieure")
    verifier(info["version"] == "99.0.0", "le préfixe 'v' est bien retiré du numéro de version")
    verifier(info["nom_fichier"].endswith(ext_attendue), f"l'asset sélectionné correspond à l'extension {ext_attendue} de l'OS")
    verifier(info["url"] == "https://x/exe", "l'URL de téléchargement retournée est celle du bon asset")

    # Cas 2 : version distante identique -> déjà à jour
    with patch("maj_logiciel.requests.get", return_value=_fausse_reponse_github(f"v{utils.VERSION}", assets)):
        info_egal = MajGestion.verifier_maj()
    verifier(info_egal is None, "verifier_maj retourne None si la version distante == version locale")

    # Cas 3 : version distante inférieure -> déjà à jour
    with patch("maj_logiciel.requests.get", return_value=_fausse_reponse_github("v0.0.1", assets)):
        info_inferieur = MajGestion.verifier_maj()
    verifier(info_inferieur is None, "verifier_maj retourne None si la version distante < version locale")

    # Cas 4 : aucun asset ne correspond à l'extension de l'OS -> doit lever une erreur claire
    assets_sans_correspondance = [{"name": "readme.txt", "browser_download_url": "https://x/r.txt", "size": 1}]
    exception_levee = False
    with patch("maj_logiciel.requests.get", return_value=_fausse_reponse_github("v99.0.0", assets_sans_correspondance)):
        try:
            MajGestion.verifier_maj()
        except RuntimeError:
            exception_levee = True
    verifier(exception_levee, "verifier_maj lève RuntimeError si aucun asset ne correspond à l'OS courant")


def test_telecharger_asset_comportement():
    """Teste que le téléchargement écrit bien le fichier et déclenche la progression,
    sans faire de vraie requête HTTP."""
    etape(8, "MajGestion.telecharger_asset - comportement (mocké)")

    contenu_attendu = b"contenu-installeur-factice" * 1000  # ~27 Ko, plusieurs chunks

    reponse = MagicMock()
    reponse.raise_for_status = lambda: None
    reponse.headers = {"content-length": str(len(contenu_attendu))}
    reponse.iter_content = lambda chunk_size: [
        contenu_attendu[i:i + chunk_size] for i in range(0, len(contenu_attendu), chunk_size)
    ]
    reponse.__enter__ = MagicMock(return_value=reponse)
    reponse.__exit__ = MagicMock(return_value=False)

    progressions = []
    with patch("maj_logiciel.requests.get", return_value=reponse):
        chemin = MajGestion.telecharger_asset(
            "https://x/fake-installer.exe",
            "fake-installer.exe",
            callback_progression=progressions.append,
        )

    verifier(os.path.exists(chemin), "telecharger_asset écrit bien un fichier sur disque")
    with open(chemin, "rb") as f:
        verifier(f.read() == contenu_attendu, "le contenu écrit sur disque correspond exactement à celui téléchargé")
    verifier(len(progressions) > 0, "le callback de progression est appelé au moins une fois")
    verifier(progressions[-1] == 100, "la progression atteint bien 100% en fin de téléchargement")
    verifier(all(0 <= p <= 100 for p in progressions), "toutes les valeurs de progression sont entre 0 et 100")


def test_scripts_updater_generation():
    """Teste que les scripts d'installation (Windows/Linux) sont bien générés avec
    le bon contenu (chemins, délai anti-verrou de fichier). subprocess.Popen est
    mocké : aucun vrai processus n'est lancé."""
    etape(9, "Génération des scripts updater.bat / updater.sh")

    faux_installeur = os.path.join(REPERTOIRE_TEMPORAIRE, "EpiData-Setup.exe")
    with patch("maj_logiciel.subprocess.Popen") as mock_popen:
        MajGestion._lancer_updater_windows(faux_installeur)
    verifier(mock_popen.called, "_lancer_updater_windows lance bien un processus (mocké)")
    script_bat = os.path.join(utils.USER_APP_DIR, "updater.bat")
    verifier(os.path.exists(script_bat), "le script updater.bat est bien créé sur disque")
    contenu_bat = open(script_bat, encoding="utf-8").read()
    verifier(faux_installeur in contenu_bat, "updater.bat référence le bon chemin d'installeur")
    verifier("SILENT" in contenu_bat, "updater.bat lance l'installeur en mode silencieux Inno Setup")
    verifier("timeout" in contenu_bat.lower(), "updater.bat attend avant de lancer l'installeur (anti-verrou fichier)")

    faux_nouveau = os.path.join(REPERTOIRE_TEMPORAIRE, "EpiData-new.AppImage")
    faux_ancien = os.path.join(REPERTOIRE_TEMPORAIRE, "EpiData.AppImage")
    open(faux_nouveau, "wb").close()
    with patch("maj_logiciel.subprocess.Popen") as mock_popen_linux:
        MajGestion._lancer_updater_linux(faux_nouveau, faux_ancien)
    verifier(mock_popen_linux.called, "_lancer_updater_linux lance bien le script shell (mocké)")
    script_sh = os.path.join(utils.USER_APP_DIR, "updater.sh")
    verifier(os.path.exists(script_sh), "le script updater.sh est bien créé sur disque")
    contenu_sh = open(script_sh, encoding="utf-8").read()
    verifier("sleep 2" in contenu_sh, "updater.sh attend 2s avant de remplacer l'AppImage (anti-verrou fichier)")
    verifier(faux_nouveau in contenu_sh and faux_ancien in contenu_sh, "updater.sh référence les bons chemins source/destination")


def creer_modeles_factices(dossier_modeles):
    """Crée des artefacts .joblib minuscules (aucun entraînement de classifieur)."""
    os.makedirs(dossier_modeles, exist_ok=True)
    base_variantes = ["tomate grappe", "yaourt nature", "pain complet"]
    vectoriseur = TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 3))
    vectoriseur.fit(base_variantes)
    joblib.dump(vectoriseur, os.path.join(dossier_modeles, 'vectoriseur_tfidf_cosine.joblib'))
    joblib.dump(
        {'base_variantes': base_variantes, 'designations': {bv: [bv] for bv in base_variantes}},
        os.path.join(dossier_modeles, 'donnees_basevariante_cosine.joblib'),
    )

def main():
    print(f"Répertoire utilisateur temporaire : {REPERTOIRE_TEMPORAIRE}")
    print("Ce test n'entraîne aucun modèle ML : voir tests/full_test.py pour le test complet.\n")

    data_service = None
    code_sortie = 0
    try:
        test_imports()
        test_sources_propres()
        data_service = test_schema_produits()
        test_cycle_persistance(data_service)
        test_nettoyer_texte()
        test_maj_logiciel_structure()
        test_verifier_maj_comportement()
        test_telecharger_asset_comportement()
        test_scripts_updater_generation()

        etape(10, "Garde anti-entraînement")
        verifier(not ENTRAINEMENTS_DETECTES, "aucun entraînement de modèle n'a été déclenché")

        print("\nSmoke test terminé avec succès (aucun entraînement ML).")
    except AssertionError as erreur:
        print(f"\nÉCHEC : {erreur}")
        code_sortie = 1
    except Exception as erreur:
        print(f"\nERREUR : {type(erreur).__name__}: {erreur}")
        code_sortie = 1
    finally:
        if data_service is not None:
            data_service.fermer()
        shutil.rmtree(REPERTOIRE_TEMPORAIRE, ignore_errors=True)

    return code_sortie


if __name__ == "__main__":
    sys.exit(main())