## Explication du fichier
# Ce ficher fait le traitement des données importer (fichier CSV à traiter)
# Couche de traitement : elle orchestre la couche ML (gestion_ml.py) et la couche
# de persistance (services.py). Elle ne contient ni SQL brut ni code d'interface graphique.

## Bibliothèques
import os
import re

import pandas as pd

from gestion_ml import GestionML
from services import DataService
from utils import ressource_path, nettoyer_texte

# Code
class ClassificateurProduits:
    """Classe pour classifier et traiter les produits alimentaires."""
    
    def __init__(self, controller=None, bd_pt=None, data_service=None, gestion_ml=None):
        """Initialise le classificateur avec tous les attributs nécessaires."""
        self.controller = controller

        # Couche de persistance (source unique des accès base de données)
        self.data_service = data_service or getattr(controller, 'data_service', None) or DataService(bd_pt=bd_pt)
        self.bd_pt = self.data_service.bd_pt

        # Couche ML (propriétaire des modèles et de l'inférence)
        self.gestion_ml = gestion_ml or GestionML(data_service=self.data_service)

        # Initialiser les attributs avec des valeurs par défaut
        self.categories = pd.DataFrame()  # DataFrame des catégories (bases, variantes, familles)
        self.fournisseurs = pd.DataFrame()  # DataFrame des fournisseurs
        self.labels = {}  # Dictionnaire des labels
        self.origines = {}  # Dictionnaire des origines
        self.unites_poids = {}  # Dictionnaire des unités de poids
        self.traitement_appertises = pd.DataFrame()  # DataFrame du traitement des appertises
        self.poids_moyen_fl = pd.DataFrame()  # DataFrame des poids moyens fruits/légumes

        # Charger les données depuis le service
        self._charger_donnees_service()
        self._charger_parametres()

        # Patterns regex compilés pour optimisation
        self._REGEX_POIDS_SPECIAL = re.compile(r'(\d+)[kKgG](\d+)')  # Cas spéciaux comme "2K5" ou "1G5"
        self._REGEX_POIDS_STANDARD = re.compile(r'(\d+[,.]?\d*)(?:-(\d+[,.]?\d*))?\s?({})')
        self._REGEX_POIDS_OEUFS = re.compile(r'(43/53|53/63|63/73|\+73)')
        self._REGEX_PACKAGING_TOTAL = re.compile(r'(?<![\d])(\d+[.,]?\d*)\s*(kg|k|kilogrammes?|l|litres|litre?)', re.IGNORECASE)
        self._REGEX_PACKAGING_COMPLEXE = re.compile(r'\(?(\d+)\s*[xX*]\s*(\d+[,.]?\d*)\s*(g|kg|ml|l|u|unités?|pièces?|tr|t)?\)?', re.IGNORECASE)
        self._REGEX_PACKAGING_SIMPLE = re.compile(r'(?<![\w])(\d+)\s*(unités?|pièces?|u|tranches?|barquettes?)\b', re.IGNORECASE)
        self._REGEX_PACKAGING_XONLY = re.compile(r'[xX*]\s*(\d+)')
        self._REGEX_ORIGINE = re.compile(r'(?<!\w)({}?)(?!\w)')
        self._REGEX_LABEL = re.compile(r'(?<!\w)({}?)(?!\w)')

    def _charger_donnees_service(self):
        """Charge les données de référence depuis le service de données."""
        data_service = self.data_service
        if data_service is None:
            return

        self.labels = data_service.dictionnaire_labels
        self.origines = data_service.dictionnaire_origines
        self.unites_poids = data_service.dictionnaire_unites_poids
        self.fournisseurs = data_service.csv_fournisseurs if data_service.csv_fournisseurs is not None else pd.DataFrame()
        self.traitement_appertises = data_service.traitement_appertises
        self.poids_moyen_fl = data_service.poids_moyen_fl

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

    def charger_modeles(self):
        """Charge les modèles via la couche ML."""
        self.gestion_ml.charger_modeles()

    def predire_avec_methode_hybride(self, texte):
        """Prédiction hybride (TF-IDF Cosine puis LinearSVC), déléguée à la couche ML.
        Retourne: (prediction, score_confiance, methode_utilisee)"""
        return self.gestion_ml.predire_avec_methode_hybride(texte)

    def nettoyer_texte(self, texte):
        """Nettoie et normalise le texte (implémentation unique dans utils.py)."""
        return nettoyer_texte(texte)

    def attribuer_aliment_et_variante(self, texte):
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
        if self.fournisseurs is None or self.fournisseurs.empty:
            self._charger_donnees_service()
        if self.fournisseurs is None or self.fournisseurs.empty:
            return None

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

                pattern_str = '|'.join(base_variante_clean)
                regex_origine = self._REGEX_ORIGINE.pattern.format(pattern_str)

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

                pattern_str = '|'.join(labels_clean)
                regex_label = self._REGEX_LABEL.pattern.format(pattern_str)

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
        match = self._REGEX_POIDS_SPECIAL.search(texte)
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
        match_total = self._REGEX_PACKAGING_TOTAL.search(texte_lower)
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
        match_complexe = self._REGEX_PACKAGING_COMPLEXE.search(texte_lower)
        if match_complexe:
            packaging = int(match_complexe.group(1))
            unite_packaging = "pièce"
            return conditionnement, packaging, unite_packaging

        # 3. Cas simples: "4 unités", "5 paquets"
        match_simple = self._REGEX_PACKAGING_SIMPLE.search(texte_lower)
        if match_simple:
            packaging = int(match_simple.group(1))
            unite_packaging = "pièce"
            return conditionnement, packaging, unite_packaging

        # 4. Cas restantes: x4, *6
        match_xonly = self._REGEX_PACKAGING_XONLY.search(texte_lower)
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
                base_variante, _ = self.gestion_ml.predire_avec_svc(texte)
            base_variante = base_variante.lower() if base_variante else ''

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
        self.preparer_modeles()

        try:
            self.data_service.creer_bd_pt()  # Créer la base de connaissance si elle n'existe pas
            resultats = []  # Liste pour stocker les résultats

            # Lire le fichier CSV ou Excel
            _, ext = os.path.splitext(fichier_entree)
            ext = ext.lower()
            if ext == '.csv':
                df = pd.read_csv(fichier_entree, dtype=str)
            elif ext in ['.xls', '.xlsx']:
                df = pd.read_excel(fichier_entree, dtype=str)
            else:
                raise ValueError("Le fichier doit être au format CSV ou Excel (.csv, .xls, .xlsx).")


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

            # Optimisation: vérifier une seule fois si la colonne code_produit existe
            has_code_produit = 'code_produit' in df.columns
            
            for i, produit in enumerate(produits):
                texte_brut = produit.get('designation', '').strip()
                code_produit = produit.get('code_produit') if has_code_produit else None
                siret = produit.get('siret')

                resultat = {}
                # Cherche le produit dans la base_connaissance (d'abord par le code_produit et ensuite par le texte_brut)
                row = self.data_service.obtenir_produit_par_code_produit(code_produit) if has_code_produit and code_produit else None

                # 2. Si pas trouvé, chercher par texte_brut
                if not row:
                    row = self.data_service.obtenir_produit_par_texte_brut(texte_brut)

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
                        'methode_prediction': row.get('methode_prediction', 'Non défini'),
                        'a_reviser': bool(row.get('a_reviser', False)),
                        'est_corrige': bool(row.get('est_corrige', False))
                    })

                else:  # produit pas encore présent dans la base_connaissance
                    # Pré-traitement
                    texte_propre = self.nettoyer_texte(texte_brut)

                    # Prédictions avec méthode hybride
                    pred_basevariante, proba_basevariante, methode_prediction = self.predire_avec_methode_hybride(texte_propre)

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
                    resultat['id'] = self.sauvegarder_produit(resultat, commit=False)

                resultats.append(resultat)
                if progress_callback:
                    progress = min(100, (i + 1) / len(produits) * 100)
                    progress_callback(progress, f"Traitement en cours... {i + 1}/{len(produits)}")

            self.data_service.valider()
            return pd.DataFrame(resultats)

        except Exception as e:
            if progress_callback:
                progress_callback(100, f"Erreur: {str(e)}")
            raise

    def preparer_modeles(self):
        """S'assure que les modèles de classification sont disponibles.
        L'entraînement n'est déclenché que si aucun fichier de modèle n'est présent."""
        self.charger_modeles()
        if self.gestion_ml.modeles_svc_disponibles and self.gestion_ml.modeles_cosine_disponibles:
            return

        fichiers_presents = all(
            os.path.exists(self.gestion_ml.chemin_modele(nom))
            for nom in ('vectoriseur.joblib', 'modele_basevariante.joblib')
        )
        if fichiers_presents:
            raise RuntimeError(
                "Les fichiers de modèles existent mais n'ont pas pu être chargés. "
                "Supprimez-les et relancez le traitement pour tenter une reconstruction."
            )

        try:
            self.gestion_ml.creer_modeles()
            self.charger_modeles()
        except Exception as e:
            raise RuntimeError(
                "Impossible de créer les modèles de classification. "
                f"Vérifiez les fichiers dans le dossier 'modeles'. Détail: {e}"
            ) from e

        if not self.gestion_ml.modeles_svc_disponibles:
            raise RuntimeError(
                "Les modèles n'ont pas été créés correctement. "
                "Vérifiez l'état du dossier 'modeles'."
            )

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
            'unite_consommation': unite_consommation,  # TODO: à faire plus tard
            'tva': tva
        }
    
    def sauvegarder_produit(self, produit, commit=True):
        """Sauvegarde un produit via la couche de persistance et retourne son id"""
        return self.data_service.inserer_produit(produit, commit=commit)

    #def appliquer_correction ():
        # TODO : développer fonction qui va mettre changer a_reviser pour FALSE et est_corrige pour TRUE lors d'une correction dans une revision des résultats et de la BD_PT