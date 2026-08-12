## Explication du fichier
# Ce ficher fait le traitement des données importer (fichier CSV à traiter)

## Bibliothèques
import os
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime
import threading
from tkinter import filedialog, messagebox
import re
import joblib
from sklearn.metrics.pairwise import cosine_similarity
from utils import BD_PT, MODELES_DIR, ressource_path
from gestion_ml import creer_modeles
from services import creer_bd_pt


# Code
#TODO: bouger une partie de ce code pour n_revision.py quand ça sera prêt
class ImportationDonnees:
    # Cette classe pour gérer l'importation et le traitement des données de produits propres (designation, base_variante) pour l'entraînement des modèles depuis un fichier CSV.
    def __init__(self, bd_pt, controller=None):        
        self.bd_pt = bd_pt
        self.controller = controller
        self.last_error = None
        self.classificateur = ClassificateurProduits(controller=controller)
        self.importer_csv_pp()

    def importer_csv_pp(self):
        """Ouvre une boîte de dialogue pour choisir un fichier CSV et lance le traitement en thread."""
        # TODO: Ajouter possibilité de choisir un fichier Excel ou CSV
        file_path = filedialog.askopenfilename(filetypes=[("Fichiers CSV", "*.csv")])
        if file_path:
            file_path = os.path.normpath(file_path)
            threading.Thread(
                target=self.traiter_fichier_pp,
                args=(file_path,),
                daemon=True
            ).start()

    def traiter_fichier_pp(self, file_path):
        """Traite le fichier CSV de produits propres et l'importe dans la base de données."""
        #TODO: Remplacer les fonctions par le traitement de la class ClassificateurProduits
        try:
            # Lire le fichier CSV
            df = pd.read_csv(file_path)

            # Vérifier les colonnes obligatoires
            colonnes_requises = ['designation', 'base_variante']
            for col in colonnes_requises:
                if col not in df.columns:
                    raise ValueError(f"Colonne manquante: {col}")

            # Ajouter les colonnes manquantes avec valeurs par défaut
            if 'siret' in df.columns:
                df['fournisseur'] = df['siret'].apply(self.classificateur.attribuer_fournisseur)
            else:
                df['fournisseur'] = None

            # Attribuer aliment, variante, allergènes et TVA à partir de base_variante
            if not all(col in df.columns for col in ['aliment', 'variante', 'allergenes', 'tva']):
                resultats_attribution = df['base_variante'].apply(
                    lambda x: self.classificateur.convertir_base_variante(str(x)) if pd.notna(x) else (
                    None, None, None, None, None)
                )
                df[['aliment', 'variante', 'allergenes', 'tva', 'famille']] = pd.DataFrame(
                    resultats_attribution.tolist(),
                    index=df.index
                )

            if 'poids_unitaire' not in df.columns:
                if 'poids_min' in df.columns and 'poids_max' in df.columns:
                    df['poids_unitaire'] = (df['poids_min'].fillna(0) + df['poids_max'].fillna(0)) / 2
                else:
                    df['poids_unitaire'] = None

            if not 'unite_consommation' in df.columns:
                def _unite_consommation(row):
                    unite_poids = row.get('unite_poids', None)
                    if unite_poids == 'g':
                        return 'pièce'
                    elif unite_poids == 'kg':
                        return 'Kg'
                    elif unite_poids == 'L':
                        return 'L'
                    elif unite_poids == 'ml':
                        return 'pièce'
                    else:
                        return unite_poids

                df['unite_consommation'] = df.apply(_unite_consommation, axis=1)

            # Ajouter les colonnes de confiance et flags
            df['confiance_basevariante'] = 1.0
            df['a_reviser'] = False
            df['est_corrige'] = False
            df['date_ajout'] = datetime.now()

            # Ajouter texte_propre si manquant
            if 'texte_propre' not in df.columns:
                df['texte_propre'] = df['texte_brut'].apply(self.classificateur.nettoyer_texte)

            # Remover colonne temporaire 'famille'
            if 'famille' in df.columns:
                df = df.drop(columns=['famille'])

            # Enregistrer dans la base de données
            self.importer_pp_bd(df)
            if self.controller:
                self.controller.after(0, lambda: messagebox.showinfo("Succès", "Importation terminée avec succès!"))
            else:
                messagebox.showinfo("Succès", "Importation terminée avec succès!")

        except Exception as e:
            self.last_error = e
            if self.controller:
                self.controller.after(0, lambda: messagebox.showerror("Erreur",
                                                                      f"Erreur lors de l'importation: \n{str(e)}"))
            else:
                messagebox.showerror("Erreur", f"Erreur lors de l'importation: \n{str(e)}")

    def importer_pp_bd(self, df):
        # TODO : il faut que la colonne a_reviser soit "false" et que la colonne est_corrige soit "true"
        """Insère le DataFrame dans la base de données SQLite."""
        conn = sqlite3.connect(self.bd_pt)
        try:
            cursor = conn.cursor()
            # --- VERIFIER SCHEMA AVANT ---
            print("Schema da tableau produits avant l'insert:")
            for row in cursor.execute("PRAGMA table_info(produits);"):
                print(row)
            # Supprime la colonne 'id' si elle existe pour laisser SQLite gérer l'auto-incrément
            if 'id' in df.columns:
                df = df.drop(columns=['id'])
            if df.index.name == 'id':
                df.index.name = None
            df = df.reset_index(drop=True)

            # Sélectionner uniquement les colonnes existantes dans la table
            colonnes_table = [
                'texte_brut', 'texte_propre', 'code_produit', 'siret', 'fournisseur',
                'base_variante', 'aliment', 'variante', 'conditionnement', 'packaging', 'unite_packaging',
                'origine', 'poids_unitaire', 'poids_min',
                'poids_max', 'unite_poids', 'poids_total_kg', 'labels', 'allergenes',
                'unite_consommation', 'tva', 'confiance_basevariante', 
                'methode_prediction', 'a_reviser', 'est_corrige', 'date_ajout'
            ]

            # Filtrer les colonnes existantes dans le DataFrame
            colonnes_a_inserer = [col for col in colonnes_table if col in df.columns]
            df = df[colonnes_a_inserer]

            # Supprime les produits en doublon
            for _, row in df.iterrows():
                code_produit = row.get('code_produit')
                texte_brut = row.get('texte_brut')

                # Supprime d'abord par code_produit, si déjà existant (si non None)
                if pd.notna(code_produit) and str(code_produit).strip() != "":
                    cursor.execute(
                        "DELETE FROM produits WHERE code_produit = ?",
                        (code_produit,)
                    )
                # Puis, s'il n'a pas trouvé un code produit, essayer par le texte_brut
                else:
                    cursor.execute(
                        "DELETE FROM produits WHERE texte_brut = ?",
                        (texte_brut,)
                    )
            conn.commit()

            # Insérer dans la base de données
            df.to_sql('produits', conn, if_exists='append', index=False)
            print("Schema du tableau produits APRÈS l'insert:")
            for row in cursor.execute("PRAGMA table_info(produits);"):
                print(row)
        finally:
            conn.close()


