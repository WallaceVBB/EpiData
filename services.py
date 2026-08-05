## Explication fichier :
# Ce fichier fait la gestion des services de l'application, 
# incluant la connexion à la base de données et le chargement des CSV nécessaires pour le traitement des produits alimentaires. 
# Il contient également les fonctions pour initialiser la base de données et charger les modèles de machine learning.

## TODO's :
# Prévoir un module distinct pour le traitement des données et la mise à jour des données.

## Variables
# 

## Bibliothèques
import os
import sqlite3
import joblib
import pandas as pd
from types import SimpleNamespace
from utils import console, MODELES_DIR, PARAMETRES_DIR, CHEMIN_BD_PT, ressource_path


class DataService:
    """Service de gestion des données, incluant la connexion à la base de données
    et le chargement des CSV. Conçu pour être instancié depuis l'UI (Application).
    """

    def __init__(self, app=None):
        self.app = app
        self.local = SimpleNamespace()

        # Connexion à la base de données de produits traités (créera le fichier si nécessaire)
        try:
            self.conn = sqlite3.connect(CHEMIN_BD_PT)
            self.initialiser_bd()
        except Exception as e:
            console.print(f"[red]Erreur: impossible de créer/ouvrir la base de données: {e}")
            self.conn = None

        # Charger les ressources (CSV, modèles)
        try:
            self.charger_csvs()
        except Exception as e:
            console.print(f"[yellow]Avertissement lors du chargement des CSV: {e}")

        try:
            self.charger_modeles()
        except Exception as e:
            console.print(f"[yellow]Avertissement lors du chargement des modèles: {e}")

    def charger_csvs(self):
        """Charge les CSV de paramètres et crée des dictionnaires utiles. Tolérant si les fichiers
        sont absents (utile pour un premier démarrage de développement).
        """
        # Labels
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

        # Origines
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

        # Unités de poids
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

        # Fournisseurs, poids moyens, traitements, categories: tenter de lire si présents
        self.csv_fournisseurs = None
        csv_fournisseurs = ressource_path(os.path.join("parametres", "fournisseurs.csv"))
        if os.path.exists(csv_fournisseurs):
            try:
                self.csv_fournisseurs = pd.read_csv(csv_fournisseurs)
            except Exception:
                self.csv_fournisseurs = None

        # Traitement des appertises
        self.traitement_appertises = pd.DataFrame()
        csv_traitement = ressource_path(os.path.join("parametres", "traitement_appertises.csv"))
        if os.path.exists(csv_traitement):
            try:
                self.traitement_appertises = pd.read_csv(csv_traitement)
            except Exception:
                self.traitement_appertises = pd.DataFrame()
        
        # Poids moyen fruits/légumes
        self.poids_moyen_fl = pd.DataFrame()
        csv_poids_fl = ressource_path(os.path.join("parametres", "poids_moyen_fl.csv"))
        if os.path.exists(csv_poids_fl):
            try:
                self.poids_moyen_fl = pd.read_csv(csv_poids_fl)
            except Exception:
                self.poids_moyen_fl = pd.DataFrame()

        # autres fichiers - chargement différé si nécessaire

    def initialiser_bd_pt(self):
        """Initialise ou récupère la connexion locale à la base de données de produits traités."""
        if not hasattr(self.local, 'connexion') or self.local.connexion is None:
            try:
                self.local.connexion = sqlite3.connect(CHEMIN_BD_PT)
                self.creer_bd_pt(self.local.connexion)
            except Exception as e:
                console.print(f"[red]Erreur création BD: {e}")
                self.local.connexion = None
        return getattr(self.local, 'connexion', None)

    def creer_dossiers(self):
        """Crée les dossiers utilisateurs nécessaires (placeholder)."""
        # Variables USER_MODELES / USER_DONNEES non définies dans l'ancien code;
        # on crée simplement le dossier MODELES_DIR et PARAMETRES_DIR s'ils n'existent pas.
        os.makedirs(MODELES_DIR, exist_ok=True)
        os.makedirs(PARAMETRES_DIR, exist_ok=True)

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

        if os.path.exists(vectoriseur_path) and os.path.exists(modele_path):
            try:
                self.vectoriseur = joblib.load(vectoriseur_path)
                self.modele_basevariante = joblib.load(modele_path)
                console.print("[bold green]✓ Modèles chargés avec succès")
            except Exception as e:
                console.print(f"[yellow]Impossible de charger les modèles: {e}")
                self.vectoriseur = None
                self.modele_basevariante = None
        else:
            # Pas d'erreur fatale : on laisse la création des modèles à la procédure dédiée
            self.vectoriseur = None
            self.modele_basevariante = None

    def creer_bd_entrainement(self):
        """Crée une nouvelle base de données d'entrainement à partir du CSV base des produits déjà traités"""
        pt_base = ressource_path(os.path.join("donnees", "pt_base.csv"))
        if not os.path.exists(pt_base):
            raise FileNotFoundError(f"Le fichier {pt_base} n'existe pas")
        # TODO: ajouter la logique pour créer la base de données d'entrainement à partir des données chargées du CSV

    def maj_bd_entrainement(self):
        """Met à jour la base de données d'entrainement à partir de la bd_pt"""
        # TODO: créer fonctions de maj de la bd_entrainement à partir de la bd_pt
        # TODO: prendre que les produits révisés ou les produits avec 90% ou plus de confiance
        # TODO: créer une manière de voir combien de produits neufs vont entrer dans la prochaine création de modèle
        pass

    def initialiser_bd(self):
        """Crée les tables de la base de données si elles n'existent pas."""
        if self.conn:
            self.creer_bd_pt(self.conn)

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
            df = pd.read_sql(f"SELECT * FROM produits WHERE id = ?", self.conn, params=[produit_id])
            if not df.empty:
                return df.iloc[0].to_dict()
            return None
        except Exception as e:
            console.print(f"[red]Erreur lors de la récupération du produit: {e}")
            return None
