# -*- coding: utf-8 -*-
"""Генератор WiX v7-источника для готового PyInstaller-дистрибутива.

Использование:
    python installer/generate_wxs.py
"""
from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist_new" / "RTX_Media_Master_v3"
OUT = ROOT / "installer" / "Package.wxs"
ICON = ROOT / "installer" / "app_icon.ico"

WIX_NS = "http://wixtoolset.org/schemas/v4/wxs"
WIX_UI_NS = "http://wixtoolset.org/schemas/v4/wxs/ui"
ET.register_namespace("", WIX_NS)
ET.register_namespace("ui", WIX_UI_NS)

PRODUCT_NAME = "RTX Media Master"
MANUFACTURER = "x_kitaikuyo_x"
VERSION = "3.5.0"
UPGRADE_CODE = "e6e4e0d9-4a4b-5f1c-9d3e-7a1b2c3d4e5f"
EXE_NAME = "RTX_Media_Master_v3.exe"


def q(tag: str) -> str:
    return f"{{{WIX_NS}}}{tag}"


def qu(tag: str) -> str:
    return f"{{{WIX_UI_NS}}}{tag}"


def safe_id(rel: str) -> str:
    """Стабильный WiX-идентификатор для относительного пути."""
    cleaned = re.sub(r"[^A-Za-z0-9_.]+", "_", rel).strip("_")
    digest = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:8].upper()
    base = f"D_{cleaned}"[:60].rstrip("_")
    return f"{base}_{digest}"


def is_excluded(rel: str) -> bool:
    lower = rel.lower()
    if lower == "settings.json":
        return True
    if lower.endswith(".log") or lower.endswith("_log.txt"):
        return True
    if lower == "crash_log.txt":
        return True
    return False


def main() -> None:
    if not DIST.is_dir():
        raise SystemExit(f"Нет дистрибутива: {DIST}")
    if not ICON.exists():
        raise SystemExit(f"Нет иконки: {ICON}")

    wix = ET.Element(q("Wix"))
    package = ET.SubElement(wix, q("Package"), {
        "Id": "RTXMediaMasterProduct",
        "Name": PRODUCT_NAME,
        "Manufacturer": MANUFACTURER,
        "Version": VERSION,
        "UpgradeCode": UPGRADE_CODE,
        "Compressed": "yes",
    })
    ET.SubElement(package, q("MajorUpgrade"), {
        "DowngradeErrorMessage": "A newer version of RTX Media Master is already installed.",
    })
    ET.SubElement(package, q("MediaTemplate"), {
        "EmbedCab": "yes", "CompressionLevel": "high",
    })
    ET.SubElement(package, q("Icon"), {
        "Id": "AppIcon", "SourceFile": str(ICON),
    })
    ET.SubElement(package, q("Property"), {
        "Id": "ARPPRODUCTICON", "Value": "AppIcon",
    })
    ET.SubElement(package, q("Property"), {
        "Id": "WixUIInstallDir", "Value": r"C:\Program Files\RTX Media Master",
    })

    ui = ET.SubElement(package, q("UI"))
    ET.SubElement(ui, qu("WixUI"), {
        "Id": "WixUI_InstallDir", "InstallDirectory": "INSTALLFOLDER",
    })

    pf = ET.SubElement(package, q("StandardDirectory"), {
        "Id": "ProgramFilesFolder",
    })
    install = ET.SubElement(pf, q("Directory"), {
        "Id": "INSTALLFOLDER", "Name": PRODUCT_NAME,
    })

    # Дерево каталогов и файлов дистрибутива.
    dir_nodes: dict[str, ET.Element] = {"": install}
    files = sorted(
        (p for p in DIST.rglob("*") if p.is_file() and not is_excluded(
            p.relative_to(DIST).as_posix()
        )),
        key=lambda p: p.relative_to(DIST).as_posix().lower(),
    )
    for path in files:
        rel = path.relative_to(DIST).as_posix()
        parent_rel = path.parent.relative_to(DIST).as_posix()
        parts = [p for p in parent_rel.split("/") if p]
        for i, part in enumerate(parts):
            node_rel = "/".join(parts[:i + 1])
            if node_rel not in dir_nodes:
                parent_node = dir_nodes["/".join(parts[:i])] if i else install
                dir_nodes[node_rel] = ET.SubElement(parent_node, q("Directory"), {
                    "Id": safe_id(node_rel), "Name": part,
                })
        ET.SubElement(dir_nodes[parent_rel], q("File"), {
            "Source": str(path),
        })

    # Ярлык в меню «Пуск».
    menu = ET.SubElement(package, q("StandardDirectory"), {"Id": "ProgramMenuFolder"})
    menu_app = ET.SubElement(menu, q("Directory"), {
        "Id": "RTXMediaMasterMenu", "Name": PRODUCT_NAME,
    })
    shortcut_component = ET.SubElement(menu_app, q("Component"), {
        "Id": "StartMenuShortcut", "Guid": "*",
    })
    ET.SubElement(shortcut_component, q("Shortcut"), {
        "Id": "LaunchApp",
        "Name": PRODUCT_NAME,
        "Target": f"[INSTALLFOLDER]{EXE_NAME}",
        "WorkingDirectory": "INSTALLFOLDER",
        "Icon": "AppIcon",
    })
    ET.SubElement(shortcut_component, q("RemoveFolder"), {
        "Id": "RemoveShortcutFolder", "Directory": "RTXMediaMasterMenu",
        "On": "uninstall",
    })
    ET.SubElement(shortcut_component, q("RegistryValue"), {
        "Root": "HKCU", "Key": "Software\\RTXMediaMaster",
        "Name": "installed", "Type": "integer", "Value": "1", "KeyPath": "yes",
    })

    ET.indent(wix, space="  ")
    OUT.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        + ET.tostring(wix, encoding="unicode")
        + "\n",
        encoding="utf-8",
    )
    print(f"WXS OK: {OUT} ({len(files)} файлов)")


if __name__ == "__main__":
    main()
