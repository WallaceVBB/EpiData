"""Smoke test du refactoring, SANS aucun entraînement de modèle ML.

Ce script vérifie que les couches (navigation → traitement → ML → persistance)
s'importent et fonctionnent, en utilisant un répertoire utilisateur temporaire et
des modèles `.joblib` factices. Toute tentative d'entraînement (`creer_modeles`,
`recreer_modeles`) ou d'appel à `classifier_produits` fait échouer le test.

Utilisation : python tests/smoke_small_test.py
"""

import os
import shutil
import sys
import tempfile

RACINE_PROJET = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE_PROJET not in sys.path:
    sys.path.insert(0, RACINE_PROJET)

# Répertoire utilisateur temporaire : aucune écriture dans le dépôt.
REPERTOIRE_TEMPORAIRE = tempfile.mkdtemp(prefix="epidata_smoke_")
os.environ["EPIDATA_USER_DIR"] = REPERTOIRE_TEMPORAIRE

import joblib  # noqa: E402
from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: E402

import data_processing  # noqa: E402
import gestion_ml  # noqa: E402
import services  # noqa: E402
import utils  # noqa: E402

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


def test_imports():
    print("1. Import des modules refactorés")
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
        "les extracteurs sont import\u00e9s normalement (sans importlib)",
    )
    verifier(
        not any(hasattr(services, nom) and callable(getattr(services, nom)) and not isinstance(getattr(services, nom), type)
                for nom in ("creer_bd_pt", "creer_bd_entrainement", "maj_bd_entrainement")),
        "services n'expose plus de wrappers de compatibilit\u00e9",
    )


def test_sources_propres():
    print("2. Absence de dépendances interdites dans les sources")
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
    print("3. Schéma de la table produits créé par DataService")
    bd_pt = os.path.join(REPERTOIRE_TEMPORAIRE, "bases_de_donnees", "bd_pt.db")
    data_service = services.DataService(bd_pt=bd_pt)
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
    print("4. Cycle de persistance via DataService")
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

    supprimes = data_service.supprimer_produits([produit])
    verifier(supprimes == 1, "supprimer_produits supprime le produit")
    verifier(
        data_service.obtenir_produit_par_code_produit('TEST-001') is None,
        "le produit n'est plus présent après suppression",
    )


def test_nettoyer_texte():
    print("5. Source unique de nettoyer_texte")
    texte = "  JUS d'Orange  BIO 1,5L!! "
    attendu = utils.nettoyer_texte(texte)
    verifier(gestion_ml.GestionML.nettoyer_texte(texte) == attendu, "GestionML.nettoyer_texte délègue à utils")
    verifier(attendu == "jus dorange bio 15l", "le nettoyage produit le résultat attendu")


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


def test_prediction_cosine(data_service):
    print("6. Prédiction cosinus avec des modèles factices")
    dossier_modeles = os.path.join(REPERTOIRE_TEMPORAIRE, "modeles_factices")
    creer_modeles_factices(dossier_modeles)

    ml = gestion_ml.GestionML(modeles_dir=dossier_modeles, data_service=data_service)
    ml.charger_modeles()
    verifier(ml.modeles_cosine_disponibles, "les modèles cosinus factices sont chargés")
    verifier(not ml.modeles_svc_disponibles, "aucun modèle LinearSVC n'est chargé (pas d'entraînement)")

    prediction, score = ml.predire_avec_cosine_similarity("TOMATES GRAPPE CAT1")
    verifier(prediction == "tomate grappe", f"la prédiction cosinus est correcte (obtenu: {prediction})")
    verifier(0.0 < score <= 1.0, "le score de confiance est dans [0, 1]")

    prediction, score, methode = ml.predire_avec_methode_hybride("TOMATES GRAPPE CAT1")
    verifier(methode == "TF-IDF_Cosine", "la méthode hybride retombe sur le cosinus sans modèle SVC")

    classificateur = data_processing.ClassificateurProduits(data_service=data_service, gestion_ml=ml)
    verifier(
        classificateur.predire_avec_methode_cosine("TOMATES GRAPPE CAT1")[0] == "tomate grappe",
        "ClassificateurProduits délègue la prédiction cosinus à la couche ML",
    )


def main():
    print(f"Répertoire utilisateur temporaire : {REPERTOIRE_TEMPORAIRE}")
    data_service = None
    try:
        test_imports()
        test_sources_propres()
        data_service = test_schema_produits()
        test_cycle_persistance(data_service)
        test_nettoyer_texte()
        test_prediction_cosine(data_service)

        print("7. Garde anti-entraînement")
        verifier(not ENTRAINEMENTS_DETECTES, "aucun entraînement de modèle n'a été déclenché")
    finally:
        if data_service is not None:
            data_service.fermer()
        shutil.rmtree(REPERTOIRE_TEMPORAIRE, ignore_errors=True)

    print("\nSmoke test terminé avec succès (aucun entraînement ML).")


if __name__ == "__main__":
    main()
