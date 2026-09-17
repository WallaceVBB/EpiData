from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from statistics import median

import pandas as pd
import pytesseract

from utils import TESSDATA_DIR, TESSERACT_EXE

# --- Paramètres OCR ---------------------------------------------------------

OCR_DPI = 600
OCR_LANG = "fra+eng"
OCR_MIN_WORDS_FOR_TEXT_LAYER = 5
OCR_MIN_CONFIDENCE = 20

OCR_TESSDATA_CONFIG = f'--tessdata-dir {TESSDATA_DIR}'


def configurer_tesseract() -> bool:
    """Configure Tesseract fourni avec EpiData."""

    tesseract_exe = Path(TESSERACT_EXE)
    tessdata_dir = Path(TESSDATA_DIR)

    if not tesseract_exe.is_file():
        print(f"[OCR] tesseract.exe introuvable : {tesseract_exe}")
        return False

    if not tessdata_dir.is_dir():
        print(f"[OCR] dossier tessdata introuvable : {tessdata_dir}")
        return False

    try:
        pytesseract.pytesseract.tesseract_cmd = str(tesseract_exe)

        return True

    except Exception as e:
        print(
            f"[OCR] Tesseract inutilisable : "
            f"{type(e).__name__}: {e}"
        )
        return False


_OCR_CONFIGURED = configurer_tesseract()

STANDARD_COLUMNS = [
    "Date Facture", "Désignation", "Quantité", "Unité", "Nb. colis", "Qté Livrée",
    "Prix unitaire HT", "Montant net HT", "Taux TVA", "Source extraction",
]

# Termes génériques qui signalent des zones hors lignes produits.
SUMMARY_TERMS = (
    "total ht", "total ttc", "total h.t", "total t.t.c", "total transport",
    "net à payer", "net a payer", "montant tva", "total tva", "taux total",
    "sous-total", "sous total", "solde à payer", "solde a payer",
    "reste à payer", "reste a payer", "taxes :", "taxes:", "total transport",
    "répartition produit", "repartition produit", "détail de la tva", "detail de la tva",
)
NON_PRODUCT_TERMS = (
    "coordonnées bancaires", "coordonnees bancaires", "iban", "bic", "siret", "siren",
    "tva intra", "échéance", "echeance", "référence :", "reference :",
    "type d'opération", "type d'operation", "document de référence", "document de reference",
    "adresse siège", "adresse siege", "code fournisseur", "n° commande", "n° bl",
    "n° commande(s)", "n° bl(s)", "facturé :", "facture :", "page :", "notre iban",
    "taux des pénalités", "taux des penalites", "nos dernières cgv", "nos dernieres cgv",
    "nf525", "e-fac","dlc:", "dlc :", "ddm:", "ddm :",
)

