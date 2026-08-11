# EpiData

**EpiData** est un logiciel open-source de traitement et d’analyse des données d’achats alimentaires.

Il est conçu pour les structures qui réalisent des achats alimentaires, notamment :

* 🏫 **Établissements publics** : cantines scolaires, EHPAD, établissements pénitentiaires, etc.
* 🤝 **Structures associatives** : épiceries sociales et solidaires, associations, etc.
* 🏪 **Structures privées** : épiceries, petits restaurants, commerces alimentaires, etc.

L'objectif est de faciliter la **structuration, l'enrichissement et l'analyse des données d'achats alimentaires**, afin de réduire le travail manuel nécessaire au suivi des achats et aux démarches de reporting.

## Fonctionnalités

EpiData propose actuellement deux fonctionnalités principales.

### 🔎 Classification et enrichissement des produits

À partir de la **désignation d'un produit**, le logiciel utilise des modèles de traitement automatique des données pour prédire différentes informations, notamment :

* type de produit ;
* gamme ;
* poids ;
* origine ;
* labels et signes de qualité.

Ces informations permettent ensuite de faciliter l'analyse des achats alimentaires et leur catégorisation.

### 📄 Conversion de factures PDF

EpiData permet de convertir des **factures au format PDF en tableaux Excel structurés**.

Le traitement vise notamment à :

* extraire les lignes correspondant aux produits achetés ;
* éliminer les informations ne concernant pas directement les produits ;
* structurer les données dans un format exploitable pour une analyse ultérieure.

L'objectif est de transformer des factures peu structurées en données directement utilisables dans un tableur ou dans un outil d'analyse.

## 🎯 Objectifs

EpiData a pour objectif de fournir un outil **libre, open-source et accessible** permettant aux structures réalisant des achats alimentaires de :

* structurer automatiquement leurs données d'achats ;
* réduire le temps consacré à la saisie et au nettoyage des données ;
* analyser la composition de leurs achats ;
* suivre l'évolution de leurs pratiques d'approvisionnement ;
* faciliter la réalisation de diagnostics sur la durabilité des achats alimentaires ;
* contribuer à la préparation des déclarations sur la plateforme *Ma Cantine*.

À terme, le projet vise à devenir un outil générique pouvant être utilisé par différents types de structures et avec différents fournisseurs.

## 🚧 Statut

⚠️ **Projet en cours de développement**

Les fonctionnalités actuelles sont fonctionnelles mais le logiciel est encore en phase de développement. Certaines fonctionnalités, notamment la classification automatique des produits et la prise en charge de nouvelles sources de données, sont susceptibles d'évoluer.

## 📊 Données

Les modèles et fonctionnalités d'EpiData s'appuient notamment sur plusieurs sources de données.

### Données issues des fournisseurs

Deux bases de données ont été constituées à partir de projets développés pour collecter et suivre les désignations de produits provenant de sites de fournisseurs :

* [Supermarche-Prix-Scraper](https://github.com/WallaceVBB/Supermarche-Prix-Scraper?utm_source=chatgpt.com)
* [Designation-Fournisseur-Tracker](https://github.com/WallaceVBB/Designation-Fournisseur-Tracker?utm_source=chatgpt.com)

### Open Food Facts

Une troisième source de données provient du projet **Open Food Facts**, une base de données collaborative et ouverte sur les produits alimentaires.

Les données utilisées dans EpiData peuvent être amenées à évoluer au fur et à mesure du développement du projet.

## 🛠️ Technologies

Le projet est principalement développé en **Python**.

Les différentes fonctionnalités s'appuient notamment sur des outils de :

* traitement et analyse de données ;
* machine learning et classification automatique ;
* extraction de données depuis des documents ;
* traitement de fichiers Excel et PDF.

*Cette section pourra être détaillée davantage au fur et à mesure que l'architecture du projet se stabilise.*

## 🤝 Contribution

EpiData est un projet **open-source** et les contributions sont les bienvenues.

Vous pouvez contribuer de différentes manières :

* signaler un bug ;
* proposer une nouvelle fonctionnalité ;
* suggérer une amélioration ;
* contribuer au code ;
* améliorer la documentation ;
* proposer de nouvelles sources de données.

Pour contribuer, vous pouvez ouvrir une **Issue** ou proposer une **Pull Request** sur GitHub.

## 📌 Feuille de route

Les prochaines évolutions envisagées comprennent notamment :

* [ ] améliorer la classification automatique des produits ;
* [ ] améliorer l'extraction automatique des factures ;
* [ ] faciliter la vérification et la correction des prédictions ;
* [ ] développer davantage les fonctionnalités d'analyse des achats ;
* [ ] améliorer l'interface utilisateur ;
* [ ] simplifier l'installation et la distribution du logiciel.

Cette feuille de route est susceptible d'évoluer en fonction des besoins des utilisateurs et des contributions au projet.

## 📄 Licence

Ce projet est distribué sous licence **MIT**.

Copyright © 2025 Wallace Bastos
