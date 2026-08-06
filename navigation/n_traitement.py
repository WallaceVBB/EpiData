# Ce fichier fait le lien entre la GUI et le traitement des produits. 
# Il contient les fonctions qui sont appelées par les boutons de la GUI pour 
# lancer le traitement des produits.

from PySide6.QtWidgets import QFileDialog, QMessageBox
from data_processing import ImportationDonnees
from utils import console, GUI_DIR

