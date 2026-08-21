"""Test complet du pipeline EpiData.

À l'inverse de `tests/smoke_smalltest.py` (rapide, sans entraînement), ce script exerce la
chaîne complète : base d'entraînement → entraînement réel des modèles
(`TfidfVectorizer` + `CalibratedClassifierCV(LinearSVC)`) → inférence → classification
d'un CSV → persistance → mise à jour de la base d'entraînement.

L'entraînement est coûteux (plusieurs minutes et plusieurs Go de RAM selon la taille de
`donnees/pt_base.csv`) : à lancer manuellement, jamais dans une boucle de développement.

Par défaut, tout est écrit dans un répertoire temporaire (`EPIDATA_USER_DIR`), donc ni
les modèles ni les bases du dépôt ne sont modifiés.

Exemples :
    python tests/full_test.py
    python tests/full_test.py --csv mon_fichier.csv --lignes 200
    python tests/full_test.py --user-dir ~/epidata_test --garder
    python tests/full_test.py --recreer          # force la reconstruction des modèles
"""

import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
import time

RACINE_PROJET = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE_PROJET not in sys.path:
    sys.path.insert(0, RACINE_PROJET)


def analyser_arguments():
    analyseur = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    analyseur.add_argument(
        "--user-dir",
        default=None,
        help="Répertoire de données à utiliser (par défaut : un répertoire temporaire supprimé à la fin).",
    )
    analyseur.add_argument(
        "--csv",
        default=None,
        help="CSV à classifier (colonne 'designation' obligatoire). Par défaut : un CSV généré depuis donnees/pt_base.csv.",
    )
    analyseur.add_argument(
        "--lignes",
        type=int,
        default=50,
        help="Nombre de désignations du CSV généré automatiquement (défaut : 50).",
    )
    analyseur.add_argument(
        "--recreer",
        action="store_true",
        help="Utilise recreer_modeles() (supprime les .joblib existants) au lieu de creer_modeles().",
    )
    analyseur.add_argument(
        "--sans-ml",
        action="store_true",
        help="N'exécute que les étapes qui ne nécessitent aucun entraînement (export CSV, pagination).",
    )
    analyseur.add_argument(
        "--garder",
        action="store_true",
        help="Conserve le répertoire de données à la fin (implicite avec --user-dir).",
    )
    return analyseur.parse_args()


ARGUMENTS = analyser_arguments()

# Le répertoire de données doit être choisi AVANT l'import des modules de l'application :
# utils.py résout tous les chemins à l'import.
REPERTOIRE_TEMPORAIRE = None
if ARGUMENTS.user_dir:
    REPERTOIRE_DONNEES = os.path.abspath(os.path.expanduser(ARGUMENTS.user_dir))
    os.makedirs(REPERTOIRE_DONNEES, exist_ok=True)
else:
    REPERTOIRE_TEMPORAIRE = tempfile.mkdtemp(prefix="epidata_full_")
    REPERTOIRE_DONNEES = REPERTOIRE_TEMPORAIRE
os.environ["EPIDATA_USER_DIR"] = REPERTOIRE_DONNEES

import pandas as pd  # noqa: E402

import utils  # noqa: E402
from data_processing import ClassificateurProduits  # noqa: E402
from gestion_ml import GestionML  # noqa: E402
from services import DataService  # noqa: E402

DESIGNATIONS_SECOURS = [
    "TOMATE GRAPPE FRANCE CAT1 5KG",
    "YAOURT NATURE BIO 4X125G",
    "PAIN COMPLET TRANCHE 500G",
    "FILET DE POULET FRAIS 2KG",
    "HARICOTS VERTS EXTRA FINS BOITE 4/4",
]


def verifier(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"  ok - {message}")


def etape(numero, titre):
    print(f"\n{numero}. {titre}")


def preparer_csv_entree():
    """Retourne le chemin du CSV à classifier, en le générant si nécessaire."""
    if ARGUMENTS.csv:
        chemin = os.path.abspath(os.path.expanduser(ARGUMENTS.csv))
        verifier(os.path.exists(chemin), f"le CSV fourni existe : {chemin}")
        return chemin

    pt_base = utils.ressource_path(os.path.join("donnees", "pt_base.csv"))
    verifier(os.path.exists(pt_base), "donnees/pt_base.csv est disponible pour générer un CSV de test")

    df = pd.read_csv(pt_base, dtype=str).dropna(subset=["designation"])
    designations = df["designation"].head(ARGUMENTS.lignes).tolist() or DESIGNATIONS_SECOURS

    chemin = os.path.join(REPERTOIRE_DONNEES, "csv_de_test.csv")
    pd.DataFrame({
        "designation": designations,
        "code_produit": [f"TEST-{index:05d}" for index in range(len(designations))],
    }).to_csv(chemin, index=False)
    verifier(True, f"CSV de test généré ({len(designations)} lignes) : {chemin}")
    return chemin