HEADER_ALIASES = {
    "designation": {"designation", "article", "produit", "description", "libelle", "intitule", "item"},
    "quantity": {"quantite", "qte", "qty", "quantity", "nombre"},
    "unit": {"unite", "uf", "unit", "unites", "conditionnement"},
    "package_count": {"colis", "colisage"},
    "delivered_quantity": {"livree", "livre", "livraison"},
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

PACKAGE_UNIT_WORDS = {"co", "col", "colis"}

_NUM_RE = re.compile(r"^[+-]?(?:\d+(?:[\.,]\d+)?|\d{1,3}(?:[ .]\d{3})+(?:[\.,]\d+)?)$")
_PERCENT_RE = re.compile(r"^[+-]?\d+(?:[\.,]\d+)?\s*%$")
_PRICE_RE = re.compile(r"^[+-]?(?:\d+(?:[\.,]\d+)?|\d{1,3}(?:[ .]\d{3})+(?:[\.,]\d+)?)[ .]*€?$", re.IGNORECASE)

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


def is_plausible_price(w: Word) -> bool:
    """Comme `is_price`, mais plus strict pour les mots issus de l'OCR.

    Sur des scans bruités, une ligne de tableau ou une tache peut être lue
    par erreur comme un chiffre isolé ("2"), ce qui pollue la sélection du
    prix unitaire / montant. Un vrai montant OCR a soit un séparateur
    décimal, soit un symbole "€" collé, soit au moins 2 chiffres — un
    chiffre unique et isolé n'est jamais un montant plausible dans ce
    contexte (Prix unitaire HT / Montant net HT sont toujours à 2 décimales).
    """
    if not is_price(w.text):
        return False
    if not getattr(w, "is_ocr", False):
        return True
    digits = re.sub(r"[^0-9]", "", w.text)
    return len(digits) >= 2 or bool(re.search(r"[.,]", w.text))


def is_ocr_zero_amount(value: str) -> bool:
    """Reconnaît les variantes OCR très caractéristiques de "0,00€" observées
    sur les lignes à quantité livrée nulle (ex. "D00E", "DODE", "DO00€E") :
    Tesseract confond fréquemment 0/O/D sur ce petit montant, quelle que
    soit la résolution utilisée. Le motif est volontairement strict (2 à 5
    caractères pris uniquement dans {D,0,O,o}, suivis d'un éventuel €/E/.)
    pour ne jamais confondre avec d'autres tokens de 2-3 lettres du tableau
    (CO, KG, DOM, DLC...).
    """
    return bool(_OCR_ZERO_AMOUNT_RE.match(normalize_text(value)))


_OCR_ZERO_AMOUNT_RE = re.compile(r"^[D0Oo]{2,5}[€E.]{0,3}$")

def is_unit_word(value: str) -> bool:
    return token_key(value) in {token_key(x) for x in UNIT_WORDS}


_TERM_BOUNDARY_CACHE: dict[str, re.Pattern] = {}


def _contains_any_term(text: str, terms: tuple[str, ...]) -> bool:
    """Comme `term in normalize_key(text)`, mais avec des frontières de mots :
    évite les faux positifs tels que "bic" (code bancaire) qui matcherait par
    erreur à l'intérieur de "bicolore".
    """
    k = normalize_key(text)
    if not k:
        return False
    for term in terms:
        pattern = _TERM_BOUNDARY_CACHE.get(term)
        if pattern is None:
            pattern = re.compile(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])")
            _TERM_BOUNDARY_CACHE[term] = pattern
        if pattern.search(k):
            return True
    return False


def is_summary(text: str) -> bool:
    return _contains_any_term(text, SUMMARY_TERMS)


def is_non_product(text: str) -> bool:
    k = normalize_key(text)
    if not k:
        return True
    return _contains_any_term(text, NON_PRODUCT_TERMS)


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
    is_ocr: bool = False

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
    unit_x: float | None
    unit_secondary_x: float | None
    unit_price_x: float | None
    vat_x: float | None
    amount_x: float | None
    package_count_x: float | None = None
    delivered_quantity_x: float | None = None


def _otsu_threshold(arr) -> int:
    """Seuil binaire optimal (méthode d'Otsu), sans dépendance externe.

    Maximise la variance inter-classe entre pixels "fond" et "texte".
    Contrairement à un seuil codé en dur, s'adapte automatiquement à la
    luminosité du scan (contrairement à ImageOps.autocontrast, qui étire le
    contraste existant mais n'aplatit pas les fonds gris/zébrés utilisés par
    certains fournisseurs pour distinguer les lignes du tableau — ce qui les
    rendait souvent illisibles pour Tesseract).
    """
    import numpy as np

    hist, _ = np.histogram(arr, bins=256, range=(0, 256))
    total = arr.size
    sum_all = np.dot(np.arange(256), hist)
    sumB = 0.0
    wB = 0.0
    max_var = 0.0
    threshold = 128
    for i in range(256):
        wB += hist[i]
        if wB == 0:
            continue
        wF = total - wB
        if wF == 0:
            break
        sumB += i * hist[i]
        mB = sumB / wB
        mF = (sum_all - sumB) / wF
        var_between = wB * wF * (mB - mF) ** 2
        if var_between > max_var:
            max_var = var_between
            threshold = i
    return threshold


