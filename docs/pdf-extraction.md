## PDF Invoice Conversion Workflow

The PDF Invoice Conversion workflow converts supplier invoices in PDF format into structured Excel-compatible data.

The subsystem currently supports:

- a generic invoice extraction workflow;
- a specialized extractor for JARDIMED invoices.

### Workflow

The interface uses three main UI states:

1. **Selection**
   - `ConvertisseurPDF_selecteur.ui`
   - The user chooses the extraction mode.

2. **Loading**
   - `ConvetisseurPDF_chargement.ui`
   - PDF processing runs in the background.
   - The GUI remains responsive.

3. **Results**
   - `Convertisseur_PDF_resultats.ui`
   - The application displays the conversion result.
   - The user can return to the selection screen.

The main extraction implementations are located in:

- `extracteur_facture/extracteur_generique.py`
- `extracteur_facture/extracteur_jardimed.py`

The workflow is coordinated by:

- `navigation/n_extracteur_factures.py`

When adding support for a new supplier, prefer extending the existing extraction architecture rather than modifying the generic extractor in a supplier-specific way.
