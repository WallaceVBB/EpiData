## Filesystem and Runtime Environment

`utils.py` manages resource paths and the transition between the development environment and the packaged application.

The application must work both:

- from the Python development environment;
- as a PyInstaller-bundled executable.

### Resource resolution

The `ressource_path()` function resolves bundled application resources depending on the runtime environment.

When packaged with PyInstaller, resources are located through `sys._MEIPASS`.

### User data directory

Writable data lives in the user-application directory, resolved by `utils.py` in this order:

1. the `EPIDATA_USER_DIR` environment variable, when set (used by tests and custom deployments);
2. the platform user-data directory, when running as a PyInstaller bundle (`%LOCALAPPDATA%\EpiData` on Windows, `~/Library/Application Support/EpiData` on macOS, `~/.local/share/EpiData` on Linux);
3. the project directory, when running from the development environment.

On first execution, bundled resources are copied to that directory by `copier_fichier_ressource_vers_utilisateur()`, called from `app.py`. Each resource keeps its subdirectory:

- `pt_base.csv` → `donnees/`;
- configuration CSVs (categories, suppliers, labels, origins, weights, units) → `parametres/`.

### Databases

`bases_de_donnees/` contains:

- `bd_pt.db`: processed products;
- `bd_entrainement.db`: validated pairs used for retraining.

The application automatically creates the required directories for resources such as:

- `modeles`
- `parametres`
- `gui`
- `bases_de_donnees`

Do not hard-code absolute filesystem paths.

Always use the existing path-resolution utilities when accessing application resources.
