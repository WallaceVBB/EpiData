# EpiData.spec  
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

hidden = []  
datas = [  
    ('gui', 'gui'),  
    ('parametres', 'parametres'),
]  
  
# scikit-learn + scipy (dépendance) : sous-modules chargés dynamiquement  
hidden += collect_submodules('sklearn')  
hidden += collect_submodules('scipy')  
  
# pandas / openpyxl : backend Excel chargé par nom  
hidden += collect_submodules('openpyxl')  
hidden += ['pandas._libs.tslibs.base']  
  
# pdfplumber s'appuie sur pdfminer.six + pypdf  
hidden += collect_submodules('pdfminer')  
hidden += collect_submodules('pdfplumber')  
hidden += collect_submodules('pypdf')  
  
# certains fichiers de données non-Python (ex: pdfminer/cmap) sont requis  
datas += collect_data_files('pdfminer')  
datas += collect_data_files('sklearn')  
  
a = Analysis(  
    ['main.py'],  
    pathex=[],  
    binaries=[],  
    datas=datas,  
    hiddenimports=hidden,  
    hookspath=[],  
    runtime_hooks=[],  
    excludes=[],  
    cipher=block_cipher,  
)  
  
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  
  
exe = EXE(  
    pyz, a.scripts, [],  
    exclude_binaries=True,  
    name='EpiData',  
    console=False,  
    icon='icons/epidata_logo.ico', 
)  
  
coll = COLLECT(  
    exe, a.binaries, a.zipfiles, a.datas,  
    name='EpiData',  
)