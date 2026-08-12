## Product Processing Workflow

The Product Processing workflow is the core EpiData pipeline.

It ingests raw product data from external files such as CSV or Excel, applies normalization and classification logic, and produces enriched records for review and export.

The workflow is managed by the product-processing navigation controller and uses background processing to keep the GUI responsive.

### Workflow

The workflow has three main UI states:

1. **File Selection**
   - The user selects an input file.
   - The user selects the processing mode.

2. **Processing**
   - A background worker performs the data-processing pipeline.
   - The GUI displays a loading/progress state.
   - Heavy processing must not block the Qt GUI thread.

3. **Results**
   - Processed records are displayed in a table.
   - The user can review the predictions.
   - Records requiring manual verification can be identified and corrected.
   - Results can subsequently be exported.

When modifying this workflow, preserve the separation between GUI navigation, background processing, and data-processing logic.

---

## 1. Machine Learning

EpiData uses machine learning to classify and enrich food product descriptions.

### Main concepts

- `base_variante`: Canonical food category string used as the main ML target.
- `Désignation`: Raw product description obtained from supplier data or invoices.
- `LinearSVC`: Main supervised classification model used for multi-class classification.
- `TF-IDF`: Text vectorization used by the classification models.
- `TF-IDF Cosine`: Similarity-based fallback used to identify similar known product descriptions.
- `Hybrid Inference`: Multi-stage inference combining cosine similarity and supervised classification.
- `a_reviser`: Flag indicating that a record has a low-confidence prediction and requires manual review.
- `est_corrige`: Boolean indicating that an ML prediction has been manually verified or corrected by a human.

### Important rules

When modifying ML-related code:

- Preserve compatibility with existing `.joblib` models and vectorizers.
- Do not change the expected feature representation without checking compatibility with the serialized models.
- Do not retrain or overwrite existing models automatically during normal application execution.
- Keep training and inference logic conceptually separated.
- Preserve the manual-review workflow.
- Do not treat a low-confidence prediction as equivalent to a human-validated result.

If changing the inference pipeline, explain how the change affects:
- cosine similarity;
- SVC classification;
- confidence/review flags;
- existing model compatibility.

---

## 2. Domain-Specific Processing Rules

EpiData contains domain-specific heuristics that should be preserved unless explicitly changed.

### Traitement des Appertises

Specialized logic used to infer or normalize the weight of canned and preserved products.

### Poids Moyen F/L

Fallback weight assignment used for fruits and vegetables when a reliable product weight is unavailable.

These rules are part of the domain logic and should not be removed or generalized without understanding their purpose.

---

## 3. Important Data Concepts

### `BD_PT`

SQLite database containing processed and enriched product records.

### `BD_ENTRAINEMENT`

Database containing validated product/classification pairs used as training data or for future model retraining.

### `Désignation`

The raw supplier product description.

### `base_variante`

The canonical product category used as the primary classification target.

### `a_reviser`

Indicates that a prediction requires manual review.

### `est_corrige`

Indicates that a prediction has been manually verified or corrected.
