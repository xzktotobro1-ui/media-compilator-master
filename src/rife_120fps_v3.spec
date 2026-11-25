# -*- mode: python ; coding: utf-8 -*-
"""
Спецификация сборки PyInstaller для RTX Media Master v3.

Сборка:
    pyinstaller rife_120fps_v3.spec --noconfirm

Или через build_pyinstaller.bat.
"""

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# Динамические импорты, которые PyInstaller не видит статически
hiddenimports = [
    "tkinter",
    "tkinter.ttk",
    "tkinter.scrolledtext",
    "pynvml",
    "tensorrt",
    "media_engine_v35",
]
try:
    hiddenimports += collect_submodules("tensorrt")
except Exception:
    pass

a = Analysis(
    ["rife_120fps_v3.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "scipy", "pandas", "torch", "tensorflow"],
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
    name="RTX_Media_Master_v3",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,          # GUI-приложение, без консоли
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