# Ce fichier fait la gestion des services de l'application, 
# incluant la connexion à la base de données et le chargement des CSV nécessaires pour le traitement des produits alimentaires. 
# Il contient également les fonctions pour initialiser la base de données et charger les modèles de machine learning.

## Acronymes
# PT = Produits Traités

def data_service(self):
    """Service de gestion des données, incluant la connexion à la base de données et le chargement des CSV"""
    self.conn = sqlite3.connect(CHEMIN_BD_PT)
    charger_csvs(self)
    charger_modeles(self)


def charger_csvs(self):
    # Charge le CSV des fournisseurs (SIRET et noms)
    csv_fournisseurs = ressource_path(os.path.join("parametres", "fournisseurs.csv"))


    # Charge le CSV des labels et de leurs différentes écritures
    csv_labels = ressource_path(os.path.join("parametres", "labels.csv"))
    df = pd.read_csv(csv_labels)
    dictionnaire_labels = {}
    for _, row in df.iterrows():
        label = str(row['labels']).strip()
        if not label:
            continue

        ecritures_label = [str(v).strip() for v in row[1:] if pd.notna(v) and str(v).strip()]
        dictionnaire_labels[label] = ecritures_label
        return dictionnaire_labels


    # Charge le CSV des origines
    csv_origines = ressource_path(os.path.join("parametres","origines.csv"))
    df = pd.read_csv(csv_origines)
    dictionnaire_origines = {}
    for _, row in df.iterrows():
        origine = str(row['origines']).strip()
        if not origine:
            continue

        variantes = [str(v).strip() for v in row[1:] if pd.notna(v) and str(v).strip()]
        dictionnaire_origines[origine] = variantes
        return dictionnaire_origines

    # Charge le CSV des poids moyens des fruits et légumes
    csv_poids_moyen_fl = ressource_path(os.path.join("parametres", "poids_moyen_fl.csv"))

    # Charge le CSV des traitements appertisés (ex. boîtes de conserve)
    csv_traitement_appertises = ressource_path(os.path.join("parametres", "traitement_appertises.csv"))

    # Charge le CSV des unités de poids (kg, g, ml...)
    csv_unites_poids = ressource_path(os.path.join("parametres", "unites_poids.csv"))
    df = pd.read_csv(csv_unites_poids)
    dictionnaire_unites_poids = {}
    for _, row in df.iterrows():
        unite_poids = str(row['unites']).strip()
        if not unite_poids:
            continue

        ecritures_unites_poids = [str(v).strip() for v in row[1:] if pd.notna(v) and str(v).strip()]
        dictionnaire_unites_poids[unite_poids] = ecritures_unites_poids
        return dictionnaire_unites_poids
    
    
    # Charge les categories avec les bases variantes, bases et variantes
    csv_categories = ressource_path(os.path.join("parametres", "categories.csv"))
    self.categories = pd.read_csv(csv_categories)

def initialiser_bd(self):
       
        # Fait la connexion avec la base de données de stockage des traitements réalisés
        if not hasattr(self.local, 'connexion'):
            self.local.connexion = sqlite3.connect(CHEMIN_BD_PT)
            self.creer_bd_pt(self.local.connexion)
            return self.local.connexion
        
        #Initialise la base de données SQLite
        conn = self.get_connexion()
        conn.commit()


def creer_dossiers(self):
        """Crée les dossiers USER_MODELES et USER_DONNEES, si nécessaires"""
        for dossier in [USER_MODELES, USER_DONNEES]:
            os.makedirs(dossier, exist_ok=True)


def creer_bd_pt (self, conn):
        """Crée les tables de la base de données de stockage des produits traités"""
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
                          gamme TEXT,
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
                          confiance_gamme REAL,
                          confiance_globale REAL,
                          a_reviser BOOLEAN,
                          est_corrige BOOLEAN DEFAULT 0,
                          date_ajout TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                          date_maj TIMESTAMP)''')


def charger_modeles(self):
       
       #Vérifie si les modèles ont déjà été enregistrés
        if (
                os.path.exists(ressource_path(os.path.join('modeles', 'vectoriseur.joblib'))) and
                os.path.exists(ressource_path(os.path.join('modeles', 'modele_basevariante.joblib')))) :
            
            self.vectoriseur = joblib.load(f'{USER_MODELES_DIR}/vectoriseur.joblib')

            self.modele_basevariante = joblib.load(f'{USER_MODELES_DIR}/modele_basevariante.joblib')

            self.modele_gamme = joblib.load(f'{USER_MODELES_DIR}/modele_gamme.joblib')

            console.print("[bold green]✓ Modèles chargés avec succès")
        
        # S'ils n'existent pas, créer modèles
        else:
            from gestion_ml import creer_modeles
            creer_modeles(self)


