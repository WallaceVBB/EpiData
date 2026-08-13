## Architecture

EpiData is organized into several functional layers.

### Application

- `main.py`: Application entry point.
- `app.py`: Main application lifecycle, GUI initialization, screen management, and high-level orchestration.

### Data Processing

- `data_processing.py`: Core product-processing logic and data normalization. It orchestrates the ML and persistence layers and contains neither raw SQL nor GUI code.
- `gestion_ml.py`: `GestionML`, the single owner of model loading (`.joblib`), training (`creer_modeles`/`recreer_modeles`), and inference (TF-IDF cosine, LinearSVC, hybrid).
- `services.py`: `DataService`, the single owner of database access (schema creation, migration, CRUD) and reference CSV loading.
- `utils.py`: Filesystem management, resource discovery, cross-platform path resolution, and shared helpers such as `nettoyer_texte`.

### Layer dependencies

Dependencies flow in one direction only:

```
navigation/ → data_processing.py → gestion_ml.py → services.py → utils.py
```

- `navigation/` never opens a database connection; it calls `DataService` methods.
- `data_processing.py` writes products through `DataService.inserer_produit` and predicts through `GestionML`.
- `gestion_ml.py` uses a dedicated `DataService` bound to the training database (`bd_entrainement.db`), separate from the product database (`bd_pt.db`).
- Text cleaning (`nettoyer_texte`) has a single implementation in `utils.py`; other layers delegate to it.

### Navigation

- `navigation/`: GUI workflow controllers for specific application modules.
  - `n_traitement.py`: Product-processing workflow.
  - `n_extracteur_factures.py`: PDF invoice conversion workflow.

Navigation modules should primarily coordinate UI events, workflows, and services. Business logic should remain in the appropriate processing or service modules.

### GUI

- `gui/`: Qt Designer `.ui` files defining the application's graphical interfaces.

The `.ui` files are XML-based Qt Designer definitions and are loaded dynamically by the application.

### Configuration and Reference Data

- `parametres/`: CSV configuration and reference files, including labels, origins, categories, weights, and units.
- `donnees/`: Seed data and reference CSV files.
- `modeles/`: Serialized machine learning models and vectorizers.
- `bases_de_donnees/`: SQLite databases, `bd_pt.db` (processed products) and `bd_entrainement.db` (validated training pairs).

### Testing without ML training

Training is expensive and must never run during development checks. `tests/smoke_test.py` validates the layering (imports, schema, CRUD, cosine inference) using tiny fake `.joblib` artifacts and a guard that fails if `creer_modeles`, `recreer_modeles`, or `classifier_produits` is called.

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