def render_page_image(page, dpi: int = OCR_DPI):
    """Rasterise une page pdfplumber en image PIL, avec mise en cache sur la
    page elle-même pour éviter de rasteriser deux fois (une fois pour les
    mots, une fois pour le texte brut de secours utilisé par invoice_date).

    L'image est binarisée (niveaux de gris -> noir/blanc pur par seuil
    d'Otsu) après sur-échantillonnage, car certaines impriment un fond 
    zébré gris/blanc en alternance sur les lignes du tableau produits. 
    La binarisation par seuil aplatit tous les fonds (gris ou blancs)
     en blanc pur et ne garde que le texte en noir, ce qui donne un
     contraste maximal quelle que soit la couleur de fond de la ligne.
    """
    import numpy as np

    cache = getattr(page, "_ocr_image_cache", None)
    if cache is not None and cache.get("dpi") == dpi:
        return cache["image"]
    image = page.to_image(resolution=dpi).original
    try:
        from PIL import Image as PILImage
        gray = image.convert("L")
        w, h = gray.size
        gray = gray.resize((w * 2, h * 2), PILImage.LANCZOS)
        arr = np.array(gray)
        t = _otsu_threshold(arr)
        bw = np.where(arr > t, 255, 0).astype("uint8")
        image = PILImage.fromarray(bw)
    except Exception:
        pass
    page._ocr_image_cache = {"dpi": dpi, "image": image}
    return image


def _ocr_data_from_image(image, lang: str = OCR_LANG):
    config = f'--psm 4 {OCR_TESSDATA_CONFIG}'
    try:
        return pytesseract.image_to_data(
            image,
            lang=lang,
            config=config,
            output_type=pytesseract.Output.DICT,
        )
    except Exception as e:
        print(f"[OCR] Erreur image_to_data : "
              f"{type(e).__name__}: {e}")
        return None


def _ocr_words_from_data(data, dpi: int = OCR_DPI) -> list[Word]:
    scale = 72.0 / (dpi * 2)
    if data is None:
        return []
    n = len(data.get("text", []))
    raw_words = []
    for i in range(n):
        text = normalize_text(data["text"][i])
        if not text or text == "_":
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if conf < OCR_MIN_CONFIDENCE:
            continue
        raw_words.append({
            "text": text,
            "left": float(data["left"][i]),
            "top": float(data["top"][i]),
            "width": float(data["width"][i]),
            "height": float(data["height"][i]),
            "line_key": (data["block_num"][i], data["par_num"][i], data["line_num"][i]),
        })

    if not raw_words:
        return []

    # Moyenne du "top" par ligne Tesseract, pour aligner tous les mots d'une
    # même ligne malgré le bruit pixel par pixel.
    line_tops: dict[tuple, list[float]] = {}
    for w in raw_words:
        line_tops.setdefault(w["line_key"], []).append(w["top"])
    line_avg_top = {k: sum(v) / len(v) for k, v in line_tops.items()}

    out: list[Word] = []
    for w in raw_words:
        top = line_avg_top[w["line_key"]]
        out.append(Word(
            w["text"],
            w["left"] * scale,
            (w["left"] + w["width"]) * scale,
            top * scale,
            (top + w["height"]) * scale,
            is_ocr=True,
        ))
    return out


def _ocr_text_from_data(data) -> str:
    if data is None:
        return ""

    lines: dict[tuple, list[str]] = {}
    line_order: list[tuple] = []
    for i, value in enumerate(data.get("text", [])):
        text = normalize_text(value)
        if not text:
            continue
        key = (
            data["block_num"][i],
            data["par_num"][i],
            data["line_num"][i],
        )
        if key not in lines:
            lines[key] = []
            line_order.append(key)
        lines[key].append(text)
    return "\n".join(" ".join(lines[key]) for key in line_order)


def ocr_page_from_image(
    image,
    dpi: int = OCR_DPI,
    lang: str = OCR_LANG,
) -> tuple[list[Word], str]:
    """Effectue une seule passe Tesseract pour les mots et le texte brut."""
    data = _ocr_data_from_image(image, lang)
    return _ocr_words_from_data(data, dpi), _ocr_text_from_data(data)


