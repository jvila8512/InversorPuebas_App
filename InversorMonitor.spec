# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import os

# Get Python directory
python_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath('.'))))

# Include python311.dll from Python installation
datas = []
binaries = []
hiddenimports = []
tmp_ret = collect_all('PyQt5')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Include Python DLL - use system Python path
python_dll = r'C:\Users\Javier\AppData\Local\Programs\Python\Python311\python311.dll'
if os.path.exists(python_dll):
    binaries.append((python_dll, '.'))

# Include app images
datas += [
    ('felicity_monitor/imagen', 'imagen'),
]

a = Analysis(
    ['felicity_monitor/main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='InversorMonitor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    icon='panel-solar.ico',
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)