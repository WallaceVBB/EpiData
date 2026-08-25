"""
Script de triage semi-automatique des produits non révisés avant insertion
dans la base d'entraînement (bd_entrainement).

Le script produit 4 fichiers :
    - auto_accepter.csv
    - a_reviser_par_classe.csv
    - auto_rejeter.csv
    - echantillon_audit.csv

Usage :
    python triagem_produits_non_revises.py chemin/vers/predictions.csv chemin/vers/categories.csv

Le fichier categories.csv (colonnes basevariante, Produit, Variante, ...)
sert de référence pour distinguer deux types d'erreurs que la confiance et
l'accord entre méthodes ne détectent pas seuls :

  - "generalisation_evitable" : une catégorie STRICTEMENT plus spécifique
    existe déjà dans votre taxonomie et correspond mieux au texte du produit,
    mais le modèle a choisi la version générique à la place.
    Ex: si "Jambon cheddar" existait comme catégorie et que le texte "Jambon
    cheddar x4" a été classé "Cheddar", ce serait signalé. En revanche,
    "Cheddar" tout seul étant la SEULE catégorie existante pour ce produit
    (pas de variante plus fine dans categories.csv), ce n'est PAS signalé :
    la prédiction est déjà la meilleure option disponible par design.

  - "sur_specification" : la classe prédite contient un mot qui n'apparaît
    nulle part dans le texte du produit (ex: "protéine" -> "Protéine de
    soja" alors que "soja" n'est jamais mentionné). Ce signal est valable
    indépendamment de la granularité de la taxonomie -- c'est un mot inventé.

  - "tete_produit_manquante" : le texte contient un mot désignant le TYPE de
    produit (sauce, jambon, purée, tarte...) que la classe prédite a perdu
    au profit d'un simple mot-saveur/ingrédient.
    Ex: "Sauce au champagne" -> "Champagne" (une sauce n'est pas la boisson
    elle-même) ; "Jambon cheddar" -> "Cheddar" (c'est un jambon, pas un
    fromage) ; "Torta Mascarpone" -> "Mascarpone" (c'est un gâteau) ;
    "Purée de passion" -> "Fruit de la passion" (c'est une préparation, pas
    le fruit brut). Le TF-IDF/LinearSVC ne comprend pas la structure
    grammaticale : le mot le plus "statistiquement fort" du texte gagne,
    même si c'est le modificateur (saveur) plutôt que le type de produit.
    La liste MOTS_TETE_PRODUIT ci-dessous est un point de départ à enrichir
    au fil de vos révisions -- ajoutez-y les mots que vous repérez comme
    étant systématiquement "avalés" par une saveur/ingrédient.
"""

# ---------------------------------------------------------------------------
# Bibliothèques
# ---------------------------------------------------------------------------

import os
import sys

import numpy as np
import pandas as pd
from rich.console import Console
from sklearn.metrics.pairwise import cosine_similarity

# Permet d'importer les modules du projet
sys.path.insert(
    0,
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..")
    )
)

from utils import nettoyer_texte  # noqa: E402
from gestion_ml import GestionML  # noqa: E402


console = Console()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Nombre de produits traités simultanément.
#
# 2000 est un bon point de départ pour une machine avec peu de RAM.
#
# Si le traitement fonctionne bien et que vous avez suffisamment de RAM,
# vous pourrez tester 5000 ou 10000.
BATCH_SIZE = 2000


# Seuils pour auto-acceptation
SEUIL_AUTO_ACCEPTER_COSINE = 0.40
SEUIL_AUTO_ACCEPTER_SVC = 0.40
SEUIL_MARGE_MIN = 0.15


# Seuils pour auto-rejet
SEUIL_AUTO_REJETER_COSINE = 0.30
SEUIL_AUTO_REJETER_SVC = 0.30


# Taille de l'échantillon d'audit
TAILLE_ECHANTILLON_AUDIT = 600


