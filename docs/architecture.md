## Architecture

EpiData is organized into several functional layers.

### Application

- `main.py`: Application entry point.
- `app.py`: Main application lifecycle, GUI initialization, screen management, and high-level orchestration.

### Data Processing

- `data_processing.py`: Core product-processing logic, including data normalization and ML classification orchestration.
- `gestion_ml.py`: Machine learning training and inference pipelines.
- `services.py`: Data persistence, database access, model management, and application-level services.
- `utils.py`: Filesystem management, resource discovery, and cross-platform path resolution.

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