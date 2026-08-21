## Explication fichier :
# Ce fichier fait la gestion des services de l'application,
# incluant la connexion à la base de données et le chargement des CSV nécessaires pour le traitement des produits alimentaires.
# Il contient également les fonctions pour initialiser les bases de données et charger les modèles de machine learning.

## Bibliothèques
import os
import sqlite3
import pandas as pd
from types import SimpleNamespace

from utils import console, MODELES_DIR, PARAMETRES_DIR, BD_PT, BD_ENTRAINEMENT, ressource_path

# Colonnes de la table produits, dans l'ordre du schéma défini par creer_bd_pt.
COLONNES_PRODUITS = [
    'texte_brut', 'texte_propre', 'code_produit', 'siret', 'fournisseur',
    'base_variante', 'aliment', 'variante', 'conditionnement', 'packaging',
    'unite_packaging', 'origine', 'poids_unitaire', 'poids_min', 'poids_max',
    'unite_poids', 'poids_total_kg', 'labels', 'allergenes', 'conservation',
    'unite_consommation', 'tva', 'confiance_basevariante', 'methode_prediction',
    'a_reviser', 'est_corrige', 'date_ajout', 'date_maj',
]


class DataService:
    def __init__(self, app=None, bd_pt=None, bd_entrainement=None):
        self.app = app
        self.bd_pt = bd_pt or BD_PT
        self.bd_entrainement = bd_entrainement or BD_ENTRAINEMENT
        self.local = SimpleNamespace()
        self.conn = None
        self.dictionnaire_labels = {}
        self.dictionnaire_origines = {}
        self.dictionnaire_unites_poids = {}
        self.csv_fournisseurs = None
        self.traitement_appertises = pd.DataFrame()
        self.poids_moyen_fl = pd.DataFrame()

        self.creer_dossiers()

        try:
            self.conn = sqlite3.connect(self.bd_pt)
            self.conn.row_factory = sqlite3.Row
            self.initialiser_bd()
        except Exception as e:
            console.print(f"[red]Erreur: impossible de créer/ouvrir la base de données: {e}")
            self.conn = None

        try:
            self.charger_csvs()
        except Exception as e:
            console.print(f"[yellow]Avertissement lors du chargement des CSV: {e}")

    def creer_dossiers(self):
        """Crée les dossiers nécessaires de l'application."""
        os.makedirs(MODELES_DIR, exist_ok=True)
        os.makedirs(PARAMETRES_DIR, exist_ok=True)
        os.makedirs(os.path.dirname(self.bd_pt), exist_ok=True)
        os.makedirs(os.path.dirname(self.bd_entrainement), exist_ok=True)

    def initialiser_bd(self):
        """Initialise la base de données des produits traités."""
        if self.conn is not None:
            self.creer_bd_pt(self.conn)
            self.migrer_bd_si_necessaire(self.conn)

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

    def creer_bd_pt(self, conn=None):
        """Crée les tables nécessaires dans la base de données de produits traités.
        Ce schéma est la source de vérité unique de la table produits."""
        conn = conn if conn is not None else self.conn
        if conn is None:
            return
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
                        methode_prediction TEXT DEFAULT 'Non défini',
                        a_reviser BOOLEAN,
                        est_corrige BOOLEAN DEFAULT 0,
                        date_ajout TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        date_maj TIMESTAMP)''')
        # TODO: temporaire pendant transition
        curseur.execute('CREATE INDEX IF NOT EXISTS idx_code_produit ON produits(code_produit)')
        curseur.execute('CREATE INDEX IF NOT EXISTS idx_texte_brut ON produits(texte_brut)')

        
        conn.commit()

    def migrer_bd_si_necessaire(self, conn=None):
        """Aligne une base existante sur le schéma de creer_bd_pt (bases créées
        avant l'ajout de la colonne 'methode_prediction')."""
        conn = conn if conn is not None else self.conn
        if conn is None:
            return
        try:
            curseur = conn.cursor()
            curseur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='produits'")
            if not curseur.fetchone():
                return
            curseur.execute("PRAGMA table_info(produits)")
            colonnes = [row[1] for row in curseur.fetchall()]
            if 'methode_prediction' not in colonnes:
                curseur.execute("ALTER TABLE produits ADD COLUMN methode_prediction TEXT DEFAULT 'Non défini'")
                conn.commit()
                console.print("[cyan]Colonne 'methode_prediction' ajoutée à la table produits")
        except Exception as e:
            console.print(f"[red]Erreur lors de la migration de la base de produits traités: {e}")

    def creer_bd_entrainement(self):
        """Crée une nouvelle base de données d'entraînement à partir du CSV pt_base.csv."""
        pt_base = ressource_path(os.path.join("parametres", "pt_base.csv"))
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

        os.makedirs(os.path.dirname(self.bd_entrainement), exist_ok=True)
        with sqlite3.connect(self.bd_entrainement) as conn:
            df.to_sql('entrainement', conn, if_exists='replace', index=False)

        console.print(f"[green]Base d'entraînement créée avec succès : {self.bd_entrainement}")
        return True

    def maj_bd_entrainement(self):
        """Met à jour la base d'entraînement à partir de la base de produits traités."""
        if not os.path.exists(self.bd_entrainement):
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
            with sqlite3.connect(self.bd_entrainement) as conn:
                df_existant = pd.read_sql_query("SELECT designation, base_variante FROM entrainement", conn)
        except Exception:
            df_existant = pd.DataFrame(columns=['designation', 'base_variante'])

        df_combine = pd.concat([df_existant, df_selection], ignore_index=True)
        df_combine = df_combine.drop_duplicates(subset=['designation', 'base_variante']).reset_index(drop=True)

        with sqlite3.connect(self.bd_entrainement) as conn:
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

    def inserer_produit(self, produit, commit=True):
        """Insère un produit (dictionnaire) et retourne son identifiant."""
        if self.conn is None:
            console.print("[red]Connexion à la base de données non disponible")
            return None

        colonnes = [colonne for colonne in COLONNES_PRODUITS if colonne in produit]
        valeurs = [produit[colonne] for colonne in colonnes]
        placeholders = ", ".join(["?"] * len(colonnes))
        requete = f"INSERT INTO produits ({', '.join(colonnes)}) VALUES ({placeholders})"

        curseur = self.conn.cursor()
        curseur.execute(requete, valeurs)
        if commit:
            self.conn.commit()
        return curseur.lastrowid

    def obtenir_produit_par_code_produit(self, code_produit):
        """Récupère un produit à partir de son code produit."""
        return self._obtenir_produit("code_produit", code_produit)

    def obtenir_produit_par_texte_brut(self, texte_brut):
        """Récupère un produit à partir de sa désignation brute."""
        return self._obtenir_produit("texte_brut", texte_brut)

    def _obtenir_produit(self, colonne, valeur):
        if self.conn is None or valeur is None:
            return None

        curseur = self.conn.cursor()
        curseur.execute(f"SELECT * FROM produits WHERE {colonne} = ?", (valeur,))
        ligne = curseur.fetchone()
        return dict(ligne) if ligne is not None else None

    def supprimer_produits(self, produits, commit=True):
        """Supprime des produits identifiés par leur code produit ou, à défaut,
        par leur désignation brute. `produits` est un itérable de dictionnaires
        (ou de lignes de DataFrame) et la méthode retourne le nombre de lignes supprimées."""
        if self.conn is None:
            console.print("[red]Connexion à la base de données non disponible")
            return 0

        curseur = self.conn.cursor()
        supprimes = 0
        for produit in produits:
            code_produit = produit.get('code_produit')
            texte_brut = produit.get('texte_brut')
            if code_produit is not None and str(code_produit).strip() not in ("", "nan"):
                curseur.execute("DELETE FROM produits WHERE code_produit = ?", (code_produit,))
            elif texte_brut is not None and str(texte_brut).strip() not in ("", "nan"):
                curseur.execute("DELETE FROM produits WHERE texte_brut = ?", (texte_brut,))
            else:
                continue
            supprimes += curseur.rowcount if curseur.rowcount > 0 else 0

        if commit:
            self.conn.commit()
        return supprimes

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

    def valider(self):
        """Valide (commit) la transaction en cours."""
        if self.conn is not None:
            self.conn.commit()

    def fermer(self):
        """Ferme la connexion à la base de données."""
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def recreer_bd_pt (self):
        self.fermer()
        if os.path.exists(self.bd_pt):
            os.remove(self.bd_pt)
        self.conn = sqlite3.connect(self.bd_pt)
        self.conn.row_factory = sqlite3.Row
        self.creer_bd_pt()
        self.valider()

    def recreer_bd_entrainement (self):
        bd_entrainement = self.bd_entrainement
        if os.path.exists (bd_entrainement):
            os.remove(bd_entrainement)
        self.creer_bd_entrainement

    def exporter_bd_pt_excel(self, chemin, progress_callback=None):
        """
        Exporte la base de produits traités vers un fichier Excel.

        La progression est purement indicative : openpyxl écrit le classeur en une
        seule opération monolithique, impossible à découper en lots.
        """
        if progress_callback:
            progress_callback(5, "Lecture de la base de produits traités...")
        # Connexion dédiée : cet export peut être exécuté depuis un thread de travail,
        # alors que self.conn appartient au thread qui a créé le DataService.
        with sqlite3.connect(self.bd_pt) as conn:
            df = pd.read_sql("SELECT * FROM produits", conn)
        if df.empty:
            return False
        if progress_callback:
            progress_callback(30, f"Écriture Excel en cours ({len(df)} lignes)...")
        df.to_excel(chemin, index=False)
        if progress_callback:
            progress_callback(100, f"Export Excel terminé ({len(df)} lignes).")
        return True

    def exporter_bd_pt_csv(self, chemin, chunksize=50000, progress_callback=None):
        """
        Exporte la base de produits traités vers un fichier CSV, par lots.

        L'écriture se fait en flux (un lot à la fois) pour ne jamais charger toute
        la base en mémoire, contrairement à l'export Excel.
        """
        if self.conn is None:
            return False

        lignes_ecrites = 0
        premier_lot = True
        # Connexion dédiée en lecture : cet export peut être exécuté depuis un thread
        # de travail, alors que self.conn appartient au thread qui a créé le DataService.
        with sqlite3.connect(self.bd_pt) as conn:
            try:
                total = conn.execute("SELECT COUNT(*) FROM produits").fetchone()[0]
            except Exception as e:
                console.print(f"[red]Erreur lors du comptage des produits: {e}")
                return False

            if not total:
                return False

            for lot in pd.read_sql("SELECT * FROM produits", conn, chunksize=chunksize):
                lot.to_csv(
                    chemin,
                    index=False,
                    mode='w' if premier_lot else 'a',
                    header=premier_lot,
                    encoding='utf-8-sig',
                )
                premier_lot = False
                lignes_ecrites += len(lot)
                if progress_callback:
                    pourcentage = int(min(100, lignes_ecrites * 100 / total))
                    progress_callback(pourcentage, f"{lignes_ecrites} / {total} lignes exportées...")

        if premier_lot:
            return False

        if progress_callback:
            progress_callback(100, f"Export CSV terminé ({lignes_ecrites} lignes).")
        return True

    def exporter_bd_entrainement_excel(self, chemin):  
            """Exporte la base de produits traités vers un fichier Excel."""  
            self.maj_bd_entrainement()
            with sqlite3.connect(self.bd_entrainement) as conn:
                df_entrainement = pd.read_sql_query("SELECT designation, base_variante FROM entrainement", conn)
            if df_entrainement.empty:  
                return False  
            df_entrainement.to_excel(chemin, index=False)  
            return True

    