def etape_base_donnees():
    etape(1, "Initialisation de la persistance")
    data_service = DataService()
    verifier(data_service.conn is not None, f"base de produits ouverte : {data_service.bd_pt}")

    curseur = data_service.conn.cursor()
    curseur.execute("PRAGMA table_info(produits)")
    colonnes = [ligne[1] for ligne in curseur.fetchall()]
    verifier("methode_prediction" in colonnes, "la table produits contient methode_prediction")
    return data_service


def etape_base_entrainement(gestion_ml):
    etape(2, "Préparation de la base d'entraînement")
    gestion_ml.preparer_bd_entrainement()
    verifier(os.path.exists(gestion_ml.bd_entrainement_path), f"base d'entraînement présente : {gestion_ml.bd_entrainement_path}")

    with sqlite3.connect(gestion_ml.bd_entrainement_path) as conn:
        nombre_lignes = conn.execute("SELECT COUNT(*) FROM entrainement").fetchone()[0]
        nombre_classes = conn.execute("SELECT COUNT(DISTINCT base_variante) FROM entrainement").fetchone()[0]
    verifier(nombre_lignes > 0, f"la base d'entraînement contient {nombre_lignes} lignes")
    verifier(nombre_classes > 1, f"la base d'entraînement contient {nombre_classes} base_variantes distinctes")


def etape_entrainement(gestion_ml):
    etape(3, "Entraînement réel des modèles (opération longue)")
    debut = time.time()
    if ARGUMENTS.recreer:
        gestion_ml.recreer_modeles()
    else:
        gestion_ml.creer_modeles()
    duree = time.time() - debut
    print(f"  entraînement terminé en {duree:.1f}s")

    for nom in GestionML.NOMS_MODELES:
        chemin = gestion_ml.chemin_modele(nom)
        verifier(os.path.exists(chemin), f"{nom} écrit ({os.path.getsize(chemin) / 1024:.0f} Ko)")


def etape_inference(gestion_ml):
    etape(4, "Inférence avec les modèles fraîchement entraînés")
    gestion_ml.vectoriseur = None
    gestion_ml.modele_basevariante = None
    gestion_ml.vectoriseur_tfidf_cosine = None
    gestion_ml.donnees_basevariante_cosine = None
    gestion_ml.charger_modeles()
    verifier(gestion_ml.modeles_svc_disponibles, "les modèles LinearSVC se rechargent depuis le disque")
    verifier(gestion_ml.modeles_cosine_disponibles, "les modèles TF-IDF Cosine se rechargent depuis le disque")

    texte = DESIGNATIONS_SECOURS[0]
    prediction_svc, score_svc = gestion_ml.predire_avec_svc(texte)
    verifier(prediction_svc is not None and 0.0 <= score_svc <= 1.0, f"prédiction LinearSVC : {prediction_svc} ({score_svc:.2%})")

    prediction_cosine, score_cosine = gestion_ml.predire_avec_cosine_similarity(texte)
    verifier(prediction_cosine is not None and 0.0 <= score_cosine <= 1.0, f"prédiction cosinus : {prediction_cosine} ({score_cosine:.2%})")

    prediction, score, methode = gestion_ml.predire_avec_methode_hybride(texte)
    verifier(methode in ("LinearSVC", "TF-IDF_Cosine"), f"prédiction hybride : {prediction} ({score:.2%}) via {methode}")


def etape_classification(data_service, gestion_ml, chemin_csv):
    etape(5, "Classification d'un CSV de bout en bout")
    classificateur = ClassificateurProduits(data_service=data_service, gestion_ml=gestion_ml)

    messages = []
    resultats = classificateur.classifier_produits(
        chemin_csv,
        progress_callback=lambda progression, message: messages.append((progression, message)),
    )
    verifier(isinstance(resultats, pd.DataFrame) and not resultats.empty, f"{len(resultats)} produits classifiés")
    verifier(bool(messages) and messages[-1][0] == 100, "le callback de progression atteint 100%")

    colonnes_attendues = {'base_variante', 'confiance_basevariante', 'methode_prediction', 'a_reviser'}
    verifier(colonnes_attendues.issubset(resultats.columns), "les colonnes attendues sont présentes dans le résultat")
    verifier(resultats['id'].notna().all(), "chaque produit classifié a un identifiant en base")

    a_reviser = int(resultats['a_reviser'].sum())
    print(f"  info - {a_reviser}/{len(resultats)} produits marqués à réviser (confiance < 70%)")
    print(f"  info - méthodes utilisées : {resultats['methode_prediction'].value_counts().to_dict()}")
    return resultats


