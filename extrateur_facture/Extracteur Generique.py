import re
from collections import Counter
from pathlib import Path

import pandas as pd
import pdfplumber
from pypdf import PdfReader


# ----------------------------------------------------------------------
# Outils bas niveau
# ----------------------------------------------------------------------

def _tokenize(line):
    """Découpe une ligne de texte "layout" en tokens séparés par >=2 espaces.
    Retourne une liste de (position_debut, position_fin, texte)."""
    toks = []
    for m in re.finditer(r'(?:(?!\s{2,}).)+', line):
        s = m.group().strip()
        if s:
            toks.append((m.start(), m.end(), s))
    return toks


_NUM_RE = re.compile(r'\d')


def _is_numeric_token(text):
    """Heuristique : un token est "numérique" s'il contient des chiffres
    et que ceux-ci dominent (permet les unités courtes du type KG, PU, %, F, 1...)."""
    if not _NUM_RE.search(text):
        return False
    digits = sum(c.isdigit() for c in text)
    letters = sum(c.isalpha() for c in text)
    return digits >= letters or letters <= 4


# ----------------------------------------------------------------------
# Filtres pour ne garder QUE les produits
# ----------------------------------------------------------------------

def _is_product_table(df):
    """Vérifie si le tableau correspond à une liste de produits/articles."""
    if df.empty or len(df.columns) < 6:
        return False

    cols_str = " ".join([str(c).lower() for c in df.columns])

    # Mots-clés caractéristiques d'un tableau de produits
    prod_keywords = ['désignation', 'designation', 'article', 'produit', 'description', 'libellé', 'libelle', 'ligne']
    # Mots-clés de tableaux récapitulatifs à exclure
    exclude_keywords = ['net à payer', 'net a payer', 'echéance', 'echeance', 'iban', 'solde au', 'récapitulatif']

    if any(k in cols_str for k in exclude_keywords):
        return False

    if any(k in cols_str for k in prod_keywords):
        return True

    # Si les en-têtes sont génériques (ex: col_1, col_2), on analyse le contenu
    text_content = " ".join(df.astype(str).values.flatten()).lower()
    if any(k in text_content for k in ['total ht', 'net à payer', 'siret', 'iban', 'sogefrpp']):
        return False

    return len(df.columns) >= 3


def _clean_product_rows(df):
    """Nettoie les lignes internes de totaux / sous-totaux dans le tableau de produits."""
    if df.empty:
        return df

    unwanted_terms = ['total transport', 'total ht', 'total tva', 'total ttc', 'net à payer', 'taxes:', 'CVE :', 'cve', 'taux', 'Montant TVA']

    def is_summary_row(row):
        row_str = " ".join([str(v).lower() for v in row if pd.notna(v)])
        return any(term in row_str for term in unwanted_terms)

    mask = df.apply(is_summary_row, axis=1)
    return df[~mask].reset_index(drop=True)


# ----------------------------------------------------------------------
# Méthode 1 : tableaux avec lignes (bordures) détectés par pdfplumber
# ----------------------------------------------------------------------

def _extract_ruled_tables(pl_page):
    """Utilise pdfplumber pour détecter des tableaux avec bordures/lignes."""
    out = []
    try:
        tables = pl_page.extract_tables()
    except Exception:
        tables = []

    for table in tables:
        if not table or len(table) < 1:
            continue

        header = [(c or "").strip() for c in table[0]]
        body = table[1:]

        expanded_rows = []
        for row in body:
            splits = [(c or "").split("\n") for c in row]
            counts = [len(s) for s in splits]
            n_sub = max(counts, default=1)
            if n_sub <= 1:
                expanded_rows.append(row)
            else:
                target = Counter(counts).most_common(1)[0][0]
                aligned = []
                for s in splits:
                    if len(s) > target:
                        s = s[-target:]
                    elif len(s) < target:
                        s = [""] * (target - len(s)) + s
                    aligned.append(s)
                for i in range(target):
                    new_row = [s[i].strip() for s in aligned]
                    if any(v for v in new_row):
                        expanded_rows.append(new_row)

        if not expanded_rows:
            continue

        col_names = []
        for i, h in enumerate(header):
            h = re.sub(r'\s+', ' ', h).strip()
            col_names.append(h if h else f"col_{i+1}")

        seen = {}
        for i, name in enumerate(col_names):
            if name in seen:
                seen[name] += 1
                col_names[i] = f"{name}_{seen[name]}"
            else:
                seen[name] = 0

        df = pd.DataFrame(expanded_rows, columns=col_names)
        df = df[~(df.apply(lambda r: all((str(v).strip() == "") for v in r), axis=1))]
        if not df.empty:
            out.append(df)

    return out


