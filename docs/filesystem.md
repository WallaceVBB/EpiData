## Filesystem and Runtime Environment

`src/epidata/utils.py` resolves bundled defaults from `src/epidata/resources/` in development and from `epidata/resources/` inside a PyInstaller bundle. Other external resources, such as Tesseract, continue to resolve from the repository or bundle root.

The application must work both:

- from the Python development environment;
- as a PyInstaller-bundled executable.

### Resource resolution

The `ressource_path()` function resolves bundled application resources depending on the runtime environment.

When packaged with PyInstaller, resources are located through `sys._MEIPASS`.

### User data directory

Writable data lives in the user-application directory, resolved by `epidata.utils` in this order:

1. the `EPIDATA_USER_DIR` environment variable, when set (used by tests and custom deployments);
2. the platform user-data directory, when running as a PyInstaller bundle (`%LOCALAPPDATA%\EpiData` on Windows, `~/Library/Application Support/EpiData` on macOS, `~/.local/share/EpiData` on Linux);
3. the project directory, when running from the development environment.

On first execution, the bundled GUI files and default configuration CSVs are copied to the user-data directory by `copier_fichier_ressource_vers_utilisateur()`, called from `app.py`. User copies remain in `gui/` and `parametres/`; packaged defaults stay read-only inside the Python package.

- `pt_base.csv` → `donnees/`;
- configuration CSVs (categories, suppliers, labels, origins, weights, units) → `parametres/`.

### Databases

`bases_de_donnees/` contains:

- `bd_pt.db`: processed products;
- `bd_entrainement.db`: validated pairs used for retraining.

The application automatically creates writable directories for data such as:

- `modeles`
- `parametres`
- `gui`
- `bases_de_donnees`

Do not hard-code absolute filesystem paths.

Always use the existing path-resolution utilities when accessing application resources.