def etape_persistance(data_service, resultats):
    etape(6, "Persistance et réutilisation de la base de connaissance")
    premier = resultats.iloc[0]
    en_base = data_service.obtenir_produit_par_texte_brut(premier['texte_brut'])
    verifier(en_base is not None, "le premier produit classifié est bien en base")
    verifier(en_base['base_variante'] == premier['base_variante'], "la base_variante persistée correspond au résultat")
    verifier(en_base['methode_prediction'] == premier['methode_prediction'], "la methode_prediction est persistée")

    produits_en_base = data_service.obtenir_produits()
    verifier(len(produits_en_base) == len(resultats), f"{len(produits_en_base)} produits en base après le premier passage")


def etape_second_passage(data_service, gestion_ml, chemin_csv, resultats):
    etape(7, "Second passage : les produits connus ne sont pas re-classifiés")
    classificateur = ClassificateurProduits(data_service=data_service, gestion_ml=gestion_ml)
    debut = time.time()
    resultats_bis = classificateur.classifier_produits(chemin_csv)
    duree = time.time() - debut
    print(f"  second passage en {duree:.1f}s")

    verifier(len(resultats_bis) == len(resultats), "le second passage retourne le même nombre de lignes")
    verifier(len(data_service.obtenir_produits()) == len(resultats), "aucun doublon n'est inséré en base")


def etape_export_csv(data_service):
    etape(9, "Export CSV par lots de la base de produits traités")
    produits = [
        {
            'texte_brut': f"PRODUIT EXPORT {index}",
            'texte_propre': f"produit export {index}",
            'code_produit': f"EXPORT-{index:05d}",
            'base_variante': 'tomate grappe',
            'confiance_basevariante': 90.0,
            'methode_prediction': 'TF-IDF_Cosine',
            'a_reviser': False,
            'est_corrige': False,
        }
        for index in range(25)
    ]
    for produit in produits:
        data_service.inserer_produit(produit)
    data_service.valider()

    nombre_en_base = len(data_service.obtenir_produits())
    chemin_csv = os.path.join(REPERTOIRE_DONNEES, "export_bd_pt.csv")

    progressions = []
    resultat = data_service.exporter_bd_pt_csv(
        chemin_csv,
        chunksize=10,
        progress_callback=lambda pourcentage, message: progressions.append((pourcentage, message)),
    )
    verifier(resultat is True, "exporter_bd_pt_csv retourne True")
    verifier(os.path.exists(chemin_csv), f"le fichier CSV est créé : {chemin_csv}")

    df_export = pd.read_csv(chemin_csv)
    verifier(len(df_export) == nombre_en_base, f"le CSV contient {len(df_export)} lignes (= produits en base)")
    verifier('code_produit' in df_export.columns and 'base_variante' in df_export.columns, "l'en-tête du CSV est présent")
    verifier(bool(progressions) and progressions[-1][0] == 100, "le callback de progression atteint 100%")


