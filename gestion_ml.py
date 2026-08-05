### Explications du fichier
# ce fichier réalise la gestion des modèles de machine learning (création, suppression et remplacement)

## Varibles
# bd_entrainement = base de données qui a des données utilisées pour l'entrainement des modèles (données des auteurs (csv "baseet utilisateurs)
# bd_pt = base de données avec tous les produits déjà traités par le logiciel

## TODO's:


### bibliothèques
import os
import sqlite3
import joblib
import pandas as pd
import re
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.calibration import CalibratedClassifierCV
from sklearn.svm import LinearSVC
from sklearn.metrics.pairwise import cosine_similarity
from rich.progress import Progress
from utils import console, MODELES_DIR, PARAMETRES_DIR, bd_entrainement, bd_pt, ressource_path


## Code

class GestionML:
    """Gestion des modèles de machine learning"""
    
    def __init__(self, bd_entrainement_path):
        """Initialise la gestion ML"""
        self.bd_entrainement = bd_entrainement_path
        if not os.path.exists(bd_entrainement_path):
            console.print("[yellow]La base de données d'entrainement est introuvable, création d'une nouvelle base...[/yellow]")
            self.creer_bd_entrainement()
        self.maj_bd_entrainement()

    def recreer_modeles(self):
        """Supprime les modèles existants et crée de nouveaux modèles."""
        for fichier in [
            "vectoriseur.joblib",
            "modele_basevariante.joblib",
            "vectoriseur_tfidf_cosine.joblib",
            "donnees_basevariante_cosine.joblib"
        ]:
            chemin_fichiers_modeles = os.path.join(MODELES_DIR, fichier)
            if os.path.exists(chemin_fichiers_modeles):
                os.remove(chemin_fichiers_modeles)
        self.creer_modeles()

    def creer_modeles(self):
        """Crée les modèles de machine learning"""
        try:
            with Progress() as progression:
                tache_globale = progression.add_task("[cyan]Entraînement global...", total=100)
                tache_etape = progression.add_task("[magenta]Étape en cours...", total=100)

                bd_entrainement_path = ressource_path("bases_de_donnees/bd_entrainement.db")
                if not os.path.exists(bd_entrainement_path):
                    console.print("[red]La base de données d'entrainement est introuvable ![/red]")
                    return
                    
                chunks = pd.read_csv(bd_entrainement_path, chunksize=1000)
                donnees = pd.concat(chunks)
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
                joblib.dump(self.vectoriseur, os.path.join(MODELES_DIR, 'vectoriseur.joblib'), compress=3)
                joblib.dump(self.modele_basevariante, os.path.join(MODELES_DIR, 'modele_basevariante.joblib'),
                            compress=3)
                joblib.dump(self.vectoriseur_tfidf_cosine, os.path.join(MODELES_DIR, 'vectoriseur_tfidf_cosine.joblib'), compress=3)
                joblib.dump(self.donnees_basevariante_cosine, os.path.join(MODELES_DIR, 'donnees_basevariante_cosine.joblib'), compress=3)
                progression.update(tache_globale, advance=10)
                progression.update(tache_etape, advance=1)

                console.print(f"[bold green]✓ Modèles LinearSVC et TF-IDF Cosine entraînés et sauvegardés dans {MODELES_DIR}")

        except Exception as e:
            console.print(f"[bold red]✗ Erreur lors de l'entraînement: {e}")
            raise

    def nettoyer_texte(self, texte):
        """Nettoie et normalise le texte"""
        texte = str(texte).lower()
        texte = re.sub(r'[^\w\s-]', '', texte)
        texte = re.sub(r'\s+', ' ', texte).strip()
        return texte

    def predire_avec_cosine_similarity(self, texte, vectoriseur_cosine=None, donnees_cosine=None):
        """
        Prédit la basevariante en utilisant TF-IDF avec similarité cosinus.
        Retourne le résultat et le score de confiance.
        """
        try:
            if vectoriseur_cosine is None or donnees_cosine is None:
                vectoriseur_cosine = joblib.load(os.path.join(MODELES_DIR, 'vectoriseur_tfidf_cosine.joblib'))
                donnees_cosine = joblib.load(os.path.join(MODELES_DIR, 'donnees_basevariante_cosine.joblib'))
            
            texte_propre = self.nettoyer_texte(texte)
            tfidf_input = vectoriseur_cosine.transform([texte_propre])
            
            # Vectoriser toutes les basevariantes de référence
            basevariantes = donnees_cosine['base_variantes']
            tfidf_reference = vectoriseur_cosine.transform(basevariantes)
            
            # Calculer la similarité cosinus
            similarites = cosine_similarity(tfidf_input, tfidf_reference)[0]
            
            # Obtenir l'index du meilleur résultat
            meilleur_index = np.argmax(similarites)
            score_confiance = similarites[meilleur_index]
            prediction = basevariantes[meilleur_index]
            
            return prediction, score_confiance
        except Exception as e:
            console.print(f"[yellow]Erreur dans la méthode cosine: {e}[/yellow]")
            return None, 0.0
