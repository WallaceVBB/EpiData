## Explication fichier :
# Ce fichier fait la gestion des services de l'application,
# incluant la connexion à la base de données et le chargement des CSV nécessaires pour le traitement des produits alimentaires.
# Il contient également les fonctions pour initialiser les bases de données et charger les modèles de machine learning.

## TODO's :
# Prévoir un module distinct pour le traitement des données et la mise à jour des données.

## Bibliothèques
import os
import sqlite3
import joblib
import pandas as pd
from types import SimpleNamespace

from utils import console, MODELES_DIR, PARAMETRES_DIR, BD_PT, BD_ENTRAINEMENT, ressource_path


class DataService:
    def __init__(self, app=None):
        self.app = app
        self.local = SimpleNamespace()
        self.conn = None
        self.vectoriseur = None
        self.modele_basevariante = None
        self.vectoriseur_tfidf_cosine = None
        self.donnees_basevariante_cosine = None
        self.dictionnaire_labels = {}
        self.dictionnaire_origines = {}
        self.dictionnaire_unites_poids = {}
        self.csv_fournisseurs = None
        self.traitement_appertises = pd.DataFrame()
        self.poids_moyen_fl = pd.DataFrame()

        self.creer_dossiers()

        try:
            self.conn = sqlite3.connect(BD_PT)
            self.initialiser_bd()
        except Exception as e:
            console.print(f"[red]Erreur: impossible de créer/ouvrir la base de données: {e}")
            self.conn = None

        try:
            self.charger_csvs()
        except Exception as e:
            console.print(f"[yellow]Avertissement lors du chargement des CSV: {e}")

        try:
            self.charger_modeles()
        except Exception as e:
            console.print(f"[yellow]Avertissement lors du chargement des modèles: {e}")

    def creer_dossiers(self):
        """Crée les dossiers nécessaires de l'application."""
        os.makedirs(MODELES_DIR, exist_ok=True)
        os.makedirs(PARAMETRES_DIR, exist_ok=True)
        os.makedirs(os.path.dirname(BD_PT), exist_ok=True)
        os.makedirs(os.path.dirname(BD_ENTRAINEMENT), exist_ok=True)

    def initialiser_bd(self):
        """Initialise la base de données des produits traités."""
        if self.conn is not None:
            self.creer_bd_pt(self.conn)

    def charger_csvs(self):
        """Charge les CSV de paramètres et crée des dictionnaires utiles.
        Tolérant si les fichiers sont absents (utile pour un premier démarrage de développement).
        """
        self.dictionnaire_labels = {}
        csv_labels = ressource_path(os.path.join("parametres", "labels.csv"))
        if os.path.exists(csv_labels):
            df = pd.read_csv(csv_labels)
            for _, row in df.iterrows():
                label = str(row.get('labels', '')).strip()
                if not label:
                    continue
                ecritures_label = [str(v).strip() for v in row[1:] if pd.notna(v) and str(v).strip()]
                self.dictionnaire_labels[label] = ecritures_label

        self.dictionnaire_origines = {}
        csv_origines = ressource_path(os.path.join("parametres", "origines.csv"))
        if os.path.exists(csv_origines):
            df = pd.read_csv(csv_origines)
            for _, row in df.iterrows():
                origine = str(row.get('origines', '')).strip()
                if not origine:
                    continue
                variantes = [str(v).strip() for v in row[1:] if pd.notna(v) and str(v).strip()]
                self.dictionnaire_origines[origine] = variantes

        self.dictionnaire_unites_poids = {}
        csv_unites_poids = ressource_path(os.path.join("parametres", "unites_poids.csv"))
        if os.path.exists(csv_unites_poids):
            df = pd.read_csv(csv_unites_poids)
            for _, row in df.iterrows():
                unite_poids = str(row.get('unites', '')).strip()
                if not unite_poids:
                    continue
                ecritures_unites_poids = [str(v).strip() for v in row[1:] if pd.notna(v) and str(v).strip()]
                self.dictionnaire_unites_poids[unite_poids] = ecritures_unites_poids

        self.csv_fournisseurs = None
        csv_fournisseurs = ressource_path(os.path.join("parametres", "fournisseurs.csv"))
        if os.path.exists(csv_fournisseurs):
            try:
                self.csv_fournisseurs = pd.read_csv(csv_fournisseurs)
            except Exception:
                self.csv_fournisseurs = None

        self.traitement_appertises = pd.DataFrame()
        csv_traitement = ressource_path(os.path.join("parametres", "traitement_appertises.csv"))
        if os.path.exists(csv_traitement):
            try:
                self.traitement_appertises = pd.read_csv(csv_traitement)
            except Exception:
                self.traitement_appertises = pd.DataFrame()

        self.poids_moyen_fl = pd.DataFrame()
        csv_poids_fl = ressource_path(os.path.join("parametres", "poids_moyen_fl.csv"))
        if os.path.exists(csv_poids_fl):
            try:
                self.poids_moyen_fl = pd.read_csv(csv_poids_fl)
            except Exception:
                self.poids_moyen_fl = pd.DataFrame()

    def creer_bd_pt(self, conn):
        """Crée les tables nécessaires dans la base de données de produits traités."""
        curseur = conn.cursor()
        curseur.execute('''CREATE TABLE IF NOT EXISTS produits (
                        id INTEGER PRIMARY KEY,
                        texte_brut TEXT,
                        texte_propre TEXT,
                        code_produit TEXT,
                        siret INTEGER,
                        fournisseur TEXT,
                        base_variante TEXT,
                        aliment TEXT,
                        variante TEXT,
                        conditionnement TEXT,
                        packaging TEXT,
                        unite_packaging TEXT,
                        origine TEXT,
                        poids_unitaire REAL,
                        poids_min REAL,
                        poids_max REAL,
                        unite_poids TEXT,
                        poids_total_kg REAL,
                        labels TEXT,
                        allergenes TEXT,
                        conservation TEXT,
                        unite_consommation TEXT,
                        tva TEXT,
                        confiance_basevariante REAL,
                        a_reviser BOOLEAN,
                        est_corrige BOOLEAN DEFAULT 0,
                        date_ajout TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        date_maj TIMESTAMP)''')
        conn.commit()

    def charger_modeles(self):
        """Charge des modèles si présents dans le dossier de modèles.
        Comportement tolérant en cas d'absence.
        """
        vectoriseur_path = os.path.join(MODELES_DIR, 'vectoriseur.joblib')
        modele_path = os.path.join(MODELES_DIR, 'modele_basevariante.joblib')
        vectoriseur_cosine_path = os.path.join(MODELES_DIR, 'vectoriseur_tfidf_cosine.joblib')
        donnees_cosine_path = os.path.join(MODELES_DIR, 'donnees_basevariante_cosine.joblib')

        if os.path.exists(vectoriseur_path) and os.path.exists(modele_path):
            try:
                self.vectoriseur = joblib.load(vectoriseur_path)
                self.modele_basevariante = joblib.load(modele_path)
            except Exception as e:
                console.print(f"[yellow]Impossible de charger les modèles LinearSVC: {e}")
                self.vectoriseur = None
                self.modele_basevariante = None
        else:
            self.vectoriseur = None
            self.modele_basevariante = None

        if os.path.exists(vectoriseur_cosine_path) and os.path.exists(donnees_cosine_path):
            try:
                self.vectoriseur_tfidf_cosine = joblib.load(vectoriseur_cosine_path)
                self.donnees_basevariante_cosine = joblib.load(donnees_cosine_path)
            except Exception as e:
                console.print(f"[yellow]Impossible de charger les modèles TF-IDF Cosine: {e}")
                self.vectoriseur_tfidf_cosine = None
                self.donnees_basevariante_cosine = None
        else:
            self.vectoriseur_tfidf_cosine = None
            self.donnees_basevariante_cosine = None

        if self.vectoriseur is not None and self.modele_basevariante is not None:
            console.print("[bold green]✓ Modèles LinearSVC chargés avec succès")
        if self.vectoriseur_tfidf_cosine is not None and self.donnees_basevariante_cosine is not None:
            console.print("[bold green]✓ Modèles TF-IDF Cosine chargés avec succès")

    def creer_bd_entrainement(self):
        """Crée une nouvelle base de données d'entraînement à partir du CSV pt_base.csv."""
        pt_base = ressource_path(os.path.join("donnees", "pt_base.csv"))
        if not os.path.exists(pt_base):
            raise FileNotFoundError(f"Le fichier {pt_base} n'existe pas")

        df = pd.read_csv(pt_base, dtype=str)
        if 'designation' not in df.columns or 'base_variante' not in df.columns:
            raise ValueError("Le CSV pt_base.csv doit contenir les colonnes 'designation' et 'base_variante'.")

        df = df[['designation', 'base_variante']].copy()
        df = df.dropna(subset=['designation', 'base_variante'])
        df['designation'] = df['designation'].astype(str).str.strip()
        df['base_variante'] = df['base_variante'].astype(str).str.strip()
        df = df[(df['designation'] != '') & (df['base_variante'] != '')]

        os.makedirs(os.path.dirname(BD_ENTRAINEMENT), exist_ok=True)
        with sqlite3.connect(BD_ENTRAINEMENT) as conn:
            df.to_sql('entrainement', conn, if_exists='replace', index=False)

        console.print(f"[green]Base d'entraînement créée avec succès : {BD_ENTRAINEMENT}")
        return True

    def maj_bd_entrainement(self):
        """Met à jour la base d'entraînement à partir de la base de produits traités."""
        if not os.path.exists(BD_ENTRAINEMENT):
            console.print("[yellow]Base d'entraînement introuvable, création à partir de pt_base.csv...[/yellow]")
            self.creer_bd_entrainement()

        if self.conn is None:
            console.print("[red]Connexion à la base de produits traités non disponible pour mettre à jour la base d'entraînement.")
            return False

        try:
            df_bd_pt = pd.read_sql("SELECT texte_brut AS designation, base_variante, confiance_basevariante, est_corrige FROM produits", self.conn)
        except Exception as e:
            console.print(f"[red]Impossible de lire la base de produits traités: {e}")
            return False

        if df_bd_pt.empty:
            console.print("[yellow]Aucun produit trouvé dans la base de produits traités. Mise à jour annulée.")
            return False

        if 'confiance_basevariante' not in df_bd_pt.columns or 'est_corrige' not in df_bd_pt.columns:
            console.print("[yellow]La table produits doit contenir les colonnes 'confiance_basevariante' et 'est_corrige'.")
            return False

        df_bd_pt['confiance_basevariante'] = pd.to_numeric(df_bd_pt['confiance_basevariante'], errors='coerce')
        if df_bd_pt['confiance_basevariante'].max(skipna=True) <= 1.0:
            df_bd_pt['confiance_basevariante'] = df_bd_pt['confiance_basevariante'] * 100.0

        df_bd_pt['est_corrige'] = df_bd_pt['est_corrige'].astype(bool)

        filtre_entrainement = (
            (df_bd_pt['est_corrige'] == True) |
            (df_bd_pt['confiance_basevariante'] >= 90)
        )
        df_selection = df_bd_pt.loc[filtre_entrainement, ['designation', 'base_variante']].copy()
        df_selection = df_selection.dropna(subset=['designation', 'base_variante'])
        df_selection['designation'] = df_selection['designation'].astype(str).str.strip()
        df_selection['base_variante'] = df_selection['base_variante'].astype(str).str.strip()
        df_selection = df_selection[(df_selection['designation'] != '') & (df_selection['base_variante'] != '')]

        if df_selection.empty:
            console.print("[yellow]Aucune ligne de formation pertinente trouvée dans bd_pt.")
            return False

        try:
            with sqlite3.connect(BD_ENTRAINEMENT) as conn:
                df_existant = pd.read_sql_query("SELECT designation, base_variante FROM entrainement", conn)
        except Exception:
            df_existant = pd.DataFrame(columns=['designation', 'base_variante'])

        df_combine = pd.concat([df_existant, df_selection], ignore_index=True)
        df_combine = df_combine.drop_duplicates(subset=['designation', 'base_variante']).reset_index(drop=True)

        with sqlite3.connect(BD_ENTRAINEMENT) as conn:
            df_combine.to_sql('entrainement', conn, if_exists='replace', index=False)

        console.print(f"[green]Base d'entraînement mise à jour avec {len(df_selection)} enregistrements issus de bd_pt. Total = {len(df_combine)}")
        return True

    def inserer_produits(self, df):
        """Insère des produits dans la base de données."""
        if self.conn is None:
            console.print("[red]Connexion à la base de données non disponible")
            return False

        try:
            df.to_sql('produits', self.conn, if_exists='append', index=False)
            self.conn.commit()
            return True
        except Exception as e:
            console.print(f"[red]Erreur lors de l'insertion des produits: {e}")
            return False

    def mettre_a_jour_produit(self, produit_id, donnees):
        """Met à jour les données d'un produit."""
        if self.conn is None:
            console.print("[red]Connexion à la base de données non disponible")
            return False

        try:
            curseur = self.conn.cursor()
            colonnes = list(donnees.keys())
            valeurs = list(donnees.values())

            set_clause = ", ".join([f"{col} = ?" for col in colonnes])
            query = f"UPDATE produits SET {set_clause} WHERE id = ?"

            curseur.execute(query, valeurs + [produit_id])
            self.conn.commit()
            return True
        except Exception as e:
            console.print(f"[red]Erreur lors de la mise à jour: {e}")
            return False

    def obtenir_produits(self):
        """Récupère tous les produits de la base de données."""
        if self.conn is None:
            return pd.DataFrame()

        try:
            df = pd.read_sql("SELECT * FROM produits", self.conn)
            return df
        except Exception as e:
            console.print(f"[red]Erreur lors de la récupération des produits: {e}")
            return pd.DataFrame()

    def obtenir_produits_a_reviser(self):
        """Récupère les produits marqués comme à réviser."""
        if self.conn is None:
            return pd.DataFrame()

        try:
            df = pd.read_sql("SELECT * FROM produits WHERE a_reviser = 1 OR est_corrige = 0", self.conn)
            return df
        except Exception as e:
            console.print(f"[red]Erreur lors de la récupération des produits à réviser: {e}")
            return pd.DataFrame()

    def obtenir_produit_par_id(self, produit_id):
        """Récupère un produit spécifique par son ID."""
        if self.conn is None:
            return None

        try:
            df = pd.read_sql("SELECT * FROM produits WHERE id = ?", self.conn, params=[produit_id])
            if not df.empty:
                return df.iloc[0].to_dict()
            return None
        except Exception as e:
            console.print(f"[red]Erreur lors de la récupération du produit: {e}")
            return None


# Compatibilité avec l'ancien code qui importait des fonctions globales.
def creer_bd_pt(service, conn):
    return DataService.creer_bd_pt(service, conn)


def creer_bd_entrainement(service):
    return DataService.creer_bd_entrainement(service)


def maj_bd_entrainement(service):
    return DataService.maj_bd_entrainement(service)