# Mots vides français très courants à ignorer
MOTS_VIDES = {
    "de", "du", "des", "le", "la", "les", "un", "une", "et", "en", "au",
    "aux", "à", "a", "avec", "sans", "pour", "sur", "dans", "par", "ou",
    "boite", "boîte", "sachet", "étui", "pot", "flacon", "kg", "g", "l",
    "ml", "cl", "environ", "brut",
}


# Mots désignant un TYPE de produit (préparation/forme) plutôt qu'un
# ingrédient/saveur. Quand un de ces mots est présent dans le texte mais
# absent de la classe prédite, c'est un signal fort que le modèle a classé
# le produit par sa saveur plutôt que par son type réel
# (ex: "Sauce au champagne" classé "Champagne").
#
# Cette liste est volontairement courte au départ : enrichissez-la avec les
# mots que vous repérez pendant la révision de a_reviser_par_classe.csv.
MOTS_TETE_PRODUIT = {
    "jambon", "sauce", "purée", "puree", "tarte", "torta", "compote",
}


# ---------------------------------------------------------------------------
# Chargement des prédictions existantes
# ---------------------------------------------------------------------------

def charger_predictions(chemin_csv):
    """
    Charge le CSV exporté par le traitement hybride.

    Tolère :
        - séparateur virgule ou point-virgule ;
        - encodage UTF-8, UTF-8-SIG, CP1252 ou Latin-1 ;
        - nombres décimaux au format français.
    """

    encodages = ["utf-8-sig", "utf-8", "cp1252", "latin1"]
    separateurs = [",", ";"]

    df = None
    derniere_erreur = None

    for encoding in encodages:
        for sep in separateurs:
            try:
                df_test = pd.read_csv(chemin_csv, sep=sep, encoding=encoding)
                colonnes = {c.strip().lower() for c in df_test.columns}
                colonnes_attendues = {"texte_brut", "classification", "confiance", "modele"}

                if colonnes_attendues.issubset(colonnes):
                    df = df_test
                    console.print(f"[green]✓ CSV chargé : encoding={encoding}, séparateur='{sep}'")
                    break
            except (UnicodeDecodeError, pd.errors.ParserError) as e:
                derniere_erreur = e
                continue
        if df is not None:
            break

    if df is None:
        raise ValueError(
            "Impossible de lire le CSV avec les encodages et séparateurs "
            f"supportés. Dernière erreur : {derniere_erreur}"
        )

    df.columns = [c.strip().lower() for c in df.columns]
    colonnes_attendues = {"texte_brut", "classification", "confiance", "modele"}
    manquantes = colonnes_attendues - set(df.columns)
    if manquantes:
        console.print(f"[yellow]Colonnes trouvées : {set(df.columns)}")
        raise ValueError(f"Colonnes manquantes dans le CSV : {manquantes}")

    if df["confiance"].dtype == object:
        df["confiance"] = (
            df["confiance"].astype(str).str.replace(",", ".", regex=False).astype(float)
        )
    if df["confiance"].max() > 1.5:
        df["confiance"] = df["confiance"] / 100.0

    return df


