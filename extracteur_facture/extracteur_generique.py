from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Optional

import pandas as pd
import pdfplumber

STANDARD_COLUMNS = [
    "Date Facture", "Désignation", "Quantité", "Unité",
    "Prix unitaire HT", "Montant net HT", "Taux TVA",
]

# Termes génériques qui signalent des zones hors lignes produits.
SUMMARY_TERMS = (
    "total ht", "total ttc", "total h.t", "total t.t.c", "total transport",
    "net à payer", "net a payer", "montant tva", "total tva", "taux total",
    "sous-total", "sous total", "solde à payer", "solde a payer",
    "reste à payer", "reste a payer", "taxes :", "taxes:", "total transport",
)
NON_PRODUCT_TERMS = (
    "coordonnées bancaires", "coordonnees bancaires", "iban", "bic", "siret", "siren",
    "tva intra", "échéance", "echeance", "référence :", "reference :",
    "type d'opération", "type d'operation", "document de référence", "document de reference",
    "adresse siège", "adresse siege", "code fournisseur", "n° commande", "n° bl",
    "n° commande(s)", "n° bl(s)", "facturé :", "facture :", "page :", "notre iban",
    "taux des pénalités", "taux des penalites", "nos dernières cgv", "nos dernieres cgv",
    "nf525", "e-fac",
)

HEADER_ALIASES = {
    "designation": {"designation", "article", "produit", "description", "libelle", "intitule", "item"},
    "quantity": {"quantite", "qte", "qty", "quantity", "nombre"},
    "unit": {"unite", "uf", "unit", "unites", "conditionnement"},
    "unit_price": {"pu", "prix", "unitaire", "tarif"},
    "amount": {"montant", "net", "amount", "total", "mt", "ht"},
    "vat": {"tva", "vat", "taxe", "taux"},
}

UNIT_WORDS = {
    "kg", "g", "mg", "t", "l", "cl", "ml", "dl", "hl",
    "p", "pc", "pcs", "piece", "pieces", "pièce", "pièces",
    "u", "un", "unité", "unités", "colis", "col", "carton", "cartons",
    "caisse", "caisses", "sac", "sacs", "seau", "bidon", "boîte", "boite", "boites",
    "botte", "barquette", "bac", "palette", "paquet", "lot", "bouteille", "douzaine",
    "douzaines", "sachet", "sachets", "flt", "plateau", "pot", "pots",
}

_NUM_RE = re.compile(r"^[+-]?(?:\d+(?:[\.,]\d+)?|\d{1,3}(?:[ .]\d{3})+(?:[\.,]\d+)?)$")
_PERCENT_RE = re.compile(r"^[+-]?\d+(?:[\.,]\d+)?\s*%$")
_PRICE_RE = re.compile(r"^[+-]?(?:\d+(?:[\.,]\d+)?|\d{1,3}(?:[ .]\d{3})+(?:[\.,]\d+)?)[ ]*€?$", re.I)


