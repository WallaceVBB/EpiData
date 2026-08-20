# EpiData.spec  
from PyInstaller.utils.hooks import collect_data_files  
  
block_cipher = None  
  
datas = [  
    ('gui', 'gui'),                   
    ('parametres', 'parametres'),     
    ('donnees', 'donnees'),           
]  
  
a = Analysis(  
    ['main.py'],  
    pathex=[],  
    binaries=[],  
    datas=datas,  
    hiddenimports=['sklearn.utils._typedefs', 'sklearn.neighbors._partition_nodes'],  
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