import re
from pathlib import Path

def extraire_facture_pdf(chemin_pdf, chemin_sortie_excel="facture_extraite.xlsx", progress_callback=None):
    """Extrait les lignes de produits d'une facture PDF et les enregistre dans un fichier Excel."""

    from pypdf import PdfReader
    import pandas as pd

    chemin_pdf = Path(chemin_pdf).expanduser()
    if not chemin_pdf.exists() or not chemin_pdf.is_file():
        raise FileNotFoundError(f"Le fichier PDF suivant est introuvable : {chemin_pdf}")

    reader = PdfReader(str(chemin_pdf))
    total_pages = len(reader.pages) or 1
    lignes_extraites = []

    # Expressions régulières pour capturer le B.L., la date et l'épicerie
    regex_bl_date = re.compile(
        r"B\.L\.\s*N°\s*(\d+)\s+Départ le\s+(\d{2}/\d{2}/\d{4})"
    )
    regex_epicerie = re.compile(r"Chez\s+(.+)")

    # Expression régulière conçue pour identifier les lignes de produits
    # (recherche l'unité caractéristique : K = Kilo, P = Pièce, R = Remise/Retour, C = Colis)
    regex_produit = re.compile(
        r"^([A-Za-z0-9*/\-\. ]+?)\s+"  # Description du produit et Origine
        r"([\d\.-]+)([KPRC])\s+"  # Prix unitaire + Unité (K, P, R, C)
        r"([\d\.-]+)\s+"  # Prix_Final
        r"([\d\.-]+)\s*"  # Palettes
        r"([\d\.-]*)\s*"  # Colis
        r"([\d\.-]*)\s*"  # Poids_brut
        r"([\d\.-]*)\s*"  # Tare_Qnt_colis
        r"([\d\.-]*)$"  # Poids_net_pieces
    )

    # Variables de contexte (conservent la dernière valeur rencontrée)
    bl_actuel = None
    date_actuelle = None
    epicerie_actuelle = None


    # Mots-clés pour ignorer les lignes d'en-tête, de pied de page et les conditions générales
    mots_ignores = [
        "FACTURE N°",
        "Règlement :",
        "Echéance :",
        "Produit    CatProvenance",
        "TRANS H.T.",
        "PORTMARCHANDISE",
        "TOTAL TVA",
        "NET A PAYER",
        "Conditions générales",
        "TRANSPORT DEPART",
    ]

    for page_num, page in enumerate(reader.pages, start=1):
        if progress_callback:
            progress_callback(
                int(10 + (page_num / total_pages) * 80),
                f"Analyse de la page {page_num}/{total_pages}"
            )

        # L'option "layout" préserve l'alignement tabulaire des colonnes du PDF
        texte = page.extract_text(extraction_mode="layout")
        if not texte:
            continue

        for ligne in texte.split("\n"):
            ligne = ligne.strip()

            # 1. Détecter si la ligne contient le N° de BL et la Date de départ
            match_bl = regex_bl_date.search(ligne)
            if match_bl:
                bl_actuel = match_bl.group(1)
                date_actuelle = match_bl.group(2)
                continue

            # 2. Détecter si la ligne contient le nom de l'épicerie
            match_epi = regex_epicerie.search(ligne)
            if match_epi:
                epicerie_actuelle = match_epi.group(1).strip()

            # Ignore les lignes vides ou contenant des mentions générales/en-têtes
            if not ligne or any(mot in ligne for mot in mots_ignores):
                continue

            # 3. Détecter s'il s'agit d'une ligne de produit
            if re.search(r"\s+([\d\.-]+)([KPRC])\s+", ligne):
                match = regex_produit.match(ligne)
                if match:
                    groupes = match.groups()
                    lignes_extraites.append(
                        {
                            "Page": page_num + 1,
                            "Date_Depart": date_actuelle,
                            "Epicerie": epicerie_actuelle,
                            "BL_No": bl_actuel,
                            "Description_Origine": groupes[0].strip(),
                            "Prix_Unitaire": float(groupes[1]),
                            "Unite": groupes[2],
                            "Prix_Final": (
                                float(groupes[3]) if groupes[3] else None
                            ),
                            "Pal": float(groupes[4]) if groupes[4] else None,
                            "Colis": float(groupes[5]) if groupes[5] else None,
                            "Poids_brut": (
                                float(groupes[6]) if groupes[6] else None
                            ),
                            "Tare_Qnt_colis": (
                                float(groupes[7]) if groupes[7] else None
                            ),
                            "Poids_net_pieces": (
                                float(groupes[8]) if groupes[8] else None
                            ),
                        }
                    )

    # Création du DataFrame pandas
    df_final = pd.DataFrame(lignes_extraites)
    output_path = Path(chemin_sortie_excel)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Export vers Excel
    df_final.to_excel(output_path, index=False)
    if progress_callback:
        progress_callback(100, f"Extraction terminée : {len(df_final)} ligne(s)")
    print(
        f"✅ Extraction terminée : {len(df_final)} lignes exportées dans '{output_path}'."
    )

    return df_final