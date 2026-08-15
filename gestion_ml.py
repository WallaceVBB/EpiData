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
                    chunks = pd.read_sql_query("SELECT designation, base_variante FROM entrainement", conn, chunksize=1000)
                    donnees = pd.concat(chunks, ignore_index=True)
                progression.update(tache_globale, advance=10)
                progression.update(tache_etape, advance=1)

                # Nettoyage des données
                console.print("Nettoyage des données...")
                donnees = donnees[donnees['base_variante'].map(donnees['base_variante'].value_counts()) >= 4]
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
                    'max_iter': 1000
                }

                # Modèle base_variante (Méthode 1: LinearSVC)
                console.print("[blue]Entraînement du modèle base_variante (LinearSVC)...")
                self.modele_basevariante = CalibratedClassifierCV(
                    LinearSVC(**svc_params),
                    cv=3
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

    def predire_avec_cosine_similarity(self, texte, vectoriseur_cosine=None, donnees_cosine=None):
        """
        Prédit la basevariante en utilisant TF-IDF avec similarité cosinus.
        Retourne le résultat et le score de confiance.
        """
        try:
            vectoriseur_cosine = vectoriseur_cosine if vectoriseur_cosine is not None else self.vectoriseur_tfidf_cosine
            donnees_cosine = donnees_cosine if donnees_cosine is not None else self.donnees_basevariante_cosine
            if vectoriseur_cosine is None or donnees_cosine is None:
                return None, 0.0

            tfidf_input = vectoriseur_cosine.transform([texte])

            # Vectoriser toutes les basevariantes de référence
            basevariantes = donnees_cosine['base_variantes'] # TODO: OPTIMISATION: sortir cette instance de ce boucle pour qu'il ne vectorise pas les basevariantes à chaque produit, mais seulement au début du traitement
            tfidf_reference = vectoriseur_cosine.transform(basevariantes)

            # Calculer la similarité cosinus
            similarites = cosine_similarity(tfidf_input, tfidf_reference)[0]

            # Obtenir l'index du meilleur résultat
            meilleur_index = int(np.argmax(similarites))
            score_confiance = float(similarites[meilleur_index])
            prediction = basevariantes[meilleur_index]

            return prediction, score_confiance
        except Exception as e:
            console.print(f"[yellow]Erreur dans la méthode cosine: {e}")
            return None, 0.0

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
        # Étape 1: Essayer Méthode 2 (TF-IDF Cosine)
        pred_cosine, proba_cosine = self.predire_avec_cosine_similarity(texte)

        # Étape 2: Si M2 >= 95%, l'utiliser directement
        if proba_cosine >= 0.95:
            return pred_cosine, proba_cosine, "TF-IDF_Cosine"

        if not self.modeles_svc_disponibles:
            return pred_cosine, proba_cosine, "TF-IDF_Cosine"

        # Étape 3: Essayer Méthode 1 (LinearSVC)
        pred_svc, proba_svc = self.predire_avec_svc(texte)

        # Étape 4: Si M1 >= 70%, l'utiliser directement
        if proba_svc >= 0.70:
            return pred_svc, proba_svc, "LinearSVC"

        # Étape 5: Si M1 < 70%, comparer les deux et prendre le meilleur
        if proba_cosine > proba_svc:
            return pred_cosine, proba_cosine, "TF-IDF_Cosine"
        return pred_svc, proba_svc, "LinearSVC"

    def predire_avec_svc(self, texte):
        """Prédit la basevariante avec le modèle LinearSVC calibré."""
        if not self.modeles_svc_disponibles:
            return None, 0.0

        vecteur = self.vectoriseur.transform([texte])
        prediction = self.modele_basevariante.predict(vecteur)[0]
        score_confiance = float(np.max(self.modele_basevariante.predict_proba(vecteur)))
        return prediction, score_confiance