def ocr_words_from_image(image, dpi: int = OCR_DPI, lang: str = OCR_LANG) -> list[Word]:
    words, _ = ocr_page_from_image(image, dpi, lang)
    return words


def ocr_text_from_image(image, lang: str = OCR_LANG) -> str:
    _, text = ocr_page_from_image(image, OCR_DPI, lang)
    return text


def _cached_ocr_page(page, ocr_dpi: int, ocr_lang: str) -> tuple[list[Word], str]:
    cache = getattr(page, "_ocr_result_cache", None)
    cache_key = (ocr_dpi, ocr_lang)
    if cache is not None and cache.get("key") == cache_key:
        return cache["words"], cache["text"]

    image = render_page_image(page, ocr_dpi)
    words, text = ocr_page_from_image(image, ocr_dpi, ocr_lang)
    page._ocr_result_cache = {
        "key": cache_key,
        "words": words,
        "text": text,
    }
    return words, text


def extract_words(page, ocr_dpi: int = OCR_DPI, ocr_lang: str = OCR_LANG) -> list[Word]:
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

    if len(out) >= OCR_MIN_WORDS_FOR_TEXT_LAYER:
        return out

    # Page probablement scannée (image, pas de couche de texte exploitable) :
    # on bascule sur l'OCR. Si l'OCR échoue ou n'est pas disponible, on
    # retombe sur ce que le texte natif a pu donner (souvent rien).
    if _OCR_CONFIGURED:
        try:
            ocr_out, _ = _cached_ocr_page(page, ocr_dpi, ocr_lang)
            if len(ocr_out) > len(out):
                page._used_ocr = True
                return ocr_out
        except Exception:
            pass
    return out


def page_text(page, ocr_dpi: int = OCR_DPI, ocr_lang: str = OCR_LANG) -> str:
    """Texte complet d'une page : couche native si elle est exploitable,
    sinon texte obtenu par OCR. Utilisé pour la recherche de la date de
    facture (invoice_date) et le fallback de secours (extract_fallback_page).
    """
    try:
        text = page.extract_text(x_tolerance=1.5, y_tolerance=2.5) or ""
    except Exception:
        text = ""
    if len(re.sub(r"\s", "", text)) >= 20:
        return text

    if _OCR_CONFIGURED:
        try:
            _, ocr_text = _cached_ocr_page(page, ocr_dpi, ocr_lang)
            if len(re.sub(r"\s", "", ocr_text)) > len(re.sub(r"\s", "", text)):
                page._used_ocr = True
                return ocr_text
        except Exception:
            pass
    return text

_PRODUCT_CODE_IN_TEXT_RE = re.compile(r"\bV\d{4}\b")

def group_lines(words: list[Word], tolerance: float = 3.2) -> list[Line]:
    lines: list[Line] = []
    for word in sorted(words, key=lambda w: (w.top, w.x0)):
        same = lines and abs(word.top - lines[-1].top) <= tolerance
        # Si le mot courant est un code produit, ne pas le coller à la ligne
        # précédente : elle contient probablement l'en-tête du tableau.
        if same and _PRODUCT_CODE_IN_TEXT_RE.search(word.text) and \
           not _PRODUCT_CODE_IN_TEXT_RE.search(lines[-1].text):
            same = False
        if not same:
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

_PRODUCT_CODE_RE = re.compile(r"\bV\d{4}\b")
_BL_RE = re.compile(r"\bBL\b\s*N[°o]", re.IGNORECASE)
_DELIVERY_GROUP_RE = re.compile(
    r"(?i)\bbon de livraison\b|\blivr[eé]\s+le\s+\d{2}[./-]\d{2}[./-]\d{4}"
)

def _looks_like_product_start(text: str) -> bool:
    t = normalize_text(text)
    if _PRODUCT_CODE_RE.search(t):
        return True
    if _BL_RE.search(t):
        return True
    if _DELIVERY_GROUP_RE.search(t):
        return True
    return False

