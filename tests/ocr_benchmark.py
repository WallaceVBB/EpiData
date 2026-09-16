#!/usr/bin/env python3
"""
ocr_benchmark.py — Banc de test comparatif pour le pipeline d'extraction de
factures (Cantine Numérique).

Permet de comparer plusieurs "presets" (méthode de prétraitement d'image x
résolution DPI x mode PSM Tesseract x options de repêchage) sur un même PDF,
et produit des logs CSV détaillés à analyser (toi-même ou en me les envoyant).

EXEMPLES D'USAGE
-----
    python tests/ocr_benchmark.py tests/facture_teste.pdf
    python tests/ocr_benchmark.py tests/facture_teste.pdf --presets otsu_300 otsu_600 hybrid_300_600
    python tests/ocr_benchmark.py tests/facture_teste.pdf --max-pages 15
    python tests/ocr_benchmark.py tests/facture_teste.pdf --out mes_resultats/ --baseline baseline_300

SORTIE (dossier --out, par défaut ./benchmark_out/)
----------------------------------------------------
    lignes_<horodatage>.csv   : une ligne = un produit détecté, pour un preset
                                 et une page donnés (+ le texte OCR brut de la
                                 ligne pour diagnostiquer les erreurs)
    resume_<horodatage>.csv   : par preset -> nb de lignes trouvées, temps,
                                 nb de pages traitées, lignes/page
    diff_<horodatage>.csv     : pour chaque preset vs le preset --baseline :
                                 quels produits sont gagnés / perdus, page par
                                 page (le vrai outil pour ton problème "9/10
                                 ici, mais des pertes ailleurs")

"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median

import pdfplumber
import pytesseract

try:
    import cv2
    _CV2_OK = True
except ImportError:
    _CV2_OK = False

import numpy as np
from PIL import Image, ImageFilter, ImageOps


def _find_project_utils():
    """Cherche utils.py en remontant les dossiers parents depuis ce script
    et depuis le dossier courant (cas où ocr_benchmark.py est dans un
    sous-dossier tests/ séparé du reste du projet). Retourne le module
    importé, ou None si introuvable."""
    import importlib.util

    start_points = [Path(__file__).resolve().parent, Path.cwd()]
    seen = set()
    for start in start_points:
        current = start
        for _ in range(5):  # remonte jusqu'à 5 niveaux, largement suffisant
            if current in seen:
                break
            seen.add(current)
            candidate = current / "utils.py"
            if candidate.is_file():
                spec = importlib.util.spec_from_file_location("cantine_project_utils", candidate)
                module = importlib.util.module_from_spec(spec)
                try:
                    spec.loader.exec_module(module)
                    return module, current
                except Exception as e:
                    print(f"  [!] utils.py trouvé ({candidate}) mais son import a échoué : {e}")
                    return None, None
            if current.parent == current:
                break
            current = current.parent
    return None, None


def configure_tesseract(tesseract_exe: str = None, tessdata_dir: str = None) -> str:
    """Configure pytesseract pour trouver tesseract.exe. Essaie, dans l'ordre :
    1) le chemin passé en argument (--tesseract-exe) ;
    2) une variable d'environnement CANTINE_TESSERACT_EXE (pratique si tu
       veux la définir une fois pour toutes dans ton environnement) ;
    3) le utils.py de ton projet principal, retrouvé automatiquement même si
       ce script est dans un sous-dossier séparé (tests/) — les chemins
       relatifs qu'il définit (ex. "tesseract\\tesseract.exe") sont résolus
       par rapport au dossier où utils.py a été trouvé, pas par rapport au
       dossier courant ;
    4) le PATH système (cas normal sous Linux/Mac, ou si tu as ajouté
       Tesseract au PATH Windows) ;
    5) les emplacements d'installation Windows les plus courants.
    Retourne un message de statut (affiché à l'utilisateur), lève une erreur
    claire si rien n'est trouvé.
    """
    import shutil
    import os

    candidates = []
    if tesseract_exe:
        candidates.append(("--tesseract-exe", tesseract_exe))

    env_exe = os.environ.get("CANTINE_TESSERACT_EXE")
    if env_exe:
        candidates.append(("variable d'environnement CANTINE_TESSERACT_EXE", env_exe))

    project_utils, project_root = _find_project_utils()
    if project_utils is not None:
        exe = getattr(project_utils, "TESSERACT_EXE", None)
        if exe:
            # Chemin résolu par rapport au dossier où utils.py a été trouvé,
            # car TESSERACT_EXE y est défini en relatif ("tesseract\tesseract.exe").
            resolved = exe if os.path.isabs(exe) else str(project_root / exe)
            candidates.append((f"utils.py du projet ({project_root})", resolved))
        if tessdata_dir is None:
            tdd = getattr(project_utils, "TESSDATA_DIR", None)
            if tdd:
                tessdata_dir = tdd if os.path.isabs(tdd) else str(project_root / tdd)

    which_exe = shutil.which("tesseract")
    if which_exe:
        candidates.append(("PATH système", which_exe))

    for path in (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ):
        if Path(path).is_file():
            candidates.append(("emplacement Windows standard", path))

    for source, path in candidates:
        if Path(path).is_file():
            pytesseract.pytesseract.tesseract_cmd = path
            if tessdata_dir and Path(tessdata_dir).is_dir():
                os.environ["TESSDATA_PREFIX"] = str(tessdata_dir)
            return f"tesseract.exe trouvé via {source} : {path}"

    raise SystemExit(
        "\n[ERREUR] Impossible de trouver tesseract.exe.\n"
        "Solutions, dans l'ordre de préférence :\n"
        "  1) Relance avec --tesseract-exe \"C:\\chemin\\vers\\tesseract.exe\"\n"
        "     (le même chemin que TESSERACT_EXE dans le utils.py de ton projet principal)\n"
        "  2) Ou place ce script dans le même dossier que utils.py (celui de\n"
        "     ton pipeline de production), qui semble déjà savoir où est Tesseract\n"
        "  3) Ou installe Tesseract et ajoute-le au PATH Windows\n"
    )

# =============================================================================
# --- Cœur du parsing (copie patchée du module d'extraction) ----------------
# =============================================================================

OCR_LANG = "fra+eng"
OCR_MIN_CONFIDENCE = 20
OCR_MIN_WORDS_FOR_TEXT_LAYER = 5

STANDARD_COLUMNS = [
    "Date Facture", "Désignation", "Quantité", "Unité",
    "Prix unitaire HT", "Montant net HT", "Taux TVA", "Source extraction",
]

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
    "nf525", "e-fac", "dlc:", "dlc :", "ddm:", "ddm :", "origine :",
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
# Patch #2 : tolère un point parasite avant le "€" (ex. OCR "18,80.€")
_PRICE_RE = re.compile(r"^[+-]?(?:\d+(?:[\.,]\d+)?|\d{1,3}(?:[ .]\d{3})+(?:[\.,]\d+)?)[ .]*€?$", re.IGNORECASE)
# Patch #3 : variantes OCR très caractéristiques de "0,00€" (D00E, DODE, DO00€E...)
_OCR_ZERO_AMOUNT_RE = re.compile(r"^[D0Oo]{2,5}[€E.]{0,3}$")
_PRODUCT_CODE_RE = re.compile(r"\bV\d{4}\b")
_BL_RE = re.compile(r"\bBL\b\s*N[°o]", re.IGNORECASE)
_PRODUCT_CODE_IN_TEXT_RE = re.compile(r"\bV\d{4}\b")
_TERM_BOUNDARY_CACHE: dict = {}


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


def is_ocr_zero_amount(value: str) -> bool:
    return bool(_OCR_ZERO_AMOUNT_RE.match(normalize_text(value)))


def is_plausible_price(w: "Word") -> bool:
    if not is_price(w.text):
        return False
    if not getattr(w, "is_ocr", False):
        return True
    digits = re.sub(r"[^0-9]", "", w.text)
    return len(digits) >= 2 or bool(re.search(r"[.,]", w.text))


def is_unit_word(value: str) -> bool:
    return token_key(value) in {token_key(x) for x in UNIT_WORDS}


def _contains_any_term(text: str, terms) -> bool:
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
    words: list

    @property
    def text(self) -> str:
        return " ".join(w.text for w in sorted(self.words, key=lambda x: x.x0))


@dataclass
class ColumnModel:
    designation_start: float
    designation_end: float
    quantity_x: float
    unit_x: float = None
    unit_secondary_x: float = None
    unit_price_x: float = None
    vat_x: float = None
    amount_x: float = None


def _looks_like_product_start(text: str) -> bool:
    t = normalize_text(text)
    if _PRODUCT_CODE_RE.search(t):
        return True
    if _BL_RE.search(t):
        return True
    return False


def group_lines(words: list, tolerance: float = 3.2) -> list:
    lines: list = []
    for word in sorted(words, key=lambda w: (w.top, w.x0)):
        same = lines and abs(word.top - lines[-1].top) <= tolerance
        if same and _PRODUCT_CODE_IN_TEXT_RE.search(word.text) and \
           not _PRODUCT_CODE_IN_TEXT_RE.search(lines[-1].text):
            same = False
        if not same:
            lines.append(Line(word.top, [word]))
        else:
            lines[-1].words.append(word)
    return lines


def header_hit_count(line: Line) -> dict:
    found = {k: [] for k in HEADER_ALIASES}
    for w in line.words:
        tk = token_key(w.text)
        for cat, aliases in HEADER_ALIASES.items():
            if tk in aliases:
                found[cat].append(w)
    return found


def find_header(lines: list, page_width: float):
    candidates = []
    for i, line in enumerate(lines):
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
        qx = min(w.xmid for w in found["quantity"])
        ux = min(w.xmid for w in found["unit"]) if found["unit"] else None
        upx = max(w.xmid for w in found["unit_price"]) if found["unit_price"] else None
        vx = min(w.xmid for w in found["vat"]) if found["vat"] else None
        ax = max(w.xmid for w in found["amount"]) if found["amount"] else None
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
    header_end = i
    for j in range(i, min(i + 5, len(lines))):
        hits = header_hit_count(lines[j])
        n = sum(bool(v) for v in hits.values())
        t = normalize_key(lines[j].text)
        if n >= 2 or any(p in t for p in ("prix unitaire", "montant net", "montant ht", "taux tva", "qté livrée", "qte livree")):
            header_end = j
    return i, header_end, model


def nearest_word(words: list, x: float, numeric: bool = False):
    candidates = []
    for w in words:
        if numeric and not (is_number(w.text) or is_price(w.text)):
            continue
        candidates.append(w)
    return min(candidates, key=lambda w: abs(w.xmid - x)) if candidates else None


def infer_columns(lines: list, start: int, model: ColumnModel) -> ColumnModel:
    samples = []
    for ln in lines[start:start + 50]:
        text = ln.text
        if is_summary(text) or is_non_product(text) or not text:
            continue
        nums = [w for w in ln.words if is_number(w.text) or is_price(w.text) or is_percent(w.text)]
        if len(nums) >= 2:
            samples.append(ln)
    if not samples:
        return model
    designation_starts = []
    for ln in samples:
        candidates = [
            w.x0 for w in sorted(ln.words, key=lambda w: w.x0)
            if w.xmid < model.quantity_x - 10 and re.search(r"[A-Za-zÀ-ÿ]", w.text)
        ]
        if candidates:
            designation_starts.append(min(candidates))
    if designation_starts:
        model.designation_start = median(designation_starts)
    price_xs = []
    for ln in samples:
        for w in ln.words:
            if is_price(w.text) and w.xmid > model.designation_end + 80:
                price_xs.append(w.xmid)
    clusters: list = []
    for x in sorted(price_xs):
        if not clusters or x - median(clusters[-1]) > 15:
            clusters.append([x])
        else:
            clusters[-1].append(x)
    price_clusters = [median(c) for c in clusters if len(c) >= max(2, len(samples) // 8)]
    if len(price_clusters) >= 2:
        ordered = sorted(price_clusters)
        up = min(ordered, key=lambda x: abs(x - model.unit_price_x)) if model.unit_price_x is not None else ordered[-2]
        am = min(ordered, key=lambda x: abs(x - model.amount_x)) if model.amount_x is not None else ordered[-1]
        if up >= am:
            up, am = ordered[-2], ordered[-1]
        model.unit_price_x = up
        model.amount_x = am
    elif len(price_clusters) == 1:
        model.amount_x = price_clusters[0]
    qxs = []
    for ln in samples:
        ws = sorted(ln.words, key=lambda w: w.x0)
        cands = [w for w in ws if (is_number(w.text) or is_price(w.text)) and w.xmid > model.designation_end + 35]
        if cands:
            w = min(cands, key=lambda z: abs(z.xmid - model.quantity_x))
            qxs.append(w.xmid)
    if qxs:
        model.quantity_x = median(qxs)
    uxs = []
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
            m = re.fullmatch(r"\d+(?:[\.,]\d+)?(kg|g|l|p|pc|pcs)", token_key(w.text), re.IGNORECASE)
            if m:
                uxs.append(w.xmid)
                break
    if uxs:
        model.unit_x = median(uxs)
    vxs = [w.xmid for ln in samples for w in ln.words if is_percent(w.text)]
    if vxs:
        model.vat_x = median(vxs)
    return model


def _is_quantity_candidate(w: Word) -> bool:
    return is_number(w.text) or is_price(w.text)


def _compact_unit_parts(text: str):
    t = token_key(text)
    m = re.fullmatch(r"(\d+(?:[\.,]\d+)?)(kg|g|mg|l|cl|ml|dl|hl|p|pc|pcs|pu|u|un|col|colis|carton|cartons|sac|sacs|caisse|caisses|botte|barquette|bac|flt|plateau|pot|pots)", t, re.IGNORECASE)
    if m:
        return [m.group(1), m.group(2)]
    return None


def _strip_origine_suffix(words: list) -> list:
    words = sorted(words, key=lambda w: w.x0)
    for i, w in enumerate(words):
        if token_key(w.text) == "origine":
            return words[:i]
    return words


def parse_product_line(line: Line, model: ColumnModel, log: list = None):
    ws = _strip_origine_suffix(line.words)
    text = " ".join(w.text for w in ws)
    if not text or is_summary(text) or is_non_product(text):
        return None
    if not any(w.x0 >= model.designation_start - 5 and w.xmid < model.designation_end + 10 for w in ws):
        return None
    numeric = [w for w in ws if _is_quantity_candidate(w)]
    numeric_right = [w for w in numeric if w.xmid >= model.designation_end - 5]
    if not numeric_right:
        return None
    pre_price = [w for w in numeric_right if model.unit_price_x is None or w.xmid < model.unit_price_x - 10]
    quantity = nearest_word(pre_price or numeric_right, model.quantity_x, numeric=True)
    if quantity is None:
        return None
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
    if pu is None or amount is None or pu is amount or amount.xmid <= pu.xmid:
        ordered_prices = sorted(prices, key=lambda w: w.xmid)
        pu, amount = ordered_prices[-2], ordered_prices[-1]
    if amount.xmid <= pu.xmid:
        return None
    left = [w for w in ws if w.x0 >= model.designation_start - 4 and w.xmid < model.quantity_x - 10]
    designation = " ".join(w.text for w in left).strip()
    designation = re.sub(r"^\s*\d+\s*/\s*\S+\s+", "", designation)
    if not designation or len(designation) < 2:
        return None
    between = [w for w in ws if quantity.x1 - 2 <= w.x0 and w.xmid < pu.xmid - 8]
    unit_parts: list = []
    for idx, w in enumerate(between):
        compact = _compact_unit_parts(w.text)
        if compact:
            unit_parts = compact
            break
        if is_unit_word(w.text):
            if idx > 0 and is_number(between[idx - 1].text):
                unit_parts = [between[idx - 1].text, w.text]
            else:
                unit_parts = [w.text]
            break
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
        "_raw_line_text": text,
        "__score": 0.30 + 0.20 + 0.18 + 0.18 + (0.10 if unit_parts else 0.0) + (0.04 if vat else 0.0),
    }


def continuation_of_row(row: dict, line: Line, model: ColumnModel) -> bool:
    text = line.text
    if not text or is_summary(text) or is_non_product(text) or looks_like_comment(text):
        return False
    if len([w for w in line.words if is_price(w.text) or is_percent(w.text)]) >= 1:
        return False
    units = [w.text for w in line.words if is_unit_word(w.text)]
    if units and all(w.xmid >= model.quantity_x - 20 for w in line.words):
        row["Unité"] = normalize_text(f"{row.get('Unité', '')} {' '.join(units)}")
        return True
    left_words = [w for w in line.words if w.xmid < model.quantity_x - 12 and re.search(r"[A-Za-zÀ-ÿ]", w.text)]
    if not left_words:
        return False
    fragment = normalize_text(" ".join(w.text for w in left_words))
    if not fragment or re.search(r"\b\d{5}\b", fragment):
        return False
    if len(fragment) > 100 and len(fragment.split()) >= 10:
        return False
    first_x = min(w.x0 for w in left_words)
    if first_x < model.designation_start - 15 and len(fragment.split()) <= 2:
        return False
    row["Désignation"] = normalize_text(f"{row['Désignation']} {fragment}")
    return True


def extract_page_lines(lines: list, page_width: float, repechage: bool = True):
    """Retourne la liste des produits détectés pour une page déjà OCRisée
    (lignes déjà groupées). Ne gère ni la date ni la colonne Source."""
    header = find_header(lines, page_width)
    if header is None:
        return [], "header_non_trouve"
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

        if repechage:
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
                current.pop("__score", None)
                rows.append(current)
            current = parsed
            continue
        if current is not None:
            continuation_of_row(current, line, model)

    if current is not None and current.get("__score", 0) >= 0.70:
        current.pop("__score", None)
        rows.append(current)
    return rows, "ok"


# =============================================================================
# --- Méthodes de prétraitement d'image (le vrai objet du benchmark) --------
# =============================================================================

def _otsu_threshold(arr: np.ndarray) -> int:
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


def prep_original(gray: Image.Image, scale: int) -> Image.Image:
    """Méthode d'origine du script : resize + autocontrast + sharpen."""
    w, h = gray.size
    img = gray.resize((w * scale, h * scale), Image.LANCZOS)
    img = ImageOps.autocontrast(img)
    img = img.filter(ImageFilter.SHARPEN)
    return img


def prep_otsu_global(gray: Image.Image, scale: int) -> Image.Image:
    """Binarisation par seuil d'Otsu calculé sur toute la page (patch validé)."""
    w, h = gray.size
    img = gray.resize((w * scale, h * scale), Image.LANCZOS)
    arr = np.array(img)
    t = _otsu_threshold(arr)
    return Image.fromarray(np.where(arr > t, 255, 0).astype("uint8"))


def prep_otsu_local(gray: Image.Image, scale: int) -> Image.Image:
    """Seuillage adaptatif local (OpenCV). Nécessite opencv-python-headless."""
    if not _CV2_OK:
        raise RuntimeError("opencv-python-headless non installé")
    w, h = gray.size
    img = gray.resize((w * scale, h * scale), Image.LANCZOS)
    arr = np.array(img)
    bw = cv2.adaptiveThreshold(arr, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, blockSize=35, C=15)
    return Image.fromarray(bw)


def prep_clahe_otsu(gray: Image.Image, scale: int) -> Image.Image:
    """CLAHE (contraste local) puis Otsu global — hybride censé combattre les
    fonds zébrés sans le bruit du seuillage adaptatif pur."""
    if not _CV2_OK:
        raise RuntimeError("opencv-python-headless non installé")
    w, h = gray.size
    img = gray.resize((w * scale, h * scale), Image.LANCZOS)
    arr = np.array(img)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(16, 16))
    arr2 = clahe.apply(arr)
    _, bw = cv2.threshold(arr2, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return Image.fromarray(bw)


PREPROCESSORS = {
    "original": prep_original,
    "otsu_global": prep_otsu_global,
    "otsu_local": prep_otsu_local,
    "clahe_otsu": prep_clahe_otsu,
}


# =============================================================================
# --- Rendu de page + OCR, paramétrés par preset -----------------------------
# =============================================================================

def render_and_ocr_page(page, dpi: int, preprocess_key: str, psm: int, scale: int = 2):
    """Rasterise, prétraite et passe à l'OCR une page pdfplumber. Retourne
    (list[Word], nb_mots_bruts_avant_filtre_confiance)."""
    image = page.to_image(resolution=dpi).original
    gray = image.convert("L")
    prep_fn = PREPROCESSORS[preprocess_key]
    processed = prep_fn(gray, scale)

    scale_pt = 72.0 / (dpi * scale)
    config = f"--psm {psm}"
    data = pytesseract.image_to_data(processed, lang=OCR_LANG, config=config, output_type=pytesseract.Output.DICT)

    n = len(data.get("text", []))
    raw_words = []
    n_before_conf_filter = 0
    for i in range(n):
        text = normalize_text(data["text"][i])
        if not text or text == "_":
            continue
        n_before_conf_filter += 1
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if conf < OCR_MIN_CONFIDENCE:
            continue
        raw_words.append({
            "text": text,
            "left": float(data["left"][i]), "top": float(data["top"][i]),
            "width": float(data["width"][i]), "height": float(data["height"][i]),
            "line_key": (data["block_num"][i], data["par_num"][i], data["line_num"][i]),
        })

    if not raw_words:
        return [], n_before_conf_filter

    line_tops: dict = {}
    for w in raw_words:
        line_tops.setdefault(w["line_key"], []).append(w["top"])
    line_avg_top = {k: sum(v) / len(v) for k, v in line_tops.items()}

    out = []
    for w in raw_words:
        top = line_avg_top[w["line_key"]]
        out.append(Word(
            w["text"], w["left"] * scale_pt, (w["left"] + w["width"]) * scale_pt,
            top * scale_pt, (top + w["height"]) * scale_pt, is_ocr=True,
        ))
    return out, n_before_conf_filter


# =============================================================================
# --- Presets -----------------------------------------------------------------
# =============================================================================

@dataclass
class Preset:
    name: str
    dpi: int
    preprocess: str
    psm: int = 4
    repechage: bool = True
    scale: int = 2
    hybrid_fallback_dpi: int = None      # si défini : mode hybride
    hybrid_fallback_preprocess: str = None
    hybrid_min_lines: int = 1            # en dessous de ce nb de lignes -> on retente en fallback
    description: str = ""


PRESETS: dict = {
    "baseline_300": Preset(
        "baseline_300", dpi=300, preprocess="original", repechage=False,
        description="Pipeline d'origine (autocontrast+sharpen), sans les patches — référence",
    ),
    "otsu_300": Preset(
        "otsu_300", dpi=300, preprocess="otsu_global", repechage=True,
        description="Otsu global + repêchage — recommandé actuellement",
    ),
    "otsu_400": Preset(
        "otsu_400", dpi=400, preprocess="otsu_global", repechage=True,
        description="Otsu global + repêchage, DPI plus élevé",
    ),
    "otsu_600": Preset(
        "otsu_600", dpi=600, preprocess="otsu_global", repechage=True,
        description="Otsu global + repêchage, DPI élevé (lent)",
    ),
    "otsu_local_400": Preset(
        "otsu_local_400", dpi=400, preprocess="otsu_local", repechage=True,
        description="Seuillage adaptatif local (nécessite opencv)",
    ),
    "clahe_otsu_400": Preset(
        "clahe_otsu_400", dpi=400, preprocess="clahe_otsu", repechage=True,
        description="CLAHE + Otsu (nécessite opencv)",
    ),
    "otsu_300_psm6": Preset(
        "otsu_300_psm6", dpi=300, preprocess="otsu_global", psm=6, repechage=True,
        description="Otsu global, mode Tesseract PSM 6 (bloc uniforme) au lieu de 4",
    ),
    "hybrid_300_600": Preset(
        "hybrid_300_600", dpi=300, preprocess="otsu_global", repechage=True,
        hybrid_fallback_dpi=600, hybrid_fallback_preprocess="otsu_global", hybrid_min_lines=1,
        description="Passe rapide à 300 dpi ; pages pauvres en lignes retentées à 600 dpi",
    ),
}


# =============================================================================
# --- Exécution d'un preset sur un PDF ---------------------------------------
# =============================================================================

def run_preset_on_pdf(pdf_path: Path, preset: Preset, max_pages: int = None, verbose: bool = True):
    """Retourne (list[row_dict], list[page_stat_dict])."""
    all_rows = []
    page_stats = []

    with pdfplumber.open(pdf_path) as pdf:
        pages = list(pdf.pages)
        if max_pages:
            pages = pages[:max_pages]

        for page_num, page in enumerate(pages, start=1):
            t0 = time.time()
            try:
                words, n_raw = render_and_ocr_page(page, preset.dpi, preset.preprocess, preset.psm, preset.scale)
            except RuntimeError as e:
                if verbose:
                    print(f"  [{preset.name}] page {page_num}: {e} — page ignorée")
                page_stats.append({"preset": preset.name, "page": page_num, "erreur": str(e),
                                    "dpi_utilise": preset.dpi, "nb_lignes": 0, "temps_s": 0})
                continue

            lines = group_lines(words)
            rows, status = extract_page_lines(lines, page.width, repechage=preset.repechage)
            dpi_used = preset.dpi

            # Mode hybride : si trop peu de lignes trouvées, on retente en fallback
            if preset.hybrid_fallback_dpi and len(rows) < preset.hybrid_min_lines:
                words2, _ = render_and_ocr_page(
                    page, preset.hybrid_fallback_dpi, preset.hybrid_fallback_preprocess,
                    preset.psm, preset.scale,
                )
                lines2 = group_lines(words2)
                rows2, status2 = extract_page_lines(lines2, page.width, repechage=preset.repechage)
                if len(rows2) > len(rows):
                    rows, status, dpi_used = rows2, status2, preset.hybrid_fallback_dpi

            elapsed = time.time() - t0
            page_stats.append({
                "preset": preset.name, "page": page_num, "erreur": "",
                "dpi_utilise": dpi_used, "nb_lignes": len(rows), "temps_s": round(elapsed, 2),
                "statut_header": status,
            })
            for r in rows:
                all_rows.append({
                    "preset": preset.name, "page": page_num, "dpi_utilise": dpi_used,
                    "Désignation": r.get("Désignation", ""), "Quantité": r.get("Quantité", ""),
                    "Unité": r.get("Unité", ""), "Prix unitaire HT": r.get("Prix unitaire HT", ""),
                    "Montant net HT": r.get("Montant net HT", ""), "Taux TVA": r.get("Taux TVA", ""),
                    "texte_ocr_brut": r.get("_raw_line_text", ""),
                })
            if verbose:
                print(f"  [{preset.name}] page {page_num}/{len(pages)} : {len(rows)} ligne(s) "
                      f"({elapsed:.1f}s, dpi={dpi_used})")

    return all_rows, page_stats


# =============================================================================
# --- Clé de correspondance produit (pour le diff) ---------------------------
# =============================================================================

def product_key(designation: str) -> str:
    """Clé de correspondance robuste entre presets pour un même produit :
    le code Vxxxx s'il existe, sinon les 12 premiers caractères normalisés
    de la désignation (suffit à distinguer BROCOLI de ABRICOT même si l'OCR
    perd le préfixe "Vxxxx -")."""
    m = _PRODUCT_CODE_RE.search(designation or "")
    if m:
        return m.group(0)
    return normalize_key(designation)[:12]


# =============================================================================
# --- Écriture des CSV --------------------------------------------------------
# =============================================================================

def write_lines_csv(path: Path, all_rows: list):
    fields = ["preset", "page", "dpi_utilise", "Désignation", "Quantité", "Unité",
              "Prix unitaire HT", "Montant net HT", "Taux TVA", "texte_ocr_brut"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=";")
        w.writeheader()
        for r in all_rows:
            w.writerow(r)


def write_summary_csv(path: Path, all_rows: list, page_stats: list, presets_run: list):
    fields = ["preset", "description", "nb_pages_traitees", "nb_lignes_totales",
              "lignes_par_page_moyenne", "temps_total_s", "nb_pages_header_non_trouve"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=";")
        w.writeheader()
        for name in presets_run:
            preset = PRESETS[name]
            stats = [s for s in page_stats if s["preset"] == name]
            rows = [r for r in all_rows if r["preset"] == name]
            n_pages = len(stats)
            total_time = sum(s["temps_s"] for s in stats)
            n_no_header = sum(1 for s in stats if s.get("statut_header") == "header_non_trouve")
            w.writerow({
                "preset": name,
                "description": preset.description,
                "nb_pages_traitees": n_pages,
                "nb_lignes_totales": len(rows),
                "lignes_par_page_moyenne": round(len(rows) / n_pages, 2) if n_pages else 0,
                "temps_total_s": round(total_time, 1),
                "nb_pages_header_non_trouve": n_no_header,
            })


def write_diff_csv(path: Path, all_rows: list, presets_run: list, baseline: str):
    """Pour chaque preset (hors baseline), liste les produits gagnés et
    perdus par rapport au preset de référence, page par page."""
    fields = ["preset", "page", "type", "cle_produit", "designation", "quantite",
              "prix_unitaire", "montant"]
    baseline_rows = [r for r in all_rows if r["preset"] == baseline]
    baseline_keys = {(r["page"], product_key(r["Désignation"])): r for r in baseline_rows}

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=";")
        w.writeheader()
        for name in presets_run:
            if name == baseline:
                continue
            preset_rows = [r for r in all_rows if r["preset"] == name]
            preset_keys = {(r["page"], product_key(r["Désignation"])): r for r in preset_rows}

            gained = set(preset_keys) - set(baseline_keys)
            lost = set(baseline_keys) - set(preset_keys)

            for page, key in sorted(gained):
                r = preset_keys[(page, key)]
                w.writerow({"preset": name, "page": page, "type": "GAGNE", "cle_produit": key,
                            "designation": r["Désignation"], "quantite": r["Quantité"],
                            "prix_unitaire": r["Prix unitaire HT"], "montant": r["Montant net HT"]})
            for page, key in sorted(lost):
                r = baseline_keys[(page, key)]
                w.writerow({"preset": name, "page": page, "type": "PERDU", "cle_produit": key,
                            "designation": r["Désignation"], "quantite": r["Quantité"],
                            "prix_unitaire": r["Prix unitaire HT"], "montant": r["Montant net HT"]})


