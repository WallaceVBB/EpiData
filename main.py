import os
import sys

RACINE_PROJET = os.path.dirname(os.path.abspath(__file__))
CHEMIN_SRC = os.path.join(RACINE_PROJET, "src")
if CHEMIN_SRC in sys.path:
    sys.path.remove(CHEMIN_SRC)
sys.path.insert(0, CHEMIN_SRC)

from epidata.main import main


if __name__ == "__main__":
    main()