def find_header(lines: list[Line], page_width: float) -> tuple[int, int, ColumnModel] | None:
    candidates = []
    for i, line in enumerate(lines):
        # Un header peut s'étendre sur 3 lignes maximum.
        window = []
        for j in range(i, min(i + 5, len(lines))):
            if lines[j].top - line.top > 48:
                break
            if _looks_like_product_start(lines[j].text):
                break
            window.append(lines[j])
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
        if _looks_like_product_start(line.text):
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
        pcx = min(w.xmid for w in found["package_count"]) if found["package_count"] else None
        dqx = min(w.xmid for w in found["delivered_quantity"]) if found["delivered_quantity"] else None
        candidates.append((score, i, len(window), ColumnModel(
            min(w.x0 for w in found["designation"]), des_end, qx, ux, None,
            upx, vx, ax, pcx, dqx,
        )))

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
                m = re.search(r"\b(?:du|le)\s*(\d{2}[./-]\d{2}[./-]\d{4})\b", candidate, re.IGNORECASE)
                if m:
                    return fmt(m.group(1))
        except Exception:
            pass

    return ""


def nearest_x(target: float, values: list[float]) -> float | None:
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
            m = re.fullmatch(r"\d+(?:[\.,]\d+)?(kg|g|l|p|pc|pcs)", token_key(w.text), re.IGNORECASE)
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


def nearest_word(words: list[Word], x: float, numeric: bool = False) -> Word | None:
    candidates = []
    for w in words:
        if numeric and not (is_number(w.text) or is_price(w.text)):
            continue
        candidates.append(w)
    return min(candidates, key=lambda w: abs(w.xmid - x)) if candidates else None


def _is_quantity_candidate(w: Word) -> bool:
    return is_number(w.text) or is_price(w.text)


def _compact_unit_parts(text: str) -> list[str] | None:
    t = token_key(text)
    m = re.fullmatch(r"(\d+(?:[\.,]\d+)?)(kg|g|mg|l|cl|ml|dl|hl|p|pc|pcs|pu|u|un|col|colis|carton|cartons|sac|sacs|caisse|caisses|botte|barquette|bac|flt|plateau|pot|pots)", t, re.IGNORECASE)
    if m:
        return [m.group(1), m.group(2)]
    return None


def _is_package_quantity_candidate(word: Word) -> bool:
    if _is_quantity_candidate(word):
        return True
    return bool(re.fullmatch(
        r"\d+(?:[\.,]\d+)?(?:co|col|colis)",
        token_key(word.text),
        re.IGNORECASE,
    ))


def _column_value_with_unit(
    words: list[Word],
    value: Word | None,
    unit_words: set[str],
    right_limit: float | None = None,
) -> str:
    if value is None:
        return ""

    compact = re.fullmatch(
        r"(\d+(?:[\.,]\d+)?)(co|col|colis)",
        token_key(value.text),
        re.IGNORECASE,
    )
    if compact and unit_words == PACKAGE_UNIT_WORDS:
        return normalize_text(f"{compact.group(1)} {compact.group(2).upper()}")

    normalized_units = {token_key(item) for item in unit_words}
    for word in sorted(words, key=lambda item: item.x0):
        if word.x0 < value.x1 - 2:
            continue
        if right_limit is not None and word.xmid >= right_limit:
            continue
        if token_key(word.text) in normalized_units:
            return normalize_text(f"{value.text} {word.text}")
    return normalize_text(value.text)

def _strip_origine_suffix(words: list[Word]) -> list[Word]:
    words = sorted(words, key=lambda w: w.x0)
    for i, w in enumerate(words):
        if token_key(w.text) == "origine":
            return words[:i]
    return words

