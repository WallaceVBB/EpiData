# WARNING : In progress

## Ce fichier doit gerer la navigation de la page gui/XXXX.ui

## Features de la page :
# Tableau SQL : tous les produits de BD_PT
# Bouton 'Actualiser' : pour enlever les produits qui sont marqués comme est_corrige = TRUE et laisser les autres
# Bouton 'Choix de revision' : pour montrer tous les produits de BD_PT' ou seulement les produits 'est_corrige = FALSE' (ce bouton doit changer entre 'Tous les produits' et 'Produits a corriger' si on click dessus), par defaut il doit etre 'Produit a corriger'
# Espace de recherche : espace où l'utilisateur peut chercher par un produit par sa designation produit (prochainement par code)

# La logique de mise à jour de la BD_PT sera organiser par products avec le fichier services.mettre_a_jour_produit(self, produit_id, donnees)

# La logique des produits à reviser est gérer par services.obtenir_produits_a_reviser(self)