# ----------------------------------------------------------------------
# Méthode 2 : tableaux "mise en page" (texte aligné par espaces)
# ----------------------------------------------------------------------

def _finalize_header(header_tokens):
    header_tokens = sorted(header_tokens, key=lambda t: t[0])
    cols = []
    for i, (s, e, text) in enumerate(header_tokens):
        left = -1 if i == 0 else (header_tokens[i - 1][1] + s) / 2
        right = 10**9 if i == len(header_tokens) - 1 else (e + header_tokens[i + 1][0]) / 2
        cols.append({"label": text, "left": left, "right": right})
    return cols


def _merge_header_line(current_tokens, new_line_tokens):
    if not current_tokens:
        return list(new_line_tokens)
    cols = _finalize_header(current_tokens)
    merged = list(current_tokens)
    for (s, e, text) in new_line_tokens:
        mid = (s + e) / 2
        placed = False
        for col in cols:
            if col["left"] <= mid < col["right"]:
                idx = None
                best_dist = None
                for j, (s2, e2, t2) in enumerate(merged):
                    cmid = (s2 + e2) / 2
                    if col["left"] <= cmid < col["right"]:
                        dist = abs(cmid - mid)
                        if best_dist is None or dist < best_dist:
                            best_dist = dist
                            idx = j
                if idx is not None:
                    s2, e2, t2 = merged[idx]
                    merged[idx] = (min(s2, s), max(e2, e), (t2 + " " + text).strip())
                    placed = True
                break
        if not placed:
            merged.append((s, e, text))
    return merged


def _assign_row_to_columns(cols, row_tokens):
    values = {c["label"]: [] for c in cols}
    for (s, e, text) in row_tokens:
        mid = (s + e) / 2
        target = None
        for c in cols:
            if c["left"] <= mid < c["right"]:
                target = c["label"]
                break
        if target is None:
            target = cols[-1]["label"] if cols else "col_1"
        values[target].append(text)
    return {k: " ".join(v).strip() for k, v in values.items()}


def _extract_layout_tables(pypdf_page):
    text = pypdf_page.extract_text(extraction_mode="layout")
    if not text:
        return []
    lines = text.split("\n")

    tables = []
    header_tokens = None
    header_building = False
    rows = []
    gap = 0
    hgap = 0
    headerless_tokens_list = []
    gap_hl = 0

    def flush_table():
        nonlocal header_tokens, rows
        if header_tokens and rows:
            cols = _finalize_header(header_tokens)
            col_labels = [c["label"] for c in cols]
            df = pd.DataFrame(rows, columns=col_labels)
            tables.append(df)
        header_tokens = None
        rows = []

    def flush_headerless():
        nonlocal headerless_tokens_list
        if headerless_tokens_list:
            n_cols = max(len(t) for t in headerless_tokens_list)
            col_labels = [f"col_{i+1}" for i in range(n_cols)]
            data = []
            for toks in headerless_tokens_list:
                vals = [t[2] for t in sorted(toks, key=lambda x: x[0])]
                vals += [""] * (n_cols - len(vals))
                data.append(vals)
            df = pd.DataFrame(data, columns=col_labels)
            tables.append(df)
        headerless_tokens_list = []

    def abandon_header():
        nonlocal header_tokens, header_building, rows, hgap
        header_tokens = None
        header_building = False
        rows = []
        hgap = 0

    for line in lines:
        toks = _tokenize(line)
        if not toks:
            gap += 1
            gap_hl += 1
            if header_building and not rows:
                hgap += 1
                if hgap > 2:
                    abandon_header()
            if gap > 3 and header_tokens is not None and rows:
                flush_table()
            if gap_hl > 3 and headerless_tokens_list:
                flush_headerless()
            continue

        numeric_count = sum(1 for (_, _, t) in toks if _is_numeric_token(t))
        is_header_candidate = (numeric_count == 0) and (len(toks) >= 2)
        is_data_row = numeric_count >= 2

        if is_header_candidate:
            if header_tokens is None:
                flush_headerless()
                header_tokens = list(toks)
                header_building = True
                rows = []
                gap = 0
                hgap = 0
            elif header_building:
                header_tokens = _merge_header_line(header_tokens, toks)
                hgap = 0
            else:
                flush_table()
                header_tokens = list(toks)
                header_building = True
                rows = []
                gap = 0
                hgap = 0
        elif is_data_row:
            if header_tokens is not None:
                cols = _finalize_header(header_tokens)
                row = _assign_row_to_columns(cols, toks)
                rows.append(row)
                header_building = False
                gap = 0
            else:
                headerless_tokens_list.append(toks)
                gap_hl = 0
        else:
            gap += 1
            gap_hl += 1
            if header_building and not rows:
                hgap += 1
                if hgap > 2:
                    abandon_header()
            if gap > 3 and header_tokens is not None and rows:
                flush_table()
            if gap_hl > 3 and headerless_tokens_list:
                flush_headerless()

    flush_table()
    flush_headerless()

    return [t for t in tables if not t.empty]