class ClassificateurProduits:
    """Classe pour classifier et traiter les produits alimentaires."""
    
    def __init__(self, controller=None, bd_pt=None):
        """Initialise le classificateur avec tous les attributs nécessaires."""
        self.controller = controller
        self.bd_pt = bd_pt or BD_PT
        
        # Initialiser les attributs avec des valeurs par défaut
        self.vectoriseur = None
        self.modele_basevariante = None
        self.vectoriseur_tfidf_cosine = None
        self.donnees_basevariante_cosine = None
        self.categories = pd.DataFrame()  # DataFrame des catégories (bases, variantes, familles)
        self.fournisseurs = pd.DataFrame()  # DataFrame des fournisseurs
        self.labels = {}  # Dictionnaire des labels
        self.origines = {}  # Dictionnaire des origines
        self.unites_poids = {}  # Dictionnaire des unités de poids
        self.traitement_appertises = pd.DataFrame()  # DataFrame du traitement des appertises
        self.poids_moyen_fl = pd.DataFrame()  # DataFrame des poids moyens fruits/légumes
        
        # Charger les données depuis le service si disponible
        self._charger_donnees_service()
        self._charger_parametres()
        
        # Migrer la BD si nécessaire
        self._migrer_bd_si_necessaire()
    
    def _charger_donnees_service(self):
        """Charge les données depuis le service de données s'il est disponible."""
        try:
            # Si on a un contrôleur avec un data_service, charger les données depuis là
            if self.controller and hasattr(self.controller, 'data_service'):
                data_service = self.controller.data_service

                if hasattr(data_service, 'dictionnaire_labels'):
                    self.labels = data_service.dictionnaire_labels
                if hasattr(data_service, 'dictionnaire_origines'):
                    self.origines = data_service.dictionnaire_origines
                if hasattr(data_service, 'dictionnaire_unites_poids'):
                    self.unites_poids = data_service.dictionnaire_unites_poids
                if hasattr(data_service, 'vectoriseur'):
                    self.vectoriseur = data_service.vectoriseur
                if hasattr(data_service, 'modele_basevariante'):
                    self.modele_basevariante = data_service.modele_basevariante
                if hasattr(data_service, 'vectoriseur_tfidf_cosine'):
                    self.vectoriseur_tfidf_cosine = data_service.vectoriseur_tfidf_cosine
                if hasattr(data_service, 'donnees_basevariante_cosine'):
                    self.donnees_basevariante_cosine = data_service.donnees_basevariante_cosine
                if hasattr(data_service, 'csv_fournisseurs'):
                    self.fournisseurs = data_service.csv_fournisseurs if data_service.csv_fournisseurs is not None else pd.DataFrame()
                if hasattr(data_service, 'traitement_appertises'):
                    self.traitement_appertises = data_service.traitement_appertises
                if hasattr(data_service, 'poids_moyen_fl'):
                    self.poids_moyen_fl = data_service.poids_moyen_fl
        except Exception:
            pass  # Si le chargement échoue, utiliser les valeurs par défaut

    def _charger_parametres(self):
        """Charge les fichiers de paramètres nécessaires au traitement."""
        try:
            categories_csv = ressource_path(os.path.join("parametres", "categories.csv"))
            if os.path.exists(categories_csv):
                df = pd.read_csv(categories_csv, dtype=str)
                df.columns = df.columns.str.lower()
                self.categories = df
        except Exception as e:
            print(f"Erreur lors du chargement des paramètres catégories: {e}")

    def _migrer_bd_si_necessaire(self):
        """Ajoute la colonne 'methode_prediction' à la table produits si elle n'existe pas."""
        try:
            with sqlite3.connect(self.bd_pt) as conn:
                cursor = conn.cursor()
                # Vérifier si la table produits existe
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='produits'")
                if cursor.fetchone():
                    # Vérifier si la colonne existe
                    cursor.execute("PRAGMA table_info(produits)")
                    colonnes = [row[1] for row in cursor.fetchall()]
                    if 'methode_prediction' not in colonnes:
                        # Ajouter la colonne avec une valeur par défaut
                        cursor.execute("ALTER TABLE produits ADD COLUMN methode_prediction TEXT DEFAULT 'Non défini'")
                        conn.commit()
                        print("[cyan]Colonne 'methode_prediction' ajoutée à la table produits[/cyan]")
        except Exception as e:
            print(f"Erreur lors de la migration de la BD: {e}")
    
    def charger_modeles(self):
        """Charge tous les modèles de machine learning nécessaires."""
        try:
            # Charger les modèles de la première méthode (LinearSVC)
            vectoriseur_path = os.path.join(MODELES_DIR, 'vectoriseur.joblib')
            modele_path = os.path.join(MODELES_DIR, 'modele_basevariante.joblib')

            if os.path.exists(vectoriseur_path) and os.path.exists(modele_path):
                self.vectoriseur = joblib.load(vectoriseur_path)
                self.modele_basevariante = joblib.load(modele_path)
            else:
                self.vectoriseur = None
                self.modele_basevariante = None

            # Charger les modèles de la deuxième méthode (TF-IDF Cosine)
            vectoriseur_cosine_path = os.path.join(MODELES_DIR, 'vectoriseur_tfidf_cosine.joblib')
            donnees_cosine_path = os.path.join(MODELES_DIR, 'donnees_basevariante_cosine.joblib')

            if os.path.exists(vectoriseur_cosine_path) and os.path.exists(donnees_cosine_path):
                self.vectoriseur_tfidf_cosine = joblib.load(vectoriseur_cosine_path)
                self.donnees_basevariante_cosine = joblib.load(donnees_cosine_path)
            else:
                self.vectoriseur_tfidf_cosine = None
                self.donnees_basevariante_cosine = None
        except Exception as e:
            print(f"Erreur lors du chargement des modèles: {e}")
            self.vectoriseur = None
            self.modele_basevariante = None
            self.vectoriseur_tfidf_cosine = None
            self.donnees_basevariante_cosine = None
    
    def predire_avec_methode_cosine(self, texte):
        """
        Prédit la basevariante en utilisant TF-IDF avec similarité cosinus.
        Retourne: (prediction, score_confiance)
        """
        try:
            if self.vectoriseur_tfidf_cosine is None or self.donnees_basevariante_cosine is None:
                return None, 0.0
            
            texte_propre = self.nettoyer_texte(texte)
            tfidf_input = self.vectoriseur_tfidf_cosine.transform([texte_propre])
            
            # Vectoriser toutes les basevariantes de référence
            basevariantes = self.donnees_basevariante_cosine['base_variantes']
            tfidf_reference = self.vectoriseur_tfidf_cosine.transform(basevariantes)
            
            # Calculer la similarité cosinus
            similarites = cosine_similarity(tfidf_input, tfidf_reference)[0]
            
            # Obtenir l'index du meilleur résultat
            meilleur_index = np.argmax(similarites)
            score_confiance = similarites[meilleur_index]
            prediction = basevariantes[meilleur_index]
            
            return prediction, score_confiance
        except Exception as e:
            print(f"Erreur dans la méthode cosine: {e}")
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
        texte_propre = self.nettoyer_texte(texte)
        vecteur = self.vectoriseur.transform([texte_propre])
        
        # Étape 1: Essayer Méthode 2 (TF-IDF Cosine)
        pred_method2, proba_method2 = self.predire_avec_methode_cosine(texte)
        
        # Étape 2: Si M2 >= 95%, l'utiliser directement
        if proba_method2 >= 0.95:
            return pred_method2, proba_method2, "TF-IDF_Cosine"
        
        # Étape 3: Essayer Méthode 1 (LinearSVC)
        pred_method1 = self.modele_basevariante.predict(vecteur)[0]
        proba_method1 = np.max(self.modele_basevariante.predict_proba(vecteur))
        
        # Étape 4: Si M1 >= 70%, l'utiliser directement
        if proba_method1 >= 0.70:
            return pred_method1, proba_method1, "LinearSVC"
        
        # Étape 5: Si M1 < 70%, comparer les deux et prendre le meilleur
        if proba_method2 > proba_method1:
            return pred_method2, proba_method2, "TF-IDF_Cosine"
        else:
            return pred_method1, proba_method1, "LinearSVC"
            
    def nettoyer_texte(self, texte):
        """Nettoie et normalise le texte"""
        texte = str(texte).lower()
        texte = re.sub(r'[^\w\s-]', '', texte)
        texte = re.sub(r'\s+', ' ', texte).strip()
        return texte

    def attribuer_aliment_et_variante(self, texte):
        # TODO : utiliser la méthode hybride pour determiner la basevariante, et ensuite attribuer aliment et variante
        basevariante, score_confiance, methode = self.predire_avec_methode_hybride(texte)
        basevariante = basevariante.lower()

        mask = self.categories['basevariante'].astype(str).str.lower() == basevariante
        matching_rows = self.categories[mask]

        if not matching_rows.empty:
            aliment = matching_rows.iloc[0]['aliment']
            variante = matching_rows.iloc[0]['variante']
            allergenes = matching_rows.iloc[0]['allergenes']
            tva = matching_rows.iloc[0]['tva']
            famille = matching_rows.iloc[0]['famille']
            return aliment, variante, allergenes, tva, famille
        return None, None, None, None, None

    def attribuer_fournisseur(self, siret):
        """
        Attribue le nom du fournisseur à partir du SIRET.
        Si le SIRET est nul ou vide, retourne None.
        """
        if not siret or pd.isna(siret) or str(siret).strip() == "":
            return None

        # S'assurer que les fournisseurs sont chargés
        if not hasattr(self, 'fournisseurs') or self.fournisseurs is None or self.fournisseurs.empty:
            self.charger_fournisseurs()

        mask = self.fournisseurs['siret'].astype(str).str.strip() == str(siret).strip()
        matching_rows = self.fournisseurs[mask]

        if not matching_rows.empty:
            return matching_rows.iloc[0]['fournisseur']
        return None

    def extraire_origine(self, texte):
        try:
            exceptions_origine = [
                "petit suisse"]
            texte = texte.lower()

            # Vérifier d'abord si le texte contient une des exceptions
            for exception in exceptions_origine:
                if exception in texte:
                    return None

            # Si pas une exception, procéder à la recherche normale d'origine
            for origines, base_variante in self.origines.items():
                base_variante_clean = []
                for v in base_variante:
                    v_str = str(v).strip().lower()
                    if v_str:
                        base_variante_clean.append(re.escape(v_str))

                if not base_variante_clean:
                    continue

                regex_origine = r'(?<!\w)(' + '|'.join(base_variante_clean) + r')(?!\w)'

                if re.search(regex_origine, texte):
                    return origines
        except Exception:
            pass
        return None

    def extraire_label(self, texte):
        labels_trouves = []
        try:
            texte = texte.lower()
            for label, ecritures_label in self.labels.items():
                labels_clean = [re.escape(str(v).strip().lower())
                                for v in ecritures_label if str(v).strip()]
                if not labels_clean:
                    continue

                regex_label = r'(?<!\w)(' + '|'.join(labels_clean) + r')(?!\w)'

                if re.search(regex_label, texte):
                    labels_trouves.append(label)
        except Exception:
            pass
        return labels_trouves if labels_trouves else None

    def extraire_poids(self, texte):
        """Extrait les informations de poids"""
        toutes_unites = [unite for sublist in self.unites_poids.values() for unite in sublist]
        unites_regex = '|'.join(re.escape(unite) for unite in toutes_unites)

        # Cas spéciaux comme "2K5" ou "1G5" (2,5K)....... pas encore prêt, il continue à reconnaître comme 2 kg et 1 g
        match = re.search(r'(\d+)[kKgG](\d+)', texte)
        if match:
            poids = float(f"{match.group(1)}.{match.group(2)}")
            unite = 'kg' if match.group(0)[-2].lower() == 'k' else 'g'
            unite_consommation = 'Kg' if unite == 'kg' else 'pièce'
            return poids, poids, poids, unite, unite_consommation

        # Fonction regex
        pattern = r'(\d+[,.]?\d*)(?:-(\d+[,.]?\d*))?\s?({})(?=\w*\b)'.format(unites_regex)
        matches = re.findall(pattern, texte, re.IGNORECASE)

        poids_max = 0
        best_match = None

        for match in matches:
            p_min = float(match[0].replace(',', '.'))  # poids min c'est le premier chiffre du groupe regex
            p_max = float(match[1].replace(',', '.')) if match[
                1] else p_min  # poids max c'est le dexième chiffre du groupe regex
            unite_brute = match[2].lower()  # unité de poids (kg, g, ml...)
            if unite_brute == "cl":  # pour convertir le cl en ml automatiquement
                unite_brute = "ml"
                p_min = p_min * 10
                p_max = p_max * 10

            for unite_poids, base_variante in self.unites_poids.items():
                if unite_brute in base_variante:
                    poids_moyen = (p_min + p_max) / 2
                    if poids_moyen > poids_max:  # s'il y a deux poids dans la designation produit (ex: 200gx10 5K), il garde le poids le plus grand
                        poids_max = poids_moyen
                        # Déterminer l'unité de consommation en fonction de l'unité de poids
                        if unite_poids == 'g':
                            unite_consommation = 'pièce'
                        elif unite_poids == 'kg':
                            unite_consommation = 'Kg'
                        elif unite_poids == 'L':
                            unite_consommation = 'L'
                        elif unite_poids == 'ml':
                            unite_consommation = 'pièce'
                        else:
                            unite_consommation = unite_poids  # cas par défaut
                        best_match = (poids_moyen, p_min, p_max, unite_poids,
                                      unite_consommation)  # il garde ça comme le best_match est l'utilise
                    break

        if best_match:
            return best_match

        # Cas pour les oeufs (ex. oeufs frais moyen 53/63 x6)
        poids_oeufs = ['43/53', '53/63', '63/73', '+73']
        for val in poids_oeufs:
            if val in texte:
                if '/' in val:
                    p_min, p_max = map(float, val.split('/'))
                elif '+' in val:
                    p_min = float(val.strip('+'))
                    p_max = p_min
                poids_moyen = (p_min + p_max) / 2
                return poids_moyen, p_min, p_max, 'g', 'pièce'

        return None, None, None, None, None

    def extraire_packaging(self, texte):
        """Extrait les informations de packaging, en priorisant les formats totaux (ex: 2kg, 3L)."""
        texte_lower = texte.lower()

        packaging = None
        unite_packaging = None
        conditionnement = None

        # Reconnaître conditionnements standards
        conditionnements = ['5/5', '5/1', '4/4', '4/1', '3/3', '3/1', '2/1', 'a10']
        for c in conditionnements:
            pattern = r'(?<![\d,]){}(?![\dkg])'.format(re.escape(c.lower()))
            if re.search(pattern, texte_lower):
                conditionnement = c
                break

        # 1. PRIORITÉ : formats totaux (ex: "2kg", "3.5L", "1,5l")
        match_total = re.search(r'(?<![\d])(\d+[.,]?\d*)\s*(kg|k|kilogrammes?|l|litres|litre?)', texte_lower)
        if match_total:
            packaging = float(match_total.group(1).replace(',', '.'))
            unite_packaging = match_total.group(2).lower()
            if unite_packaging.startswith('l') or unite_packaging.startswith('litres') or unite_packaging.startswith(
                    'litre'):
                unite_packaging = 'L'
            elif unite_packaging.startswith('k') or unite_packaging.startswith('kg') or unite_packaging.startswith(
                    'kilogramme'):
                unite_packaging = 'Kg'
            return conditionnement, packaging, unite_packaging

        # 2. Formatos com multiplicação: 4x100g, 10x500ml → unidade = pièce
        pattern_complexe = re.compile(
            r'\(?(\d+)\s*[xX*]\s*(\d+[,.]?\d*)\s*(g|kg|ml|l|u|unités?|pièces?|tr|t)?\)?'
        )
        match_complexe = pattern_complexe.search(texte_lower)
        if match_complexe:
            packaging = int(match_complexe.group(1))
            unite_packaging = "pièce"
            return conditionnement, packaging, unite_packaging

        # 3. Cas simples: "4 unités", "5 paquets"
        match_simple = re.search(r'(?<![\w])(\d+)\s*(unités?|pièces?|u|tranches?|barquettes?)\b', texte_lower)
        if match_simple:
            packaging = int(match_simple.group(1))
            unite_packaging = "pièce"
            return conditionnement, packaging, unite_packaging

        # 4. Cas restantes: x4, *6
        match_xonly = re.search(r'[xX*]\s*(\d+)', texte_lower)
        if match_xonly:
            packaging = int(match_xonly.group(1))
            unite_packaging = "pièce"
            return conditionnement, packaging, unite_packaging

        return conditionnement, packaging, unite_packaging

    def extraire_poids_et_packaging(self, texte, famille=None):
        """Extrait les poids et packaging selon les règles spécifiées."""
        poids, poids_min, poids_max, unite, unite_consommation = self.extraire_poids(texte)

        packaging = None
        unite_packaging = None
        conditionnement = None

        poids_defaults_conditionnements = {
            "1/6": 0.13,
            "1/2": 0.415,
            "1/3": 0.25,
            "1/4": 0.25,
            "2/1": 1.5,
            "3/1": 1.9,
            "3/4": 0.59,
            "4/1": 2,
            "4/4": 0.8,
            "5/1": 4,
            "5/4": 1,
            "A10": 1.8,
        }

        # Cas 1 : Poids trouvé directement
        if poids_min is not None:
            _, packaging, unite_packaging = self.extraire_packaging(texte)

        else:
            # Vérifier si base_variante est présente dans le CSV
            base_variante = getattr(self, 'base_variante', None)
            if not base_variante:
                texte_propre = self.nettoyer_texte(texte)
                vecteur = self.vectoriseur.transform([texte_propre])
                base_variante = self.modele_basevariante.predict(vecteur)[0]
            base_variante = base_variante.lower()

            # Cas 2 : Poids non trouvé → chercher conditionnement
            conditionnement, _, _ = self.extraire_packaging(texte)
            if conditionnement:
                if not self.traitement_appertises.empty and base_variante:
                    match = self.traitement_appertises[
                        (self.traitement_appertises['basevariante'].str.lower() == base_variante) &
                        (self.traitement_appertises['conditionnement'] == conditionnement)
                        ]

                    if not match.empty:
                        poids_csv = float(str(match.iloc[0]['poids']).replace(',', '.'))
                        unite_csv = match.iloc[0]['unite_poids']
                        unite_consommation = "pièce"
                        return poids_csv, poids_csv, poids_csv, unite_csv, conditionnement, packaging, unite_packaging, unite_consommation

                poids_defaut = poids_defaults_conditionnements.get(conditionnement.upper())
                if poids_defaut:
                    unite_consommation = "kg"
                    return poids_defaut, poids_defaut, poids_defaut, "kg", conditionnement, packaging, unite_packaging, unite_consommation

            # Cas 3 : fruits/légumes
            if not self.poids_moyen_fl.empty and base_variante:
                match = self.poids_moyen_fl[self.poids_moyen_fl['basevariante'].str.lower() == base_variante]
                if not match.empty:
                    poids_csv = float(str(match.iloc[0]['poids']).replace(',', '.'))
                    unite_csv = match.iloc[0]['unite_poids']
                    unite_consommation = "pièce"
                    return poids_csv, poids_csv, poids_csv, unite_csv, conditionnement, packaging, unite_packaging, unite_consommation

        # Règle personnalisée à appliquer AVANT le retour final
        if (not unite_consommation or pd.isna(unite_consommation)) and famille == 'Viandes_Poissons':
            unite_consommation = 'Kg'

        return poids, poids_min, poids_max, unite, conditionnement, packaging, unite_packaging, unite_consommation

    def calculer_poids_total_kg(self, poids, unite, unite_packaging, packaging):
        """Calcule le poids total en kg"""
        # Si le poids n'est pas trouvé, laisser vide
        if poids is None or unite is None:
            return None

        # Si unite_packaging n'est pas "pièce"
        if unite_packaging is None:
            packaging = 1

        if unite_packaging in ["Kg", "L"]:
            return packaging

        # Conversion en Kg
        if unite == 'g' or unite == 'ml':
            poids_kg = poids / 1000
        elif unite in ['Kg', 'L']:
            poids_kg = packaging
        else:
            return None

            # Multiplie le poids converti en Kg par le packaging
        return poids_kg * packaging

    def classifier_produits(self, fichier_entree, progress_callback=None):
        """Classifie les produits à partir d'un fichier CSV avec colonnes: designation (obligatoire), code_produit (optionnel), siret (optionnel)"""
        self.charger_modeles()

        if self.vectoriseur is None or self.modele_basevariante is None:
            vectoriseur_path = os.path.join(MODELES_DIR, 'vectoriseur.joblib')
            modele_path = os.path.join(MODELES_DIR, 'modele_basevariante.joblib')

            if os.path.exists(vectoriseur_path) and os.path.exists(modele_path):
                raise RuntimeError(
                    "Les fichiers de modèles existent mais n'ont pas pu être chargés. "
                    "Supprimez-les et relancez le traitement pour tenter une reconstruction."
                )

            try:
                creer_modeles(self)
                self.charger_modeles()
            except Exception as e:
                raise RuntimeError(
                    "Impossible de créer les modèles de classification. "
                    f"Vérifiez les fichiers dans le dossier 'modeles'. Détail: {e}"
                ) from e

            if self.vectoriseur is None or self.modele_basevariante is None:
                raise RuntimeError(
                    "Les modèles n'ont pas été créés correctement. "
                    "Vérifiez l'état du dossier 'modeles'."
                )

        try:
            with sqlite3.connect(self.bd_pt) as conn:
                conn.row_factory = sqlite3.Row
                creer_bd_pt(self, conn) # Créer la base de connaissance si elle n'existe pas
                cursor = conn.cursor()
                resultats = []  # Liste pour stocker les résultats

                # Lire le fichier CSV
                df = pd.read_csv(fichier_entree, dtype=str)

                # Normaliser les noms de colonnes (ex: 'DESIGNATION' → 'designation')
                df.columns = df.columns.str.lower()

                # Flexibilisation de la manière d'écrire les colonnes
                alias_code_produit = ['code produit', 'code_produit', 'codeproduit', 'code', 'code produi',
                                      'ode_produit', 'ode produit']

                # Ckecker les alias de 'code_produit'
                for alias in alias_code_produit:
                    if alias in df.columns:
                        df['code_produit'] = df[alias]
                        break

                # Garantire que les autres colonnes existent
                if 'code_produit' not in df.columns:
                    df['code_produit'] = None
                if 'siret' not in df.columns:
                    df['siret'] = None
                if 'designation' not in df.columns:
                    raise ValueError("Le fichier CSV doit contenir une colonne 'designation'.")

                produits = df.to_dict(orient='records')

                for i, produit in enumerate(produits):
                    texte_brut = produit.get('designation', '').strip()
                    code_produit = produit.get('code_produit')
                    siret = produit.get('siret')

                    resultat = {}
                    row = None
                    # Cherche le produit dans la base_connaissance (d'abord par le code_produit et ensuite par le texte_brut)
                    if code_produit:
                        cursor.execute(
                            "SELECT * FROM produits WHERE code_produit = ?",
                            (code_produit,)
                        )
                        row = cursor.fetchone()

                    # 2. Si pas trouvé, chercher par texte_brut
                    if not row:
                        cursor.execute(
                            "SELECT * FROM produits WHERE texte_brut = ?",
                            (texte_brut,)
                        )
                        row = cursor.fetchone()

                    if row:  # si produit trouvé dans la base
                        resultat.update({
                            'id': row['id'],
                            'texte_brut': texte_brut,
                            'texte_propre': row['texte_propre'],
                            'code_produit': row['code_produit'],
                            'siret': row['siret'],
                            'fournisseur': row['fournisseur'],
                            'base_variante': row['base_variante'],
                            'aliment': row['aliment'],
                            'variante': row['variante'],
                            'conditionnement': row['conditionnement'],
                            'packaging': row['packaging'],
                            'unite_packaging': row['unite_packaging'],
                            'origine': row['origine'],
                            'poids_unitaire': row['poids_unitaire'],
                            'poids_min': row['poids_min'],
                            'poids_max': row['poids_max'],
                            'unite_poids': row['unite_poids'],
                            'poids_total_kg': row['poids_total_kg'],
                            'labels': row['labels'],
                            'allergenes': row['allergenes'],
                            'unite_consommation': row['unite_consommation'],
                            'tva': row['tva'],
                            'confiance_basevariante': row['confiance_basevariante'],
                            'methode_prediction': row['methode_prediction'] if 'methode_prediction' in row.keys() else 'Non défini',
                            'a_reviser': bool(row['a_reviser']) if 'a_reviser' in row.keys() else False,
                            'est_corrige': bool(row['est_corrige']) if 'est_corrige' in row.keys() else False
                        })

                    else:  # produit pas encore présent dans la base_connaissance
                        # Pré-traitement
                        texte_propre = self.nettoyer_texte(texte_brut)

                        # Vectorisation
                        vecteur = self.vectoriseur.transform([texte_propre])

                        # Prédictions avec méthode hybride
                        pred_basevariante, proba_basevariante, methode_prediction = self.predire_avec_methode_hybride(texte_brut)

                        # Caractéristiques supplémentaires
                        caracteristiques = self.extraire_caracteristiques(texte_brut, siret)

                        # Ajuste base_variante, aliment, variante si confiance < 25
                        if proba_basevariante < 0.25:
                            base_variante = "Produit non trouvé"
                            aliment = "Produit non trouvé"
                            variante = None
                            allergenes = None
                            tva = None
                        else:
                            base_variante = pred_basevariante
                            aliment = caracteristiques['aliment']
                            variante = caracteristiques['variante']
                            allergenes = caracteristiques['allergenes']
                            tva = caracteristiques['tva']

                        poids_total_kg = self.calculer_poids_total_kg(
                            caracteristiques['poids'],
                            caracteristiques['unite'],
                            caracteristiques['unite_packaging'],
                            caracteristiques['packaging']
                        )

                        # Formatage du résultat
                        resultat.update({
                            'texte_brut': texte_brut,
                            'texte_propre': texte_propre,
                            'code_produit': code_produit,
                            'siret': siret,
                            'fournisseur': caracteristiques['fournisseur'],
                            'base_variante': base_variante,
                            'aliment': aliment,
                            'variante': variante,
                            'conditionnement': caracteristiques['conditionnement'],
                            'packaging': caracteristiques['packaging'],
                            'unite_packaging': caracteristiques['unite_packaging'],
                            'origine': caracteristiques['origine'],
                            'poids_unitaire': caracteristiques['poids'],
                            'poids_min': caracteristiques['poids_min'],
                            'poids_max': caracteristiques['poids_max'],
                            'unite_poids': caracteristiques['unite'],
                            'poids_total_kg': poids_total_kg,
                            'labels': ','.join(caracteristiques['labels']) if caracteristiques['labels'] else None,
                            'allergenes': allergenes,
                            'unite_consommation': caracteristiques['unite_consommation'],
                            'tva': tva,
                            'confiance_basevariante': round(proba_basevariante * 100, 2),
                            'methode_prediction': methode_prediction,
                            'a_reviser': bool(proba_basevariante < 0.70),
                            'est_corrige': False
                        })
                        # Sauvegarder et récupérer l'ID
                        resultat['id'] = self.sauvegarder_produit(resultat, conn)

                    resultats.append(resultat)
                    if progress_callback:
                        progress = min(100, (i + 1) / len(produits) * 100)
                        progress_callback(progress, f"Traitement en cours... {i + 1}/{len(produits)}")

                conn.commit()
                return pd.DataFrame(resultats)

        except Exception as e:
            if progress_callback:
                progress_callback(100, f"Erreur: {str(e)}")
            raise

    def extraire_caracteristiques(self, texte, siret=None):
        """Extrait toutes les caractéristiques du produit"""

        # convertir siret en nom du fournisseur
        fournisseur = self.attribuer_fournisseur(siret)

        # attribuer aliment et variante
        aliment, variante, allergenes, tva, famille = self.attribuer_aliment_et_variante(texte)

        # Extrair poids, unité, conditionnement et packaging
        poids, poids_min, poids_max, unite, conditionnement, packaging, unite_packaging, unite_consommation = self.extraire_poids_et_packaging(
            texte, famille=famille)

        # Origine
        origine = self.extraire_origine(texte)

        # Labels
        label = self.extraire_label(texte)

        return {
            'fournisseur': fournisseur,
            'aliment': aliment,
            'variante': variante,
            'famille': famille,
            'poids': poids,
            'poids_min': poids_min,
            'poids_max': poids_max,
            'unite': unite,
            'conditionnement': conditionnement,
            'packaging': packaging,
            'unite_packaging': unite_packaging,
            'origine': origine,
            'labels': label,
            'allergenes': allergenes,
            'unite_consommation': unite_consommation,  # verificação: à faire plus tard
            'tva': tva
        }
    
    def sauvegarder_produit(self, produit, conn):
        """Sauvegarde un produit en base de données et retourne son id"""
        curseur = conn.cursor()
        curseur.execute('''INSERT INTO produits (
            texte_brut, texte_propre, code_produit, siret, fournisseur, base_variante, aliment, variante,
            conditionnement, packaging, unite_packaging, origine,
            poids_unitaire, poids_min, poids_max, unite_poids, poids_total_kg, labels, allergenes, unite_consommation, tva,
            confiance_basevariante, methode_prediction, a_reviser)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (produit['texte_brut'], produit['texte_propre'], produit['code_produit'], produit['siret'],
                         produit['fournisseur'],
                         produit['base_variante'], produit['aliment'], produit['variante'],
                         produit['conditionnement'], produit['packaging'],
                         produit['unite_packaging'], produit['origine'],
                         produit['poids_unitaire'], produit['poids_min'],
                         produit['poids_max'], produit['unite_poids'],
                         produit['poids_total_kg'], produit['labels'],
                         produit['allergenes'],
                         produit['unite_consommation'], produit['tva'],
                         produit['confiance_basevariante'], produit['methode_prediction'],
                         produit['a_reviser']))
        return curseur.lastrowid