# EpiData — GitHub Copilot Instructions

## Project

EpiData is a Python desktop application for processing and enriching food purchasing data.

Main technologies:
- Python
- PySide6 / Qt
- SQLite
- Pandas
- Scikit-learn
- Joblib
- PDFPlumber
- PyInstaller

The project is actively under development. Prefer small, coherent changes that preserve existing behavior.

## Architecture

- `main.py` — application entry point.
- `app.py` — application lifecycle and high-level GUI orchestration.
- `data_processing.py` — product processing, normalization, and classification.
- `gestion_ml.py` — ML training and inference.
- `services.py` — application services, persistence, database access, and model management.
- `navigation/` — GUI workflow controllers.
- `gui/` — Qt Designer `.ui` files.
- `extrateur_facture/` — PDF invoice extraction.
- `parametres/` — configuration and reference CSVs.
- `donnees/` — seed/reference data.
- `modeles/` — serialized ML models and vectorizers.
- `utils.py` — filesystem and resource path management.

Keep responsibilities separated between these components.

## Development Rules

### Understand before modifying

For significant changes:

1. Inspect the relevant code.
2. Identify affected files.
3. Explain the proposed approach.
4. Then implement the change.

Do not immediately rewrite multiple files without understanding their relationships.

### Reuse existing code

Before creating a new function, class, service, or utility:

- search the repository for existing functionality;
- reuse existing code where appropriate;
- avoid duplicate implementations.

### Minimize changes

Prefer the smallest coherent change that solves the problem.

Avoid:
- unnecessary refactoring;
- unrelated cleanup;
- large rewrites;
- new dependencies without a clear reason.

### Preserve behavior

Do not remove or silently change existing functionality.

If a change may affect another workflow, explain the potential impact.

## Qt / GUI

The GUI uses PySide6 and Qt Designer.

- Prefer editing `.ui` files through Qt Designer.
- Preserve widget `objectName` values.
- Check signal/slot connections before renaming or removing widgets.
- Preserve the existing `QStackedWidget` navigation architecture.
- Keep business logic out of GUI event handlers.

## Threading

Long-running operations such as ML inference, PDF extraction, and large data processing must not block the Qt GUI thread.

Preserve the existing worker/thread architecture and use signals for communication with the GUI.

Do not update Qt widgets directly from worker threads.

## Machine Learning

Important concepts:

- `base_variante` — canonical ML target.
- `Désignation` — raw supplier product description.
- `LinearSVC` — supervised classification model.
- `TF-IDF` — text vectorization.
- `TF-IDF Cosine` — similarity-based matching/fallback.
- `a_reviser` — record requiring manual review.
- `est_corrige` — human-verified/corrected prediction.

When modifying ML code:

- preserve compatibility with existing `.joblib` models;
- do not overwrite models during normal application execution;
- keep training and inference separate;
- preserve the manual-review workflow.

## Data and Database

Important databases:

- `BD_PT` — processed and enriched product records.
- `BD_ENTRAINEMENT` — validated records used for training/retraining.

Preserve existing schemas and user data unless a change is explicitly required.

Use parameterized SQL queries.

Treat database schema and ML model format changes as potentially breaking changes.

## Filesystem and Packaging

The application must work both in development and as a PyInstaller executable.

Use the existing path-resolution utilities in `utils.py`.

Do not hard-code absolute paths.

Be careful when modifying code involving bundled resources and `sys._MEIPASS`.

## PDF Extraction

Current extractors include:

- generic invoice extraction;
- JARDIMED-specific extraction.

Relevant code is in `extrateur_facture/` and `navigation/n_extracteur_factures.py`.

When adding a supplier, prefer extending the extraction architecture rather than adding supplier-specific conditions to generic extraction logic.

## Debugging

When fixing a bug:

1. Identify the root cause.
2. Inspect the relevant data flow.
3. Explain the cause.
4. Make the smallest reasonable fix.
5. Explain what should be tested.

Do not refactor unrelated code during a bug fix.

If the cause cannot be determined from the available information, say what is missing instead of guessing.

## Documentation

Additional project documentation is available in `docs/`.

The source code is the ultimate source of truth.

If documentation conflicts with the implementation, inspect the code and mention the discrepancy rather than blindly following the documentation.

## Before Significant Changes

Before modifying multiple files or changing architecture, provide:

- **Goal**
- **Files affected**
- **Approach**
- **Risks**
- **Testing**

Do not perform unrelated changes as part of the task.