def normalize_text(value: str) -> str:
    s = str(value or "")
    s = s.replace("￾", " ").replace("\u00ad", "")
    s = re.sub(r"_+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_key(value: str) -> str:
    s = normalize_text(value).lower()
    table = str.maketrans("éèêëàâîïôùûç", "eeeeaaiioouc")
    return s.translate(table)


def token_key(value: str) -> str:
    return normalize_key(value).strip(" .,:;-_/")


def is_number(value: str) -> bool:
    return bool(_NUM_RE.fullmatch(normalize_text(value).replace("\u00a0", " ").strip()))


def is_price(value: str) -> bool:
    return bool(_PRICE_RE.fullmatch(normalize_text(value).replace("\u00a0", " ")))


def is_percent(value: str) -> bool:
    return bool(_PERCENT_RE.fullmatch(normalize_text(value)))


def is_unit_word(value: str) -> bool:
    return token_key(value) in {token_key(x) for x in UNIT_WORDS}


def is_summary(text: str) -> bool:
    k = normalize_key(text)
    return any(t in k for t in SUMMARY_TERMS)


def is_non_product(text: str) -> bool:
    k = normalize_key(text)
    if not k:
        return True
    return any(t in k for t in NON_PRODUCT_TERMS)


def looks_like_comment(text: str) -> bool:
    k = normalize_key(text)
    # Un commentaire est long et ne ressemble pas à une cellule structurée.
    if len(k.split()) >= 10 and not re.search(r"\d", k):
        return True
    return any(x in k for x in ("je n ai", "je n'ai", "désolé", "desole", "consultez", "retrouvez"))


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float

    @property
    def xmid(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class Line:
    top: float
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in sorted(self.words, key=lambda x: x.x0))

    @property
    def numeric_words(self) -> list[Word]:
        return [w for w in self.words if is_number(w.text) or is_price(w.text) or is_percent(w.text)]


@dataclass
class ColumnModel:
    designation_start: float
    designation_end: float
    quantity_x: float
    unit_x: Optional[float]
    unit_secondary_x: Optional[float]
    unit_price_x: Optional[float]
    vat_x: Optional[float]
    amount_x: Optional[float]


def extract_words(page) -> list[Word]:
    try:
        raw = page.extract_words(
            x_tolerance=1.2, y_tolerance=2.5,
            keep_blank_chars=False, use_text_flow=False,
        )
    except Exception:
        raw = []
    out = []
    for item in raw:
        text = normalize_text(item.get("text", ""))
        if not text or text == "_":
            continue
        out.append(Word(text, float(item["x0"]), float(item["x1"]), float(item["top"]), float(item["bottom"])))
    return out


def group_lines(words: list[Word], tolerance: float = 3.2) -> list[Line]:
    lines: list[Line] = []
    for word in sorted(words, key=lambda w: (w.top, w.x0)):
        if not lines or abs(word.top - lines[-1].top) > tolerance:
            lines.append(Line(word.top, [word]))
        else:
            lines[-1].words.append(word)
    return lines


def header_hit_count(line: Line) -> dict[str, list[Word]]:
    found = {k: [] for k in HEADER_ALIASES}
    for w in line.words:
        tk = token_key(w.text)
        for cat, aliases in HEADER_ALIASES.items():
            if tk in aliases:
                found[cat].append(w)
    return found


def find_header(lines: list[Line], page_width: float) -> Optional[tuple[int, int, ColumnModel]]:
    candidates = []
    for i, line in enumerate(lines):
        # Un header peut s'étendre sur 3 lignes maximum.
        window = []
        for j in range(i, min(i + 5, len(lines))):
            if lines[j].top - line.top <= 48:
                window.append(lines[j])
            else:
                break
        all_words = [w for ln in window for w in ln.words]
        found = {k: [] for k in HEADER_ALIASES}
        for w in all_words:
            tk = token_key(w.text)
            for cat, aliases in HEADER_ALIASES.items():
                if tk in aliases:
                    found[cat].append(w)
        present = {k for k, v in found.items() if v}
        if not {"designation", "quantity"}.issubset(present):
            continue
        # Le vrai tableau comporte généralement aussi prix + montant ou TVA.
        score = 10
        score += 4 * len(present)
        score += 5 if "amount" in present else 0
        score += 4 if "unit_price" in present else 0
        score += 2 if "vat" in present else 0
        if line.top < lines[-1].top * 0.50:
            score += 2
        des_end = max(w.x1 for w in found["designation"])
        if des_end > page_width * 0.70:
            continue

        # Ancre initiale de chaque colonne. Les données permettront ensuite de
        # corriger les décalages entre en-têtes et valeurs.
        qx = min(w.xmid for w in found["quantity"])
        ux = min(w.xmid for w in found["unit"]) if found["unit"] else None

        # Pour les en-têtes multi-mots, ne pas utiliser le premier mot comme
        # ancre : "Prix" est avant les vraies valeurs PU et "HT" est souvent
        # encore plus à gauche du montant. On utilise le mot le plus à droite
        # de chaque groupe sémantique, puis l'inférence sur les données affine.
        upx = max(w.xmid for w in found["unit_price"]) if found["unit_price"] else None
        vx = min(w.xmid for w in found["vat"]) if found["vat"] else None
        ax = max(w.xmid for w in found["amount"]) if found["amount"] else None

        # "MT" est le meilleur marqueur générique pour le montant quand il existe.
        for w in found["amount"]:
            if token_key(w.text) in {"mt", "montant"}:
                if token_key(w.text) == "mt":
                    ax = w.xmid
                break
        candidates.append((score, i, len(window), ColumnModel(min(w.x0 for w in found["designation"]), des_end, qx, ux, None, upx, vx, ax)))

    if not candidates:
        return None
    candidates.sort(key=lambda x: (-x[0], x[1]))
    score, i, _, model = candidates[0]

    # Lignes de header réelles uniquement : celles qui ont au moins 2 marqueurs,
    # ou un libellé composé typique. Cela évite de prendre une ligne "Pièces"
    # comme début de tableau.
    header_end = i
    for j in range(i, min(i + 5, len(lines))):
        hits = header_hit_count(lines[j])
        n = sum(bool(v) for v in hits.values())
        t = normalize_key(lines[j].text)
        if n >= 2 or any(p in t for p in ("prix unitaire", "montant net", "montant ht", "taux tva", "qté livrée", "qte livree")):
            header_end = j
    return i, header_end, model


def invoice_date(text: str, page=None) -> str:
    """Extrait la date d'émission de la facture sans confondre les dates de livraison.

    Ordre de priorité :
    1) date explicitement attachée à « FACTURE ... du/le ... » sur la même ligne ;
    2) libellé « Date : » / « Date » ;
    3) en-tête « DATE CLIENT PAGE » suivi de la date (certaines factures) ;
    4) « Date base » du récapitulatif ;
    5) inspection des caractères uniquement sur la ligne de FACTURE.
    """
    raw = str(text or "").replace("\r", "")

    def fmt(value: str) -> str:
        return value.replace(".", "/").replace("-", "/")

    # 1. « FACTURE N° ... du 07.07.2026 » : même ligne uniquement.
    patterns = (
        r"(?im)^\s*facture\b[^\n]{0,160}?\b(?:du|le)\s*(\d{2}[./-]\d{2}[./-]\d{4})\b",
        r"(?im)^\s*date\s*:?\s*(\d{2}[./-]\d{2}[./-]\d{4})\b",
        r"(?im)^\s*date\s+client\s+page\b[^\n]*\n(?:[^\n]*\n){0,2}?.*?\b(\d{2}[./-]\d{2}[./-]\d{4})\b",
    )
    for pattern in patterns:
        m = re.search(pattern, raw)
        if m:
            return fmt(m.group(1))

    # 2. Libellé DATE et date séparés par quelques champs/lignes.
    m = re.search(
        r"(?im)^\s*date(?:\s+client\s+page|\s+client|\s+page)?\b[^\n]*\n(?:[^\n]*\n){0,2}?.*?\b(\d{2}[./-]\d{2}[./-]\d{4})\b",
        raw,
    )
    if m:
        return fmt(m.group(1))

    # 3. Récapitulatif : « Échéance Date base Règl. » puis deux dates.
    # La seconde est la date de base / émission.
    m = re.search(r"(?is)date\s+base(?P<body>.{0,260})", raw)
    if m:
        dates = re.findall(r"\b(\d{2}[./-]\d{2}[./-]\d{4})\b", m.group("body"))
        if dates:
            return fmt(dates[-1])

    # 4. Fallback générique par caractères, mais uniquement sur la ligne où
    # apparaît « FACTURE », afin de ne jamais récupérer une date de livraison.
    if page is not None:
        try:
            chars = list(page.chars)
            fact = [c for c in chars if normalize_key(c.get("text", "")) == "facture"]
            if fact:
                y = median([float(c["top"]) for c in fact])
                line_chars = [
                    c for c in chars
                    if abs(float(c["top"]) - y) <= 2.5
                ]
                line_chars.sort(key=lambda c: float(c["x0"]))
                candidate = "".join(str(c.get("text", "")) for c in line_chars)
                m = re.search(r"\b(?:du|le)\s*(\d{2}[./-]\d{2}[./-]\d{4})\b", candidate, re.I)
                if m:
                    return fmt(m.group(1))
        except Exception:
            pass

    return ""


def nearest_x(target: float, values: list[float]) -> Optional[float]:
    if not values:
        return None
    return min(values, key=lambda x: abs(x - target))


def infer_columns(lines: list[Line], start: int, model: ColumnModel) -> ColumnModel:
    """Calibre les colonnes sur les lignes qui ressemblent clairement à des articles."""
    samples = []
    for ln in lines[start:start + 50]:
        text = ln.text
        if is_summary(text) or is_non_product(text) or not text:
            continue
        # Une ligne article robuste contient au moins 2 nombres/prix dans la zone droite.
        nums = [w for w in ln.words if is_number(w.text) or is_price(w.text) or is_percent(w.text)]
        if len(nums) >= 2:
            samples.append(ln)
    if not samples:
        return model

    # Position réelle du début des désignations dans les lignes de données.
    # Elle peut être très différente de l'abscisse de l'en-tête (centré,
    # fusionné, présence d'une colonne Ligne/Article, etc.).
    designation_starts = []
    for ln in samples:
        candidates = [
            w.x0 for w in sorted(ln.words, key=lambda w: w.x0)
            if w.xmid < model.quantity_x - 10 and re.search(r"[A-Za-zÀ-ÿ]", w.text)
        ]
        if candidates:
            # On ignore les éventuels marqueurs de début de ligne numériques.
            designation_starts.append(min(candidates))
    if designation_starts:
        model.designation_start = median(designation_starts)

    # X médian des prix candidats : en pratique PU et montant forment 2 colonnes fixes.
    price_xs = []
    for ln in samples:
        for w in ln.words:
            if is_price(w.text) and w.xmid > model.designation_end + 80:
                price_xs.append(w.xmid)
    # Clusters horizontaux.
    clusters: list[list[float]] = []
    for x in sorted(price_xs):
        if not clusters or x - median(clusters[-1]) > 15:
            clusters.append([x])
        else:
            clusters[-1].append(x)
    price_clusters = [median(c) for c in clusters if len(c) >= max(2, len(samples) // 8)]

    # Ne pas confondre un code numérique (ex. "1" dans la colonne TVA) avec un prix.
    # On conserve les ancres fournies par le header, mais les valeurs répétées des
    # lignes produits sont prioritaires pour placer PU et montant.
    if len(price_clusters) >= 2:
        ordered = sorted(price_clusters)
        # Le PU est toujours avant le montant. Si les ancres sont exploitables,
        # on choisit le cluster le plus proche de chacune ; sinon les deux derniers.
        up = min(ordered, key=lambda x: abs(x - model.unit_price_x)) if model.unit_price_x is not None else ordered[-2]
        am = min(ordered, key=lambda x: abs(x - model.amount_x)) if model.amount_x is not None else ordered[-1]
        if up >= am:
            up, am = ordered[-2], ordered[-1]
        model.unit_price_x = up
        model.amount_x = am
    elif len(price_clusters) == 1:
        model.amount_x = price_clusters[0]

    # Quantité : premier nombre significatif à droite de la désignation.
    qxs = []
    for ln in samples:
        ws = sorted(ln.words, key=lambda w: w.x0)
        cands = [w for w in ws if (is_number(w.text) or is_price(w.text)) and w.xmid > model.designation_end + 35]
        # Une valeur proche de l'ancre header est préférée, mais on conserve les signes négatifs.
        if cands:
            w = min(cands, key=lambda z: abs(z.xmid - model.quantity_x))
            qxs.append(w.xmid)
    if qxs:
        model.quantity_x = median(qxs)

    # Unité : premier mot d'unité après la quantité, avant PU.
    uxs = []
    secondary = []
    for ln in samples:
        ws = sorted(ln.words, key=lambda w: w.x0)
        qty = nearest_word(ws, model.quantity_x, numeric=True)
        if qty is None:
            continue
        for w in ws:
            if w.x0 < qty.x1 - 1:
                continue
            if model.unit_price_x is not None and w.xmid >= model.unit_price_x - 15:
                break
            if is_unit_word(w.text):
                uxs.append(w.xmid)
                break
            # Certaines factures ont une unité collée : 12kg / 12p.
            m = re.fullmatch(r"\d+(?:[\.,]\d+)?(kg|g|l|p|pc|pcs)", token_key(w.text), re.I)
            if m:
                uxs.append(w.xmid)
                break
    if uxs:
        model.unit_x = median(uxs)

    # TVA : on cherche les pourcentages réels, pas les codes comme F 1.
    vxs = [w.xmid for ln in samples for w in ln.words if is_percent(w.text)]
    if vxs:
        model.vat_x = median(vxs)

    return model


def nearest_word(words: list[Word], x: float, numeric: bool = False) -> Optional[Word]:
    candidates = []
    for w in words:
        if numeric and not (is_number(w.text) or is_price(w.text)):
            continue
        candidates.append(w)
    return min(candidates, key=lambda w: abs(w.xmid - x)) if candidates else None


def _is_quantity_candidate(w: Word) -> bool:
    return is_number(w.text) or is_price(w.text)


def _compact_unit_parts(text: str) -> Optional[list[str]]:
    t = token_key(text)
    m = re.fullmatch(r"(\d+(?:[\.,]\d+)?)(kg|g|mg|l|cl|ml|dl|hl|p|pc|pcs|pu|u|un|col|colis|carton|cartons|sac|sacs|caisse|caisses|botte|barquette|bac|flt|plateau|pot|pots)", t, re.I)
    if m:
        return [m.group(1), m.group(2)]
    return None


def parse_product_line(line: Line, model: ColumnModel) -> Optional[dict[str, str]]:
    ws = sorted(line.words, key=lambda w: w.x0)
    text = line.text
    if not text or is_summary(text) or is_non_product(text):
        return None

    # Une vraie ligne produit doit commencer dans la zone de désignation et
    # posséder une structure numérique à droite : quantité + prix + montant.
    if not any(w.x0 >= model.designation_start - 5 and w.xmid < model.designation_end + 10 for w in ws):
        return None

    numeric = [w for w in ws if _is_quantity_candidate(w)]
    numeric_right = [w for w in numeric if w.xmid >= model.designation_end - 5]
    if not numeric_right:
        return None

    # Quantité : priorité à l'ancre de la colonne, mais seulement aux nombres
    # situés avant le PU. Cela évite de prendre le montant comme quantité.
    pre_price = [w for w in numeric_right if model.unit_price_x is None or w.xmid < model.unit_price_x - 10]
    quantity = nearest_word(pre_price or numeric_right, model.quantity_x, numeric=True)
    if quantity is None:
        return None

    # Les prix sont les valeurs explicitement placées dans les colonnes de prix.
    prices = [w for w in ws if is_price(w.text) and w.xmid > quantity.x1 - 3]
    if len(prices) < 2:
        return None

    pu = nearest_word(prices, model.unit_price_x, numeric=False) if model.unit_price_x is not None else None
    amount = nearest_word(prices, model.amount_x, numeric=False) if model.amount_x is not None else None

    # Sécurité géométrique : PU doit être à gauche du montant.
    if pu is None or amount is None or pu is amount or amount.xmid <= pu.xmid:
        ordered_prices = sorted(prices, key=lambda w: w.xmid)
        pu, amount = ordered_prices[-2], ordered_prices[-1]

    if amount.xmid <= pu.xmid:
        return None

    # Désignation : uniquement les mots de la vraie zone Désignation.
    left = [w for w in ws if w.x0 >= model.designation_start - 4 and w.xmid < model.quantity_x - 10]
    designation = " ".join(w.text for w in left).strip()
    # Retire le couple Ligne/Article au début quand il existe.
    designation = re.sub(r"^\s*\d+\s*/\s*\S+\s+", "", designation)
    if not designation or len(designation) < 2:
        return None

    # Unité : on regarde toutes les valeurs entre quantité et PU.
    # Cela couvre à la fois '12 p', '15 KG', '12kg', '12 pieces' et 'COL'.
    between = [w for w in ws if quantity.x1 - 2 <= w.x0 and w.xmid < pu.xmid - 8]
    unit_parts: list[str] = []
    for idx, w in enumerate(between):
        compact = _compact_unit_parts(w.text)
        if compact:
            unit_parts = compact
            break
        if is_unit_word(w.text):
            # Si un nombre se trouve juste avant, il appartient au conditionnement.
            if idx > 0 and is_number(between[idx - 1].text):
                unit_parts = [between[idx - 1].text, w.text]
            else:
                unit_parts = [w.text]
            break

    # Certaines factures séparent quantité et unité, mais sans mot d'unité :
    # on conserve alors le nombre immédiatement après la quantité.
    if not unit_parts:
        extra = [w.text for w in between if is_number(w.text) and w is not quantity]
        if len(extra) == 1:
            unit_parts = [extra[0]]

    vat = ""
    pct = [w for w in ws if is_percent(w.text)]
    if pct:
        target = model.vat_x
        vat_word = min(pct, key=lambda w: abs(w.xmid - target)) if target is not None else pct[-1]
        vat = vat_word.text.replace(" ", "")

    return {
        "Désignation": normalize_text(designation),
        "Quantité": normalize_text(quantity.text),
        "Unité": normalize_text(" ".join(unit_parts)),
        "Prix unitaire HT": normalize_text(pu.text),
        "Montant net HT": normalize_text(amount.text),
        "Taux TVA": vat,
        "__score": 0.30 + 0.20 + 0.18 + 0.18 + (0.10 if unit_parts else 0.0) + (0.04 if vat else 0.0),
    }


def continuation_of_row(row: dict[str, str], line: Line, model: ColumnModel) -> bool:
    text = line.text
    if not text or is_summary(text) or is_non_product(text) or looks_like_comment(text):
        return False

    # Si la ligne contient un prix/montant, elle n'est pas une simple continuation.
    if len([w for w in line.words if is_price(w.text) or is_percent(w.text)]) >= 1:
        return False

    # Un fragment d'unité peut être sur la ligne suivante (pieces, Pièces).
    units = [w.text for w in line.words if is_unit_word(w.text)]
    if units and all(w.xmid >= model.quantity_x - 20 for w in line.words):
        row["Unité"] = normalize_text(f"{row.get('Unité', '')} {' '.join(units)}")
        return True

    # Fragment de désignation : uniquement à gauche de la quantité.
    left_words = [w for w in line.words if w.xmid < model.quantity_x - 12 and re.search(r"[A-Za-zÀ-ÿ]", w.text)]
    if not left_words:
        return False

    fragment = normalize_text(" ".join(w.text for w in left_words))
    if not fragment or re.search(r"\b\d{5}\b", fragment):
        return False
    if len(fragment) > 100 and len(fragment.split()) >= 10:
        return False

    # Certains fournisseurs impriment le pays seul sur la ligne suivante,
    # tandis qu'un vrai complément de désignation contient généralement
    # plusieurs mots. On garde toutefois les fragments courts lorsque leur
    # position correspond à la colonne Désignation (cas "Gros" chez certains PDF).
    first_x = min(w.x0 for w in left_words)
    if first_x < model.designation_start - 15 and len(fragment.split()) <= 2:
        return False

    row["Désignation"] = normalize_text(f"{row['Désignation']} {fragment}")
    return True


def extract_page(page, date: str) -> list[dict[str, str]]:
    words = extract_words(page)
    lines = group_lines(words)
    header = find_header(lines, page.width)
    if header is None:
        return []
    h_start, h_end, model = header
    model = infer_columns(lines, h_end + 1, model)

    rows = []
    current = None
    for line in lines[h_end + 1:]:
        text = line.text
        if not text:
            continue
        if is_summary(text):
            if current is not None and current.get("__score", 0) >= 0.70:
                current["Date Facture"] = date
                current.pop("__score", None)
                rows.append(current)
                current = None
            continue
        # Une fois un pied de page détecté, on ne cherche plus de produit sous celui-ci.
        k = normalize_key(text)
        if "nf525" in k or "e-fac" in k or k.startswith("page :"):
            break
        # Ne jamais classer les lignes administratives comme produit.
        if is_non_product(text):
            continue
        parsed = parse_product_line(line, model)
        if parsed:
            if current is not None and current.get("__score", 0) >= 0.70:
                current["Date Facture"] = date
                current.pop("__score", None)
                rows.append(current)
            current = parsed
            continue
        if current is not None:
            continuation_of_row(current, line, model)

    if current is not None and current.get("__score", 0) >= 0.70:
        current["Date Facture"] = date
        current.pop("__score", None)
        rows.append(current)
    return rows


def extract_fallback_page(page, date: str) -> list[dict[str, str]]:
    """Fallback texte : conservateur et uniquement utilisé si aucun header exploitable."""
    out = []
    text = page.extract_text(x_tolerance=1.5, y_tolerance=2.5) or ""
    for raw in text.splitlines():
        s = normalize_text(raw)
        if not s or is_summary(s) or is_non_product(s):
            continue
        m = re.match(r"^(.+?)\s+([+-]?\d+(?:[.,]\d+)?)\s+(\S+)\s+(.+?)\s+(.+?)\s+(\d+(?:[.,]\d+)?\s*%)$", s)
        if not m:
            continue
        designation, qty, unit, pu, amount, vat = m.groups()
        nums = re.findall(r"[+-]?\d+(?:[.,]\d+)?", pu + " " + amount)
        if len(nums) < 2:
            continue
        out.append({
            "Date Facture": date,
            "Désignation": normalize_text(designation),
            "Quantité": qty,
            "Unité": unit,
            "Prix unitaire HT": normalize_text(pu),
            "Montant net HT": normalize_text(amount),
            "Taux TVA": vat.replace(" ", ""),
        })
    return out


def extraire_facture_pdf(chemin_pdf: str | Path, chemin_sortie_excel: str | Path = "facture_extraite.xlsx", progress_callback=None) -> pd.DataFrame:
    pdf_path = Path(chemin_pdf).expanduser()
    output_path = Path(chemin_sortie_excel).expanduser()
    if not pdf_path.exists() or not pdf_path.is_file():
        raise FileNotFoundError(f"Fichier PDF introuvable : {pdf_path}")

    all_rows: list[dict[str, str]] = []
    last_date = ""
    with pdfplumber.open(pdf_path) as pdf:
        pages = list(pdf.pages)
        page_texts = [pg.extract_text() or "" for pg in pages]

        for page_num, page in enumerate(pages, start=1):
            text = page_texts[page_num - 1]
            d = invoice_date(text, page)

            # Si la première page d'une facture a une date corrompue, le PDF
            # contient souvent la vraie date sur la page récapitulative suivante
            # via « Date base ». On regarde les deux pages suivantes uniquement
            # lorsqu'aucune date n'a été trouvée sur la page courante.
            if not d:
                for offset in (1, 2):
                    idx = page_num - 1 + offset
                    if idx >= len(pages):
                        break
                    candidate_text = page_texts[idx]
                    d = invoice_date(candidate_text)
                    if d and re.search(r"date\s+base", normalize_key(candidate_text), re.I):
                        break
                    if re.search(r"total\s+(?:ht|ttc)|net\s+à\s+payer|net\s+a\s+payer", normalize_key(candidate_text), re.I):
                        # Cette page ressemble déjà à une page récapitulative ; inutile
                        # de continuer à chercher plus loin pour cette facture.
                        if d:
                            break
                    d = ""

            if d:
                last_date = d
            d = d or last_date
            rows = extract_page(page, d)
            if not rows:
                rows = extract_fallback_page(page, d)
            all_rows.extend(rows)
            if progress_callback:
                progress_callback(int(10 + page_num / max(len(pdf.pages), 1) * 80), f"Analyse de la page {page_num}/{len(pdf.pages)}")

    # Nettoyage final : colonnes fixes, pas de score dans Excel.
    final_rows = []
    for row in all_rows:
        clean = {c: normalize_text(row.get(c, "")) for c in STANDARD_COLUMNS}
        if not clean["Désignation"]:
            continue
        final_rows.append(clean)
    df = pd.DataFrame(final_rows, columns=STANDARD_COLUMNS)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Produits", index=False)
    if progress_callback:
        progress_callback(100, f"Extraction réussie : {len(df)} ligne(s)")
    print(f"Extraction réussie : {len(df)} ligne(s) enregistrée(s) dans '{output_path}'.")
    return df