# =============================================================================
# --- CLI ----------------------------------------------------------------------
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Banc de test OCR pour factures.")
    parser.add_argument("pdf", type=Path, help="Chemin du PDF à tester")
    parser.add_argument("--presets", nargs="+", default=list(PRESETS.keys()),
                         help=f"Presets à exécuter (défaut : tous). Disponibles : {', '.join(PRESETS)}")
    parser.add_argument("--max-pages", type=int, default=None,
                         help="Limiter le test aux N premières pages (recommandé pour un premier essai)")
    parser.add_argument("--out", type=Path, default=Path("benchmark_out"),
                         help="Dossier de sortie des CSV")
    parser.add_argument("--baseline", type=str, default="baseline_300",
                         help="Preset de référence pour le rapport de diff")
    parser.add_argument("--tesseract-exe", type=str, default=None,
                         help=r"Chemin vers tesseract.exe (ex: C:\...\tesseract.exe). "
                              r"Nécessaire sous Windows si Tesseract n'est pas dans le PATH.")
    parser.add_argument("--tessdata-dir", type=str, default=None,
                         help="Dossier tessdata (contenant fra.traineddata, eng.traineddata)")
    args = parser.parse_args()

    status = configure_tesseract(args.tesseract_exe, args.tessdata_dir)
    print(status)

    if not args.pdf.exists():
        print(f"Fichier introuvable : {args.pdf}")
        sys.exit(1)

    args.out.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    unknown = [p for p in args.presets if p not in PRESETS]
    if unknown:
        print(f"Presets inconnus : {unknown}. Disponibles : {list(PRESETS)}")
        sys.exit(1)

    if not _CV2_OK:
        skip = [p for p in args.presets if PRESETS[p].preprocess in ("otsu_local", "clahe_otsu")]
        if skip:
            print(f"[!] opencv non installé (pip install opencv-python-headless) — "
                  f"presets ignorés : {skip}")
        args.presets = [p for p in args.presets if p not in skip]

    print(f"Fichier : {args.pdf}")
    print(f"Presets : {args.presets}")
    if args.max_pages:
        print(f"Limité aux {args.max_pages} premières pages")
    print()

    all_rows, page_stats = [], []
    for name in args.presets:
        preset = PRESETS[name]
        print(f"--- Preset '{name}' : {preset.description} ---")
        t0 = time.time()
        rows, stats = run_preset_on_pdf(args.pdf, preset, max_pages=args.max_pages)
        all_rows.extend(rows)
        page_stats.extend(stats)
        print(f"  => {len(rows)} ligne(s) au total en {time.time() - t0:.1f}s\n")

    lines_path = args.out / f"lignes_{timestamp}.csv"
    summary_path = args.out / f"resume_{timestamp}.csv"
    diff_path = args.out / f"diff_{timestamp}.csv"

    write_lines_csv(lines_path, all_rows)
    write_summary_csv(summary_path, all_rows, page_stats, args.presets)
    if args.baseline in args.presets:
        write_diff_csv(diff_path, all_rows, args.presets, args.baseline)
    else:
        print(f"[!] baseline '{args.baseline}' non exécuté, pas de rapport de diff")

    print("=" * 70)
    print("Terminé. Fichiers générés :")
    print(f"  {lines_path}")
    print(f"  {summary_path}")
    if args.baseline in args.presets:
        print(f"  {diff_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()