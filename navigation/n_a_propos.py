### Navigation de la fenêtre A propos

from PySide6.QtWidgets import QLabel
from utils import VERSION

PROPOS_TEXT = f"""
<div style="font-family:'Segoe UI';">

    <h2 style="margin-bottom:12px;">
        Qu'est-ce qu'EpiData ?
    </h2>

    <p>
        EpiData est un logiciel conçu pour faciliter le traitement, la structuration et l'exploitation des données liées aux produits alimentaires.<br>
        Son objectif est de réduire les tâches répétitives liées au traitement des données et de faciliter leur intégration dans des outils de suivi, d'analyse et de gestion.<br>

        EpiData permet notamment de traiter des données issues de fichiers de produits et de factures, de les transformer dans un format structuré et d'enrichir automatiquement certaines informations grâce à des modèles de machine learning.
    </p>

    <h2 style="margin-bottom:12px;">
           Fonctionnement
    </h2>

    <p>
        EpiData combine plusieurs technologies pour automatiser le traitement des données :
        
        <ul>
        <li>traitement et normalisation des données ;</li>
        <li>outils permettant de vérifier et de corriger les résultats obtenus.</li>
        <li>conversion et extraction d'informations à partir de factures PDF ;</li>
        </ul>

        Les résultats produits automatiquement restent contrôlables par l'utilisateur afin de favoriser la qualité et la fiabilité des données.
    </p>

    <h2 style="margin-bottom:12px;">
           Un logiciel en développement
    </h2>

    <p>
        EpiData est un projet en évolution continue. Les fonctionnalités, les modèles et les méthodes de traitement sont régulièrement améliorés afin d'augmenter la fiabilité des résultats et de répondre aux besoins rencontrés sur le terrain.
    </p>

    <h2 style="margin-bottom:12px;">
            Crédits
    </h2>
    
    <p>
        <b>Développement et maintenance</b><br>
        Wallace Victor Bastos Barbosa
    </p>

    <p>
        <b>Soutien au développement</b><br>
        Groupement des Épiceries Sociales de Bourgogne-Franche-Comté
        (GESBFC)<br>
        <span style="color:#666;">
            Soutien au développement d'EpiData dans le cadre professionnel.
        </span>
    </p>

    <h2 style="margin-bottom:12px;">
           Version
    </h2>

    <p>
        EpiData<br>
        Version : {VERSION}
    </p>

    <p>
    © Wallace Victor Bastos Barbosa
    </p>

</div>
"""


class ProposNavigation:
    def __init__(self, load_gui):
        # Fonction permettant de charger un .ui (fournie par Application)
        self.load_gui = load_gui

        # La fenêtre est chargée une seule fois puis réutilisée
        self.fenetre = None

    def ouvrir_propos(self):
        if self.fenetre is None:
            self.fenetre = self.load_gui("A_propos.ui")
            self._configurer_propos(self.fenetre)

        self.fenetre.show()
        self.fenetre.raise_()
        self.fenetre.activateWindow()

    def _configurer_propos(self, fenetre):
        label = fenetre.findChild(QLabel, "l_a_propos")

        if label is None:
            raise RuntimeError("Le label 'l_a_propos' est introuvable dans A_propos.ui")

        label.setText(PROPOS_TEXT)
        label.setWordWrap(True)