def _extract_invoice_date(text):
    """Extrait et harmonise la date de facture au format JJ/MM/AAAA."""
    if not text:
        return ""

    # 1. Cas : "FACTURE N° XXX du DD.MM.YYYY" ou "FACTURE N° XXX DU DD/MM/YYYY"
    match = re.search(r'facture\s*(?:n[°o]?\s*[\w-]+)?\s*du\s*(\d{2}[\./-]\d{2}[\./-]\d{4})', text, re.IGNORECASE)
    if match:
        return match.group(1).replace('.', '/').replace('-', '/')

    # 2. Cas : "Date : DD/MM/YYYY" ou "Date: DD.MM.YYYY"
    match = re.search(r'date\s*:\s*(\d{2}[\./-]\d{2}[\./-]\d{4})', text, re.IGNORECASE)
    if match:
        return match.group(1).replace('.', '/').replace('-', '/')

    # 3. Recherche générique si le mot "Date" est suivi d'une date
    match = re.search(r'date[^\n\r]*?(\d{2}[\./-]\d{2}[\./-]\d{4})', text, re.IGNORECASE)
    if match:
        return match.group(1).replace('.', '/').replace('-', '/')

    # 4. Fallback : première date au format JJ/MM/AAAA ou JJ.MM.AAAA trouvée dans la page
    match = re.search(r'\b(\d{2}[\./-]\d{2}[\./-]\d{4})\b', text)
    if match:
        return match.group(1).replace('.', '/').replace('-', '/')

    return ""

# ----------------------------------------------------------------------
# Fonction principale
# ----------------------------------------------------------------------

def extraire_facture_pdf(chemin_pdf, chemin_sortie_excel="facture_extraite.xlsx", progress_callback=None):
    chemin_pdf = Path(chemin_pdf).expanduser()
    if not chemin_pdf.exists() or not chemin_pdf.is_file():
        raise FileNotFoundError(f"Le fichier PDF suivant est introuvable : {chemin_pdf}")

    reader = PdfReader(str(chemin_pdf))
    total_pages = len(reader.pages) or 1
    product_dfs = []
    last_found_date = ""

    with pdfplumber.open(chemin_pdf) as pl_pdf:
        for page_num, (pypdf_page, pl_page) in enumerate(zip(reader.pages, pl_pdf.pages), start=1):
            if progress_callback:
                progress_callback(
                    int(10 + (page_num / total_pages) * 80),
                    f"Analyse de la page {page_num}/{total_pages}"
                )
            # Concaténation des textes des deux extracteurs pour être certain de ne rien rater
            t1 = pl_page.extract_text() or ""
            t2 = pypdf_page.extract_text() or ""
            page_text = t1 + "\n" + t2

            current_date = _extract_invoice_date(page_text)

            if current_date:
                last_found_date = current_date
            else:
                current_date = last_found_date

            # Extraction des tableaux
            tables = _extract_ruled_tables(pl_page)
            if not tables:
                tables = _extract_layout_tables(pypdf_page)

            for df in tables:
                if _is_product_table(df):
                    df_cleaned = _clean_product_rows(df)
                    if not df_cleaned.empty:
                        df_cleaned.insert(0, 'Date Facture', current_date)
                        product_dfs.append(df_cleaned)

    output_path = Path(chemin_sortie_excel)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not product_dfs:
        print("Aucun tableau de produits n'a été détecté.")
        df_empty = pd.DataFrame()
        df_empty.to_excel(output_path, index=False)
        if progress_callback:
            progress_callback(100, "Aucun tableau de produits détecté")
        return df_empty

    df_final = pd.concat(product_dfs, ignore_index=True)

    with pd.ExcelWriter(output_path) as writer:
        df_final.to_excel(writer, sheet_name="Produits", index=False)

    if progress_callback:
        progress_callback(100, f"Extraction réussie : {len(df_final)} ligne(s)")

    print(
        f"✅ Extraction réussie : {len(df_final)} ligne(s) enregistrée(s) "
        f"dans 'Produits' de '{output_path}'."
    )

    return df_final