def parse_product_line(line: Line, model: ColumnModel) -> dict[str, str] | None:
    ws = _strip_origine_suffix(line.words)
    text = " ".join(w.text for w in ws)
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
    # On inclut aussi les variantes OCR très caractéristiques de "0,00€"
    # (ex. "D00E", "DODE") : sur les lignes à quantité livrée nulle, ce
    # montant est presque toujours lu comme des lettres D/O plutôt que des
    # chiffres, et le rejeter fait perdre la ligne entière faute d'un
    # deuxième prix.
    prices = [w for w in ws if is_plausible_price(w) and w.xmid > quantity.x1 - 3]
    prices += [
        Word("0,00€", w.x0, w.x1, w.top, w.bottom, is_ocr=w.is_ocr)
        for w in ws
        if w.xmid > quantity.x1 - 3 and not is_plausible_price(w) and is_ocr_zero_amount(w.text)
    ]
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

    package_count = None
    if model.package_count_x is not None:
        package_candidates = [
            w for w in ws
            if w.xmid > quantity.x1 - 2
            and w.xmid < pu.xmid - 10
            and _is_package_quantity_candidate(w)
            and w is not quantity
        ]
        if package_candidates:
            package_count = min(
                package_candidates,
                key=lambda w: abs(w.xmid - model.package_count_x),
            )

    delivered_quantity = None
    if model.delivered_quantity_x is not None:
        delivered_candidates = [
            w for w in ws
            if w.xmid > quantity.x1 - 2
            and w.xmid < pu.xmid - 10
            and _is_quantity_candidate(w)
            and w is not quantity
        ]
        if delivered_candidates:
            delivered_quantity = min(
                delivered_candidates,
                key=lambda w: abs(w.xmid - model.delivered_quantity_x),
            )

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
        "Nb. colis": _column_value_with_unit(
            ws, package_count, PACKAGE_UNIT_WORDS,
            right_limit=model.delivered_quantity_x,
        ),
        "Qté Livrée": _column_value_with_unit(
            ws, delivered_quantity, UNIT_WORDS,
            right_limit=model.unit_price_x,
        ),
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
    source = "OCR (à vérifier)" if getattr(page, "_used_ocr", False) else "Texte natif"
    lines = group_lines(words)
    header = find_header(lines, page.width)
    if header is None:
        return []
    h_start, h_end, model = header
    model = infer_columns(lines, h_end + 1, model)

    rows = []
    current = None

    body_lines = lines[h_end + 1:]
    for idx, raw_line in enumerate(body_lines):
        stripped = _strip_origine_suffix(raw_line.words)
        if not stripped:
            continue
        line = Line(raw_line.top, stripped)
        text = line.text
        if not text:
            continue
        if is_summary(text):
            if current is not None and current.get("__score", 0) >= 0.70:
                current["Date Facture"] = date
                current["Source extraction"] = source
                current.pop("__score", None)
                rows.append(current)
                current = None
            continue
        k = normalize_key(text)
        if "nf525" in k or "e-fac" in k or k.startswith("page :"):
            break
        if is_non_product(text):
            continue
        parsed = parse_product_line(line, model)

        # Repêchage : sur les scans bruités, les colonnes chiffrées d'une
        # ligne produit peuvent être détectées par Tesseract comme
        # appartenant à la ligne suivante (typiquement la ligne "Origine :"),
        # à cause d'un léger décalage vertical interne à Tesseract. On ne
        # récupère que les valeurs numériques de la ligne suivante situées
        # dans la zone des colonnes chiffrées (jamais son texte) — et
        # seulement si la ligne courante ressemble à un début de produit
        # (code Vxxxx ou "- NOM EN MAJUSCULES"), pour ne pas perturber les
        # lignes déjà correctement reconnues.
        looks_like_product = bool(
            _PRODUCT_CODE_RE.search(text) or re.search(r"-\s*[A-ZÀ-Ÿ]{3,}", text)
        )
        if parsed is None and looks_like_product and idx + 1 < len(body_lines):
            next_line = body_lines[idx + 1]
            if not is_summary(next_line.text):
                extra_numeric = [
                    w for w in next_line.words
                    if w.xmid > model.designation_end + 35
                    and (is_number(w.text) or is_price(w.text) or is_percent(w.text))
                ]
                if extra_numeric:
                    merged = Line(line.top, line.words + extra_numeric)
                    retry = parse_product_line(merged, model)
                    if retry:
                        parsed = retry

        if parsed:
            if current is not None and current.get("__score", 0) >= 0.70:
                current["Date Facture"] = date
                current["Source extraction"] = source
                current.pop("__score", None)
                rows.append(current)
            current = parsed
            continue
        if current is not None:
            continuation_of_row(current, line, model)

    if current is not None and current.get("__score", 0) >= 0.70:
        current["Date Facture"] = date
        current["Source extraction"] = source
        current.pop("__score", None)
        rows.append(current)
    return rows


