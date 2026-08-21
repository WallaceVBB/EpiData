### Explications du fichier
# Ce fichier réalise la gestion des modèles de machine learning (création, chargement, remplacement et inférence).
# Il constitue la couche ML : elle est appelée par la couche de traitement (data_processing.py)
# et s'appuie sur la couche de persistance (services.py) pour la base d'entraînement.

## Variables
# bd_entrainement = base de données qui a des données utilisées pour l'entrainement des modèles (données des auteurs et utilisateurs)
# bd_pt = base de données avec tous les produits déjà traités par le logiciel

### bibliothèques
import os
import sqlite3

import joblib
import numpy as np
import pandas as pd
from rich.progress import Progress
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.svm import LinearSVC
from sklearn.model_selection import train_test_split
from sklearn.frozen import FrozenEstimator

from services import DataService
from utils import console, BD_ENTRAINEMENT, MODELES_DIR, nettoyer_texte


## Code
class GestionML:
    """Couche ML : chargement, création et utilisation des modèles de classification.

    La source de vérité du chemin de la base d'entraînement est `utils.BD_ENTRAINEMENT` ;
    un autre chemin peut être injecté (tests, environnements particuliers).
    """

    NOMS_MODELES = (
        "vectoriseur.joblib",
        "modele_basevariante.joblib",
        "vectoriseur_tfidf_cosine.joblib",
        "donnees_basevariante_cosine.joblib",
    )

    def __init__(self, bd_entrainement_path=None, modeles_dir=None, data_service=None):
        """Initialise la gestion ML sans déclencher d'entraînement ni d'accès disque lourd."""
        self.bd_entrainement_path = bd_entrainement_path or BD_ENTRAINEMENT
        self.modeles_dir = modeles_dir or MODELES_DIR
        self.data_service = data_service

        self.vectoriseur = None
        self.modele_basevariante = None
        self.vectoriseur_tfidf_cosine = None
        self.donnees_basevariante_cosine = None

        self._tfidf_reference_cache = None

    @staticmethod
    def nettoyer_texte(texte):
        """Nettoie et normalise le texte (implémentation unique dans utils.py)."""
        return nettoyer_texte(texte)

    def chemin_modele(self, nom_fichier):
        """Chemin absolu d'un fichier de modèle."""
        return os.path.join(self.modeles_dir, nom_fichier)

    @property
    def modeles_svc_disponibles(self):
        return self.vectoriseur is not None and self.modele_basevariante is not None

    @property
    def modeles_cosine_disponibles(self):
        return self.vectoriseur_tfidf_cosine is not None and self.donnees_basevariante_cosine is not None

    def charger_modeles(self):
        """Charge les modèles présents dans le dossier de modèles.
        Comportement tolérant en cas d'absence : les attributs restent à None."""
        self.vectoriseur, self.modele_basevariante = self._charger_paire(
            "vectoriseur.joblib", "modele_basevariante.joblib", "LinearSVC"
        )
        self.vectoriseur_tfidf_cosine, self.donnees_basevariante_cosine = self._charger_paire(
            "vectoriseur_tfidf_cosine.joblib", "donnees_basevariante_cosine.joblib", "TF-IDF Cosine"
        )

        if self.modeles_svc_disponibles:
            console.print("[bold green]✓ Modèles LinearSVC chargés avec succès")
        if self.modeles_cosine_disponibles:
            console.print("[bold green]✓ Modèles TF-IDF Cosine chargés avec succès")

    def _charger_paire(self, nom_premier, nom_second, libelle):
        chemin_premier = self.chemin_modele(nom_premier)
        chemin_second = self.chemin_modele(nom_second)
        if not (os.path.exists(chemin_premier) and os.path.exists(chemin_second)):
            return None, None
        try:
            return joblib.load(chemin_premier), joblib.load(chemin_second)
        except Exception as e:
            console.print(f"[yellow]Impossible de charger les modèles {libelle}: {e}")
            return None, None

    def _obtenir_data_service(self):
        """Retourne le service de persistance utilisé pour la base d'entraînement."""
        if self.data_service is None:
            self.data_service = DataService(bd_entrainement=self.bd_entrainement_path)
        return self.data_service

    def preparer_bd_entrainement(self):
        """Prépare la base d'entraînement via la couche de persistance."""
        data_service = self._obtenir_data_service()
        if not os.path.exists(self.bd_entrainement_path):
            console.print("[yellow]La base de données d'entrainement est introuvable, création d'une nouvelle base...")
            data_service.creer_bd_entrainement()
        data_service.maj_bd_entrainement()

    def recreer_modeles(self):
        """Supprime les modèles existants et crée de nouveaux modèles."""
        for fichier in self.NOMS_MODELES:
            chemin_fichier_modele = self.chemin_modele(fichier)
            if os.path.exists(chemin_fichier_modele):
                os.remove(chemin_fichier_modele)
        self.creer_modeles()

    def creer_modeles(self):
        """Crée (entraîne) les modèles de machine learning et les sauvegarde sur disque."""
        try:
            with Progress() as progression:
                tache_globale = progression.add_task("[cyan]Entraînement global...", total=100)
                tache_etape = progression.add_task("[magenta]Étape en cours...", total=100)

                self.preparer_bd_entrainement()

                with sqlite3.connect(self.bd_entrainement_path) as conn:
                    donnees = pd.read_sql_query("SELECT designation, base_variante FROM entrainement", conn)
                progression.update(tache_globale, advance=10)
                progression.update(tache_etape, advance=1)

                # Nettoyage des données
                console.print("Nettoyage des données...")
                donnees = donnees[donnees['base_variante'].map(donnees['base_variante'].value_counts()) >= 15]
                progression.update(tache_globale, advance=10)
                progression.update(tache_etape, advance=1)

                # Vectorialisation de bases variantes
                self.vectoriseur = TfidfVectorizer(max_features=3000, ngram_range=(1, 2), sublinear_tf=True, min_df=3)
                textes = donnees['designation'].apply(self.nettoyer_texte).tolist()
                X = self.vectoriseur.fit_transform(textes)
                progression.update(tache_globale, advance=20)
                progression.update(tache_etape, advance=1)

                # Configuration des modèles avec LinearSVC
                svc_params = {
                    'class_weight': 'balanced',
                    'max_iter': 1000,
                    'dual': False,
                }

                # Modèle base_variante (Méthode 1: LinearSVC)
                console.print("[blue]Entraînement du modèle base_variante (LinearSVC)...")
                self.modele_basevariante = CalibratedClassifierCV(
                    LinearSVC(**svc_params),
                    cv=3,
                    n_jobs=-1
                ).fit(X, donnees['base_variante'])
                progression.update(tache_globale, advance=20)
                progression.update(tache_etape, advance=1)

                # Méthode 2: TF-IDF avec Similarité Cosinus
                console.print("[blue]Entraînement du modèle TF-IDF Cosine...")
                self.vectoriseur_tfidf_cosine = TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 4))
                textes_propres = donnees['base_variante'].apply(self.nettoyer_texte).unique().tolist()
                self.vectoriseur_tfidf_cosine.fit(textes_propres)

                # Sauvegarder les données de référence pour la méthode cosine
                self.donnees_basevariante_cosine = {
                    'base_variantes': donnees['base_variante'].unique().tolist(),
                    'designations': donnees.groupby('base_variante')['designation'].apply(list).to_dict()
                }
                progression.update(tache_globale, advance=10)
                progression.update(tache_etape, advance=1)

                # Sauvegarde
                console.print("Sauvegarde des modèles...")
                os.makedirs(self.modeles_dir, exist_ok=True)
                joblib.dump(self.vectoriseur, self.chemin_modele('vectoriseur.joblib'), compress=3)
                joblib.dump(self.modele_basevariante, self.chemin_modele('modele_basevariante.joblib'), compress=3)
                joblib.dump(self.vectoriseur_tfidf_cosine, self.chemin_modele('vectoriseur_tfidf_cosine.joblib'), compress=3)
                joblib.dump(self.donnees_basevariante_cosine, self.chemin_modele('donnees_basevariante_cosine.joblib'), compress=3)
                progression.update(tache_globale, advance=10)
                progression.update(tache_etape, advance=1)

                console.print(f"[bold green]✓ Modèles LinearSVC et TF-IDF Cosine entraînés et sauvegardés dans {self.modeles_dir}")

        except Exception as e:
            console.print(f"[bold red]✗ Erreur lors de l'entraînement: {e}")
            raise

    def _obtenir_tfidf_reference(self, vectoriseur_cosine, donnees_cosine):
        """Retourne (basevariantes, tfidf_reference) pour la méthode cosine.

        La matrice TF-IDF des basevariantes de référence ne dépend que du
        vectoriseur et des données chargés, jamais du texte du produit en
        cours : on la calcule donc une seule fois puis on la réutilise pour
        tous les produits suivants, tant que le vectoriseur/les données n'ont
        pas changé.
        """
        cache = self._tfidf_reference_cache
        if cache is not None and cache[0] is vectoriseur_cosine and cache[1] is donnees_cosine:
            return cache[2], cache[3]

        basevariantes = donnees_cosine['base_variantes']
        tfidf_reference = vectoriseur_cosine.transform(basevariantes)
        self._tfidf_reference_cache = (vectoriseur_cosine, donnees_cosine, basevariantes, tfidf_reference)
        return basevariantes, tfidf_reference

    def predire_avec_cosine_similarity(self, texte, vectoriseur_cosine=None, donnees_cosine=None):
        """
        Prédit la basevariante en utilisant TF-IDF avec similarité cosinus.
        Retourne le résultat et le score de confiance.
        """
        return self.predire_avec_cosine_similarity_lot([texte], vectoriseur_cosine, donnees_cosine)[0]

    def predire_avec_cosine_similarity_lot(self, textes, vectoriseur_cosine=None, donnees_cosine=None):
        """Version par lot de `predire_avec_cosine_similarity`.

        Les textes sont vectorisés en une seule fois (`transform(liste)`) et la
        similarité cosinus est calculée sur toute la matrice, ce qui évite un
        appel scikit-learn par produit.
        Retourne une liste de tuples (prediction, score_confiance).
        """
        if not textes:
            return []
        try:
            vectoriseur_cosine = vectoriseur_cosine if vectoriseur_cosine is not None else self.vectoriseur_tfidf_cosine
            donnees_cosine = donnees_cosine if donnees_cosine is not None else self.donnees_basevariante_cosine
            if vectoriseur_cosine is None or donnees_cosine is None:
                return [(None, 0.0)] * len(textes)

            tfidf_input = vectoriseur_cosine.transform(textes)

            # Basevariantes de référence : vectorisées une seule fois puis mises en
            # cache (voir _obtenir_tfidf_reference), au lieu d'être revectorisées à chaque produit.
            basevariantes, tfidf_reference = self._obtenir_tfidf_reference(vectoriseur_cosine, donnees_cosine)

            # Calculer la similarité cosinus
            similarites = cosine_similarity(tfidf_input, tfidf_reference)

            # Obtenir l'index du meilleur résultat pour chaque texte
            meilleurs_index = np.argmax(similarites, axis=1)
            return [
                (basevariantes[int(index)], float(similarites[ligne, index]))
                for ligne, index in enumerate(meilleurs_index)
            ]
        except Exception as e:
            console.print(f"[yellow]Erreur dans la méthode cosine: {e}")
            return [(None, 0.0)] * len(textes)

    def predire_avec_methode_hybride(self, texte):
        """
        Prédit la basevariante en utilisant une approche hybride:
        1. Essaye la méthode 2 (TF-IDF Cosine) - plus légère et rapide
        2. Si accuracy >= 95%, l'utiliser directement
        3. Si accuracy < 95%, essaye la méthode 1 (LinearSVC)
        4. Si accuracy M1 >= 70%, l'utiliser
        5. Si accuracy M1 < 70%, comparer et retourner le meilleur

        Retourne: (prediction, score_confiance, methode_utilisee)
        """
        return self.predire_avec_methode_hybride_lot([texte])[0]

    def predire_avec_methode_hybride_lot(self, textes):
        """Version par lot de `predire_avec_methode_hybride`.

        La logique de décision est identique à la version unitaire ; seules les
        inférences sont regroupées : une passe cosine pour tous les textes, puis
        une passe LinearSVC pour les seuls textes dont le score cosine est
        inférieur à 0.95.
        Retourne une liste de tuples (prediction, score_confiance, methode_utilisee).
        """
        if not textes:
            return []

        # Étape 1: Essayer Méthode 2 (TF-IDF Cosine) pour tout le lot
        resultats_cosine = self.predire_avec_cosine_similarity_lot(textes)

        resultats = [None] * len(textes)
        index_svc = []
        for i, (pred_cosine, proba_cosine) in enumerate(resultats_cosine):
            # Étape 2: Si M2 >= 95%, l'utiliser directement (aucun appel LinearSVC)
            if proba_cosine >= 0.95 or not self.modeles_svc_disponibles:
                resultats[i] = self._decider_hybride(resultats_cosine[i], (None, 0.0))
            else:
                index_svc.append(i)

        if not index_svc:
            return resultats

        # Étapes 3 à 5: LinearSVC sur les seuls textes restants
        resultats_svc = self.predire_avec_svc_lot([textes[i] for i in index_svc])
        for i, resultat_svc in zip(index_svc, resultats_svc):
            resultats[i] = self._decider_hybride(resultats_cosine[i], resultat_svc)

        return resultats

    def _decider_hybride(self, resultat_cosine, resultat_svc):
        """Applique les règles de décision hybrides à des prédictions déjà calculées."""
        pred_cosine, proba_cosine = resultat_cosine

        # Étape 2: Si M2 >= 95%, l'utiliser directement
        if proba_cosine >= 0.95 or not self.modeles_svc_disponibles:
            return pred_cosine, proba_cosine, "TF-IDF_Cosine"

        pred_svc, proba_svc = resultat_svc

        # Étape 4: Si M1 >= 70%, l'utiliser directement
        if proba_svc >= 0.70:
            return pred_svc, proba_svc, "LinearSVC"

        # Étape 5: Si M1 < 70%, comparer les deux et prendre le meilleur
        if proba_cosine > proba_svc:
            return pred_cosine, proba_cosine, "TF-IDF_Cosine"
        return pred_svc, proba_svc, "LinearSVC"

    def predire_avec_svc(self, texte):
        """Prédit la basevariante avec le modèle LinearSVC calibré."""
        return self.predire_avec_svc_lot([texte])[0]

    def predire_avec_svc_lot(self, textes):
        """Version par lot de `predire_avec_svc` : une seule vectorisation et une
        seule inférence pour l'ensemble des textes."""
        if not textes:
            return []
        if not self.modeles_svc_disponibles:
            return [(None, 0.0)] * len(textes)

        vecteurs = self.vectoriseur.transform(textes)
        predictions = self.modele_basevariante.predict(vecteurs)
        probabilites = self.modele_basevariante.predict_proba(vecteurs)
        return [
            (predictions[i], float(np.max(probabilites[i])))
            for i in range(len(textes))
        ]