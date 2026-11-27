# -*- mode: python ; coding: utf-8 -*-
"""
Спецификация сборки PyInstaller для ЧИСТОГО CLI-движка RTX Media Master v3.5.

Результат: rtx_engine.exe — headless-движок, который вызывается из C# GUI
(RTX_Media_Master_v3.exe) с флагами --no-progress и разбирает вывод по логам.

Сборка:
    pyinstaller src/rtx_engine.spec --noconfirm --clean --distpath dist_new
"""

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

hiddenimports = [
    "media_engine_v35",
    "pynvml",
    "tensorrt",
    "rich",
    "rich.console",
    "rich.progress",
]
try:
    hiddenimports += collect_submodules("tensorrt")
except Exception:
    pass
try:
    hiddenimports += collect_submodules("rich")
except Exception:
    pass

a = Analysis(
    ["rtx_media_master_v35.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "scipy", "pandas", "torch", "tensorflow"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="rtx_engine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=True,   # CLI-движок; GUI запускает его с CreateNoWindow=true
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="RTX_Media_Master_v3",
)