def extract_fallback_page(page, date: str) -> list[dict[str, str]]:
    """Fallback texte : conservateur et uniquement utilisé si aucun header exploitable."""
    out = []
    text = page_text(page)
    source = "OCR (à vérifier)" if getattr(page, "_used_ocr", False) else "Texte natif"
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
            "Source extraction": source,
        })
    return out


def extraire_facture_pdf(chemin_pdf: str | Path, chemin_sortie_excel: str | Path = "facture_extraite.xlsx", progress_callback=None) -> pd.DataFrame:
    import pdfplumber

    pdf_path = Path(chemin_pdf).expanduser()
    output_path = Path(chemin_sortie_excel).expanduser()
    if not pdf_path.exists() or not pdf_path.is_file():
        raise FileNotFoundError(f"Fichier PDF introuvable : {pdf_path}")

    # --- Répartition de la barre de progression par phases ----------------

    #   0  -  5 %  : préparation (ouverture PDF, comptage des pages)
    #   5  - 90 %  : lecture / OCR du texte brut de chaque page
    #  90  - 95 %  : extraction des lignes produits page par page
    #  95  -100 %  : écriture du fichier Excel
    PHASE_PREP    = (0, 5)
    PHASE_READ    = (5, 90)
    PHASE_EXTRACT = (90, 95)
    PHASE_WRITE   = (95, 100)

    def report(pct, msg):
        if progress_callback:
            progress_callback(int(pct), msg)

    report(PHASE_PREP[0], "Ouverture du PDF...")

    all_rows: list[dict[str, str]] = []
    last_date = ""

    with pdfplumber.open(pdf_path) as pdf:
        pages = list(pdf.pages)
        n_pages = max(len(pages), 1)
        report(PHASE_PREP[1], f"PDF ouvert : {n_pages} page(s)")

        # --- Phase 1 : lecture / OCR du texte brut de chaque page ---------
        page_texts: list[str] = []
        read_start, read_end = PHASE_READ
        for i, pg in enumerate(pages, start=1):
            page_texts.append(page_text(pg))
            pct = read_start + (read_end - read_start) * (i / n_pages)
            report(pct, f"Lecture de la page {i}/{n_pages}")

        # --- Phase 2 : extraction des lignes produits ---------------------
        extract_start, extract_end = PHASE_EXTRACT
        for page_num, page in enumerate(pages, start=1):
            text = page_texts[page_num - 1]
            d = invoice_date(text, page)

            if not d:
                for offset in (1, 2):
                    idx = page_num - 1 + offset
                    if idx >= len(pages):
                        break
                    candidate_text = page_texts[idx]
                    d = invoice_date(candidate_text)
                    if d and re.search(r"date\s+base", normalize_key(candidate_text), re.IGNORECASE):
                        break
                    if re.search(r"total\s+(?:ht|ttc)|net\s+à\s+payer|net\s+a\s+payer", normalize_key(candidate_text), re.IGNORECASE):
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

            pct = extract_start + (extract_end - extract_start) * (page_num / n_pages)
            report(pct, f"Analyse de la page {page_num}/{n_pages}")

    # --- Phase 3 : écriture du fichier Excel ------------------------------
    report(PHASE_WRITE[0], "Préparation du fichier Excel...")

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

    report(PHASE_WRITE[1], f"Extraction réussie : {len(df)} ligne(s)")
    print(f"Extraction réussie : {len(df)} ligne(s) enregistrée(s) dans '{output_path}'.")
    return df