def etape_pagination():
    etape(10, "Pagination du tableau de résultats")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtUiTools import QUiLoader
    from PySide6.QtWidgets import QApplication

    from navigation.n_traitement import TAILLE_PAGE_RESULTATS, TraitementNavigation

    application = QApplication.instance() or QApplication([])
    chemin_ui = utils.ressource_path(os.path.join("gui", "Traitement_resultats.ui"))
    page = QUiLoader().load(chemin_ui)
    verifier(page is not None, "la page Traitement_resultats.ui se charge")
    for nom in ("b_Page_Precedente", "b_Page_Suivante", "label_Pagination"):
        verifier(hasattr(page, nom), f"le .ui expose le widget de pagination {nom}")

    nombre_lignes = TAILLE_PAGE_RESULTATS + 500
    df = pd.DataFrame({
        'id': range(1, nombre_lignes + 1),
        'code_produit': [f"PAGE-{index:06d}" for index in range(nombre_lignes)],
        'texte_brut': [f"PRODUIT {index}" for index in range(nombre_lignes)],
        'base_variante': ['tomate grappe'] * nombre_lignes,
        'est_corrige': [False] * nombre_lignes,
    })

    pages = {'traitement_resultats': page}
    navigation = TraitementNavigation(page, lambda _nom: None, pages)
    navigation.current_results_df = df
    navigation._populate_results_table(df)

    verifier(navigation._nb_pages == 2, f"_nb_pages vaut {navigation._nb_pages} pour {nombre_lignes} lignes")
    verifier(
        navigation._results_model.rowCount() == TAILLE_PAGE_RESULTATS,
        f"le modèle source ne contient que {TAILLE_PAGE_RESULTATS} lignes",
    )
    verifier(len(navigation._produits_id_map) == TAILLE_PAGE_RESULTATS, "la carte des produits ne couvre que la page")
    verifier(navigation._produits_id_map[0]['id'] == 1, "la première ligne de la page 1 correspond au premier produit")
    verifier(not page.b_Page_Precedente.isEnabled() and page.b_Page_Suivante.isEnabled(), "boutons cohérents sur la page 1")

    navigation.on_page_suivante()
    verifier(navigation._page_courante == 1, "on_page_suivante passe à la page 2")
    verifier(navigation._results_model.rowCount() == 500, "la dernière page ne contient que les lignes restantes")
    verifier(set(navigation._produits_id_map) == set(range(500)), "les clés de la carte sont les indices locaux de la page")
    verifier(
        navigation._produits_id_map[0]['id'] == TAILLE_PAGE_RESULTATS + 1,
        "la première ligne de la page 2 correspond au produit global suivant",
    )
    verifier(page.b_Page_Precedente.isEnabled() and not page.b_Page_Suivante.isEnabled(), "boutons cohérents sur la dernière page")

    # Édition sur la page 2 : l'index global doit viser la bonne ligne du DataFrame complet.
    index_global = navigation._page_courante * TAILLE_PAGE_RESULTATS + 10
    verifier(
        df.iloc[index_global]['code_produit'] == navigation._produits_id_map[10]['original_data']['code_produit'],
        "l'index global d'édition pointe sur la ligne éditée du DataFrame complet",
    )

    navigation.on_page_precedente()
    verifier(navigation._page_courante == 0, "on_page_precedente revient à la page 1")

    del navigation
    page.deleteLater()


def etape_maj_entrainement(data_service):
    etape(8, "Mise à jour de la base d'entraînement depuis les produits traités")
    resultat = data_service.maj_bd_entrainement()
    print(f"  info - maj_bd_entrainement a retourné {resultat} (False si aucun produit ne dépasse le seuil de confiance)")


def main():
    print(f"Répertoire de données : {REPERTOIRE_DONNEES}")
    print("ATTENTION : ce test entraîne réellement les modèles ML, cela peut prendre plusieurs minutes.\n")

    data_service = None
    code_sortie = 0
    try:
        chemin_csv = None if ARGUMENTS.sans_ml else preparer_csv_entree()
        data_service = etape_base_donnees()
        gestion_ml = GestionML(data_service=data_service)

        if not ARGUMENTS.sans_ml:
            etape_base_entrainement(gestion_ml)
            etape_entrainement(gestion_ml)
            etape_inference(gestion_ml)
            resultats = etape_classification(data_service, gestion_ml, chemin_csv)
            etape_persistance(data_service, resultats)
            etape_second_passage(data_service, gestion_ml, chemin_csv, resultats)
            etape_maj_entrainement(data_service)
        else:
            print("\n(--sans-ml : étapes 2 à 8 ignorées)")

        etape_export_csv(data_service)
        etape_pagination()

        print("\nTest complet terminé avec succès.")
    except AssertionError as erreur:
        print(f"\nÉCHEC : {erreur}")
        code_sortie = 1
    except Exception as erreur:
        print(f"\nERREUR : {type(erreur).__name__}: {erreur}")
        code_sortie = 1
    finally:
        if data_service is not None:
            data_service.fermer()
        if REPERTOIRE_TEMPORAIRE and not ARGUMENTS.garder:
            shutil.rmtree(REPERTOIRE_TEMPORAIRE, ignore_errors=True)
        else:
            print(f"Artefacts conservés dans : {REPERTOIRE_DONNEES}")

    return code_sortie


if __name__ == "__main__":
    sys.exit(main())
