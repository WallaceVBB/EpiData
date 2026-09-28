## Architecture

EpiData is organized into several functional layers.

### Application

- `main.py`: Compatibility launcher at the repository root.
- `src/epidata/main.py`: Installed application entry point.
- `src/epidata/app.py`: Main application lifecycle, GUI initialization, screen management, and high-level orchestration.

### Data Processing

- `src/epidata/produits/traitement.py`: Product-processing logic that orchestrates ML and persistence without GUI code or raw SQL.
- `src/epidata/produits/ml.py`: `GestionML`, responsible for model loading, training and inference.
- `src/epidata/produits/donnees.py`: `DataService`, responsible for database access and reference CSV loading.
- `src/epidata/utils.py`: Filesystem management, resource discovery, cross-platform path resolution, and shared helpers such as `nettoyer_texte`.

### Layer dependencies

Dependencies flow in one direction only:

```
epidata.navigation → epidata.produits.traitement → epidata.produits.ml / epidata.produits.donnees → epidata.utils
```

- Navigation never opens a database connection; it calls `DataService` methods.
- Product processing writes through `DataService.inserer_produit` and predicts through `GestionML`.
- `GestionML` uses a dedicated `DataService` bound to the training database (`bd_entrainement.db`), separate from the product database (`bd_pt.db`).
- Text cleaning (`nettoyer_texte`) has a single implementation in `epidata.utils`; other layers delegate to it.

### Domain packages and navigation

- `src/epidata/navigation/`: GUI workflow controllers for specific application modules.
  - `n_traitement.py`: Product-processing workflow.
  - `n_extracteur_factures.py`: PDF invoice conversion workflow.

Navigation modules should primarily coordinate UI events, workflows, and services. Business logic should remain in the appropriate processing or service modules.

### GUI

- `src/epidata/resources/gui/`: Qt Designer `.ui` files and styles, bundled with the Python package.
- `src/epidata/resources/icons/`: Application icons bundled with the Python package.
- `src/epidata/resources/parametres/`: Default CSV configuration bundled with the Python package.
- `src/epidata/factures/extracteurs/`: Generic and supplier-specific PDF invoice extractors.

The `.ui` files are XML-based Qt Designer definitions and are loaded dynamically by the application.

### Configuration and Reference Data

- The writable `parametres/` directory in the user-data folder contains the user's active configuration copies.
- `donnees/`: Seed data and reference CSV files.
- `modeles/`: Serialized machine learning models and vectorizers.
- `bases_de_donnees/`: SQLite databases, `bd_pt.db` (processed products) and `bd_entrainement.db` (validated training pairs).

### Testing without ML training

Training is expensive and must never run during development checks. `tests/smoke_test_small.py` validates the layering (imports, schema, CRUD, cosine inference) using tiny fake `.joblib` artifacts and a guard that fails if `creer_modeles`, `recreer_modeles`, or `classifier_produits` is called.

`tests/full_test.py` is the opposite: a manually launched end-to-end run that *does* train the models (training database → `creer_modeles` → inference → CSV classification → persistence → `maj_bd_entrainement`). Both scripts write to a temporary `EPIDATA_USER_DIR`, so the repository's models and databases are left untouched.

---

## Key Technologies

The project currently uses:

- Python
- PySide6 / Qt
- SQLite
- Pandas
- Scikit-learn
- LinearSVC
- TF-IDF
- Joblib
- PDFPlumber
- PyInstaller

Do not introduce a new dependency when the required functionality can reasonably be implemented using the existing stack.