def charger_categories(chemin_categories_csv):
    """Charge le référentiel de catégories (colonne basevariante) utilisé
    pour vérifier si une catégorie plus spécifique existe déjà dans la
    taxonomie avant de signaler une "généralisation" comme suspecte."""
    df_cat = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
        try:
            df_cat = pd.read_csv(chemin_categories_csv, encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    if df_cat is None:
        raise ValueError(f"Impossible de lire {chemin_categories_csv}")

    df_cat.columns = [c.strip() for c in df_cat.columns]
    if "basevariante" not in df_cat.columns:
        raise ValueError(
            f"Colonne 'basevariante' introuvable dans {chemin_categories_csv} "
            f"(colonnes trouvées : {list(df_cat.columns)})"
        )
    return df_cat["basevariante"].dropna().unique().tolist()


# ---------------------------------------------------------------------------
# Tokenisation
# ---------------------------------------------------------------------------

def _tokeniser(texte_nettoye):
    mots = texte_nettoye.split(" ")
    return {m for m in mots if len(m) >= 3 and m not in MOTS_VIDES}


def chevauchement_lexical(texte_nettoye, classe_nettoyee):
    """Retourne True si au moins un mot significatif de la classe apparaît
    dans le texte du produit."""
    mots_texte = _tokeniser(texte_nettoye)
    mots_classe = _tokeniser(classe_nettoyee)
    if not mots_classe:
        return False
    return len(mots_texte & mots_classe) > 0


def tete_produit_manquante(mots_texte, mots_classe):
    """Retourne les mots de MOTS_TETE_PRODUIT présents dans le texte mais
    absents de la classe prédite (ex: "sauce" dans "sauce au champagne" mais
    pas dans la classe "Champagne"). Un ensemble non vide signale que le
    modèle a probablement classé le produit par sa saveur/ingrédient plutôt
    que par son type réel."""
    return (mots_texte & MOTS_TETE_PRODUIT) - mots_classe


# ---------------------------------------------------------------------------
# Index de la taxonomie (categories.csv) pour détecter les catégories
# plus spécifiques disponibles mais non choisies
# ---------------------------------------------------------------------------

def construire_index_categories(basevariantes):
    """Construit un index inversé token -> ensemble d'indices de catégories,
    et la liste des ensembles de tokens par catégorie. Permet de retrouver
    rapidement si une catégorie strictement plus spécifique qu'une prédiction
    donnée existe dans la taxonomie."""
    noms = []
    tokens_par_categorie = []
    index_inverse = {}
    vus = set()

    for nom in basevariantes:
        if nom in vus:
            continue
        vus.add(nom)

        tokens = frozenset(_tokeniser(nettoyer_texte(nom)))
        idx = len(noms)
        noms.append(nom)
        tokens_par_categorie.append(tokens)

        for t in tokens:
            index_inverse.setdefault(t, set()).add(idx)

    return noms, tokens_par_categorie, index_inverse


def categorie_plus_specifique_disponible(pred_tokens, texte_tokens, index_categories):
    """Retourne le nom d'une catégorie de la taxonomie strictement plus
    spécifique que la classe prédite (contient tous ses mots + au moins un
    de plus) ET dont tous les mots apparaissent réellement dans le texte du
    produit. Retourne None si aucune telle catégorie n'existe -- dans ce
    cas, la classe prédite est déjà la plus fine option disponible, ce qui
    n'est PAS une erreur (ex: "Miel", "Cheddar", "Champagne" seuls dans la
    taxonomie, sans variante plus précise)."""
    noms, tokens_par_categorie, index_inverse = index_categories

    if not pred_tokens:
        return None

    listes = [index_inverse.get(t, set()) for t in pred_tokens]
    if any(len(l) == 0 for l in listes):
        return None

    candidats_idx = set.intersection(*listes) if listes else set()

    for idx in candidats_idx:
        tokens_cand = tokens_par_categorie[idx]
        if len(tokens_cand) > len(pred_tokens) and tokens_cand.issuperset(pred_tokens):
            if tokens_cand.issubset(texte_tokens):
                return noms[idx]

    return None


def diagnostic_specificite(texte_nettoye, classe_nettoyee, index_categories):
    """Retourne (diagnostic, categorie_alternative).

    diagnostic est "ok" ou une combinaison (séparée par "+") de :
      - "tete_produit_manquante" : mot de type de produit perdu (le signal
        le plus fiable, cf. MOTS_TETE_PRODUIT) ;
      - "sur_specification" : mot inventé dans la classe, absent du texte ;
      - "generalisation_evitable" : catégorie plus fine disponible dans la
        taxonomie mais non choisie.
    """
    mots_texte = _tokeniser(texte_nettoye)
    mots_classe = _tokeniser(classe_nettoyee)

    if not mots_classe or not mots_texte:
        return "ok", None

    drapeaux = []

    if tete_produit_manquante(mots_texte, mots_classe):
        drapeaux.append("tete_produit_manquante")

    if len(mots_classe - mots_texte) > 0:
        drapeaux.append("sur_specification")

    candidat = categorie_plus_specifique_disponible(mots_classe, mots_texte, index_categories)
    if candidat is not None:
        drapeaux.append("generalisation_evitable")

    if not drapeaux:
        return "ok", None
    return "+".join(drapeaux), candidat


# ---------------------------------------------------------------------------
# Prédiction TF-IDF Cosine (par lots, pour limiter la RAM)
# ---------------------------------------------------------------------------

def predire_cosine_avec_marge(gestion_ml, textes, batch_size=BATCH_SIZE):
    """Prédit avec TF-IDF + cosine similarity par lots pour limiter la RAM."""
    vectoriseur = gestion_ml.vectoriseur_tfidf_cosine
    donnees = gestion_ml.donnees_basevariante_cosine
    basevariantes, tfidf_reference = gestion_ml._obtenir_tfidf_reference(vectoriseur, donnees)

    predictions, confiances, marges = [], [], []
    total = len(textes)
    console.print(f"[cyan]TF-IDF Cosine : {total:,} lignes à traiter (batch={batch_size})")

    for debut in range(0, total, batch_size):
        fin = min(debut + batch_size, total)
        textes_batch = textes[debut:fin]

        tfidf_input = vectoriseur.transform(textes_batch)
        similarites = cosine_similarity(tfidf_input, tfidf_reference)

        idx_tries = np.argsort(-similarites, axis=1)
        top1_idx = idx_tries[:, 0]
        top2_idx = idx_tries[:, 1] if similarites.shape[1] > 1 else top1_idx

        conf_batch = similarites[np.arange(len(similarites)), top1_idx]
        conf_top2 = similarites[np.arange(len(similarites)), top2_idx]
        marge_batch = conf_batch - conf_top2
        pred_batch = [basevariantes[int(i)] for i in top1_idx]

        predictions.extend(pred_batch)
        confiances.extend(conf_batch.tolist())
        marges.extend(marge_batch.tolist())

        console.print(f"[cyan]  {fin:,}/{total:,} ({100 * fin / total:.1f}%)")
        del tfidf_input, similarites, idx_tries

    return predictions, confiances, marges


# ---------------------------------------------------------------------------
# Prédiction LinearSVC (par lots)
# ---------------------------------------------------------------------------

def predire_svc_avec_marge(gestion_ml, textes, batch_size=BATCH_SIZE):
    """Prédit avec LinearSVC calibré par lots pour limiter la RAM."""
    vectoriseur = gestion_ml.vectoriseur
    modele = gestion_ml.modele_basevariante
    classes = modele.classes_

    predictions, confiances, marges = [], [], []
    total = len(textes)
    console.print(f"[cyan]LinearSVC : {total:,} lignes à traiter (batch={batch_size})")

    for debut in range(0, total, batch_size):
        fin = min(debut + batch_size, total)
        textes_batch = textes[debut:fin]

        vecteurs = vectoriseur.transform(textes_batch)
        probabilites = modele.predict_proba(vecteurs)

        idx_tries = np.argsort(-probabilites, axis=1)
        top1_idx = idx_tries[:, 0]
        top2_idx = idx_tries[:, 1] if probabilites.shape[1] > 1 else top1_idx

        conf_batch = probabilites[np.arange(len(probabilites)), top1_idx]
        conf_top2 = probabilites[np.arange(len(probabilites)), top2_idx]
        marge_batch = conf_batch - conf_top2
        pred_batch = [classes[int(i)] for i in top1_idx]

        predictions.extend(pred_batch)
        confiances.extend(conf_batch.tolist())
        marges.extend(marge_batch.tolist())

        console.print(f"[cyan]  {fin:,}/{total:,} ({100 * fin / total:.1f}%)")
        del vecteurs, probabilites, idx_tries

    return predictions, confiances, marges


# ---------------------------------------------------------------------------
# Déduplication par texte nettoyé (les prédictions sont déterministes :
# inutile de recalculer pour "Miel Framboisier" et "miel framboisier")
# ---------------------------------------------------------------------------

def dedupliquer_par_texte_nettoye(df):
    df = df.copy()
    df["_texte_nettoye"] = df["texte_brut"].apply(nettoyer_texte)
    textes_uniques = df["_texte_nettoye"].drop_duplicates().reset_index(drop=True)
    df_uniques = pd.DataFrame({"_texte_nettoye": textes_uniques})
    taux_duplication = 1 - len(df_uniques) / len(df)
    console.print(
        f"[cyan]{len(df):,} lignes -> {len(df_uniques):,} textes uniques "
        f"({100*taux_duplication:.1f}% de doublons après nettoyage)."
    )
    return df, df_uniques


# ---------------------------------------------------------------------------
# Triage principal
# ---------------------------------------------------------------------------

def trier(df, gestion_ml, index_categories, batch_size=BATCH_SIZE):
    df, df_uniques = dedupliquer_par_texte_nettoye(df)
    textes_nettoyes = df_uniques["_texte_nettoye"].tolist()

    console.print("\n[bold cyan]=== TF-IDF Cosine ===")
    pred_cosine, conf_cosine, marge_cosine = predire_cosine_avec_marge(
        gestion_ml, textes_nettoyes, batch_size=batch_size
    )

    console.print("\n[bold cyan]=== LinearSVC ===")
    pred_svc, conf_svc, marge_svc = predire_svc_avec_marge(
        gestion_ml, textes_nettoyes, batch_size=batch_size
    )

    df_uniques["pred_cosine"] = pred_cosine
    df_uniques["conf_cosine"] = conf_cosine
    df_uniques["marge_cosine"] = marge_cosine
    df_uniques["pred_svc"] = pred_svc
    df_uniques["conf_svc"] = conf_svc
    df_uniques["marge_svc"] = marge_svc
    df_uniques["accord"] = df_uniques["pred_cosine"] == df_uniques["pred_svc"]

    console.print("\n[cyan]Calcul du chevauchement lexical et de la spécificité...")
    classes_nettoyees = df_uniques["pred_cosine"].apply(nettoyer_texte)
    df_uniques["overlap_lexical"] = [
        chevauchement_lexical(t, c) for t, c in zip(textes_nettoyes, classes_nettoyees)
    ]

    diagnostics = [
        diagnostic_specificite(t, c, index_categories)
        for t, c in zip(textes_nettoyes, classes_nettoyees)
    ]
    df_uniques["diagnostic_specificite"] = [d[0] for d in diagnostics]
    df_uniques["categorie_alternative"] = [d[1] for d in diagnostics]

    df = df.merge(df_uniques, on="_texte_nettoye", how="left")

    specificite_ok = df["diagnostic_specificite"] == "ok"

    condition_accepter = (
        df["accord"]
        & df["overlap_lexical"]
        & specificite_ok
        & (df["conf_cosine"] >= SEUIL_AUTO_ACCEPTER_COSINE)
        & (df["conf_svc"] >= SEUIL_AUTO_ACCEPTER_SVC)
        & (df["marge_cosine"] >= SEUIL_MARGE_MIN)
    )

    condition_rejeter = (
        ~df["overlap_lexical"]
        & (df["conf_cosine"] < SEUIL_AUTO_REJETER_COSINE)
        & (df["conf_svc"] < SEUIL_AUTO_REJETER_SVC)
    )

    df_accepter = df[condition_accepter].copy()
    df_rejeter = df[condition_rejeter & ~condition_accepter].copy()
    df_reviser = df[~condition_accepter & ~condition_rejeter].copy()

    console.print(
        f"[yellow]Dont détectés via categories.csv (généralisation évitable / "
        f"sur-spécification) : {(~specificite_ok).sum():,} lignes routées vers "
        "révision malgré confiance/accord OK."
    )

    return df_accepter, df_reviser, df_rejeter


def preparer_lot_revision(df_reviser):
    """Trie/groupe pour une révision humaine par blocs. L'ordre alphabétique
    du diagnostic place "generalisation_evitable" et "tete_produit_manquante"
    avant "sur_specification" et "ok" -- concrètement, "tete_produit_manquante"
    est le signal le plus fiable empiriquement (cf. "Sauce au champagne" ->
    "Champagne") : vérifiez ces lignes en premier."""
    colonnes = [
        "texte_brut", "pred_cosine", "conf_cosine", "pred_svc", "conf_svc",
        "accord", "overlap_lexical", "diagnostic_specificite", "categorie_alternative",
    ]
    return (
        df_reviser[colonnes]
        .sort_values(
            ["diagnostic_specificite", "pred_cosine", "conf_cosine"],
            ascending=[True, True, False],
        )
        .reset_index(drop=True)
    )


def creer_echantillon_audit(df_accepter, df_reviser, df_rejeter, taille):
    n_par_lot = taille // 3
    parts = []
    for nom, df_lot in [("auto_accepter", df_accepter), ("a_reviser", df_reviser), ("auto_rejeter", df_rejeter)]:
        if len(df_lot) == 0:
            continue
        n = min(n_par_lot, len(df_lot))
        echantillon = df_lot.sample(n=n, random_state=42).copy()
        echantillon["lot_origine"] = nom
        echantillon["correct_manuel"] = ""
        parts.append(echantillon)
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def main(chemin_csv_entree, chemin_categories_csv):
    console.print("[bold cyan]Chargement des modèles...")
    gestion_ml = GestionML()
    gestion_ml.charger_modeles()
    if not (gestion_ml.modeles_svc_disponibles and gestion_ml.modeles_cosine_disponibles):
        console.print("[bold red]Modèles introuvables -- vérifiez le dossier de modèles.")
        return

    console.print("[bold cyan]Chargement de la taxonomie (categories.csv)...")
    basevariantes = charger_categories(chemin_categories_csv)
    console.print(f"[cyan]{len(basevariantes):,} catégories de référence chargées.")
    index_categories = construire_index_categories(basevariantes)

    df = charger_predictions(chemin_csv_entree)
    df_accepter, df_reviser, df_rejeter = trier(
        df, gestion_ml, index_categories, batch_size=BATCH_SIZE
    )

    dossier_sortie = os.path.dirname(os.path.abspath(chemin_csv_entree))
    chemin_accepter = os.path.join(dossier_sortie, "auto_accepter.csv")
    chemin_reviser = os.path.join(dossier_sortie, "a_reviser_par_classe.csv")
    chemin_rejeter = os.path.join(dossier_sortie, "auto_rejeter.csv")
    chemin_audit = os.path.join(dossier_sortie, "echantillon_audit.csv")

    console.print("\n[cyan]Écriture des fichiers...")
    df_accepter.to_csv(chemin_accepter, index=False, encoding="utf-8-sig")
    preparer_lot_revision(df_reviser).to_csv(chemin_reviser, index=False, encoding="utf-8-sig")
    df_rejeter.to_csv(chemin_rejeter, index=False, encoding="utf-8-sig")

    echantillon_audit = creer_echantillon_audit(df_accepter, df_reviser, df_rejeter, TAILLE_ECHANTILLON_AUDIT)
    echantillon_audit.to_csv(chemin_audit, index=False, encoding="utf-8-sig")

    total = len(df)
    console.print("\n[bold green]Résultats du triage :")
    console.print(f"  auto_accepter        : {len(df_accepter):>7,} lignes ({100 * len(df_accepter) / total:.1f}%)")
    console.print(f"  a_reviser_par_classe : {len(df_reviser):>7,} lignes ({100 * len(df_reviser) / total:.1f}%)")
    console.print(f"  auto_rejeter          : {len(df_rejeter):>7,} lignes ({100 * len(df_rejeter) / total:.1f}%)")
    console.print(f"\n[bold cyan]Fichiers écrits dans : {dossier_sortie}")
    console.print(
        "\n[bold yellow]IMPORTANT : avant d'insérer 'auto_accepter.csv' dans bd_entrainement, "
        f"annotez la colonne 'correct_manuel' (oui/non) dans '{os.path.basename(chemin_audit)}' "
        "pour vérifier la précision réelle de chaque lot. Si la précision du lot "
        "auto_accepter est < ~95%, resserrez les seuils au début du script et relancez."
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        console.print(
            "[red]Usage : python triagem_produits_non_revises.py "
            "chemin/vers/predictions.csv chemin/vers/categories.csv"
        )
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])