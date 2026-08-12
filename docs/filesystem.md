## Filesystem and Runtime Environment

`utils.py` manages resource paths and the transition between the development environment and the packaged application.

The application must work both:

- from the Python development environment;
- as a PyInstaller-bundled executable.

### Resource resolution

The `ressource_path()` function resolves application resources depending on the runtime environment.

When packaged with PyInstaller, resources may be located through `sys._MEIPASS`.

### User data

On first execution, default resources such as databases must be copied from bundled resources to the application's user-data directory.

The application automatically creates the required directories for resources such as:

- `modeles`
- `parametres`
- `gui`
- `bases_de_donnees`

Do not hard-code absolute filesystem paths.

Always use the existing path-resolution utilities when accessing application resources.
