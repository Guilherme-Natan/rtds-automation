#!/usr/bin/env python3
"""Copia uma imagem BOOT.bin para um cartao SD compativel."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))

from common import AutomationError, entrypoint, env_directories, ok, resolve_file, warn
from cli import Cancelled, select


@dataclass(frozen=True)
class Volume:
    root: Path
    label: str
    filesystem: str
    size: int
    bus: str


def _windows_volumes() -> list[Volume]:
    kernel32 = ctypes.windll.kernel32
    mask = kernel32.GetLogicalDrives()
    volumes: list[Volume] = []
    for index in range(26):
        if not mask & (1 << index):
            continue
        root = f"{chr(65 + index)}:\\"
        if kernel32.GetDriveTypeW(root) != 2:  # DRIVE_REMOVABLE
            continue
        label = ctypes.create_unicode_buffer(261)
        filesystem = ctypes.create_unicode_buffer(261)
        serial = ctypes.c_ulong()
        maximum = ctypes.c_ulong()
        flags = ctypes.c_ulong()
        if not kernel32.GetVolumeInformationW(root, label, 261, ctypes.byref(serial), ctypes.byref(maximum), ctypes.byref(flags), filesystem, 261):
            continue
        total = ctypes.c_ulonglong()
        free = ctypes.c_ulonglong()
        available = ctypes.c_ulonglong()
        if not kernel32.GetDiskFreeSpaceExW(root, ctypes.byref(available), ctypes.byref(total), ctypes.byref(free)):
            continue
        if filesystem.value.upper() == "FAT32" and total.value <= 32 * 1024**3:
            volumes.append(Volume(Path(root), label.value, filesystem.value, total.value, "removivel"))
    return volumes


def _linux_volumes() -> list[Volume]:
    try:
        result = subprocess.run(
            ["lsblk", "--json", "--bytes", "--output", "NAME,PATH,RM,TRAN,FSTYPE,SIZE,LABEL,MOUNTPOINTS"],
            text=True,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    volumes: list[Volume] = []

    def visit(node: dict, removable_parent: bool = False, transport: str = "") -> None:
        removable = removable_parent or bool(node.get("rm"))
        bus = str(node.get("tran") or transport or "removivel")
        mounts = node.get("mountpoints") or []
        mount = next((item for item in mounts if item), None)
        filesystem = str(node.get("fstype") or "")
        size = int(node.get("size") or 0)
        if removable and mount and filesystem.lower() in {"vfat", "fat32"} and size <= 32 * 1024**3:
            volumes.append(Volume(Path(mount), str(node.get("label") or ""), filesystem, size, bus))
        for child in node.get("children") or []:
            visit(child, removable, bus)

    for device in json.loads(result.stdout).get("blockdevices", []):
        visit(device)
    return volumes


def compatible_volumes() -> list[Volume]:
    if os.name == "nt":
        volumes = _windows_volumes()
    elif sys.platform.startswith("linux"):
        volumes = _linux_volumes()
    else:
        raise AutomationError("Deteccao automatica de cartao SD suportada no Windows e no Linux.")
    return sorted({volume.root: volume for volume in volumes}.values(), key=lambda item: str(item.root))


def _choose_boot_image() -> Path:
    source = select("Escolha a origem da imagem", ["Circuito", "Teste"])[0]
    if source == 0:
        images = sorted({
            image.resolve()
            for directory in env_directories("CIRCUIT_DIRS")
            for image in directory.rglob("BOOT.bin")
            if image.parent.parent.name == "arquivos_boot"
        })
        if not images:
            raise AutomationError("Nenhum BOOT.bin de circuito foi encontrado.")
        circuits = sorted({image.parent.parent.parent.name for image in images})
        circuit = circuits[select("Escolha o circuito", circuits)[0]]
        method_images = [image for image in images if image.parent.parent.parent.name == circuit]
        labels = [image.parent.name for image in method_images]
        return method_images[select(f"Escolha o metodo de {circuit}", labels)[0]]
    images = sorted({image.resolve() for directory in env_directories("TEST_DIRS") for image in directory.rglob("BOOT.bin")})
    if not images:
        raise AutomationError("Nenhum BOOT.bin de teste foi encontrado.")
    return images[select("Escolha o teste", [image.parent.name for image in images])[0]]


def deploy(boot_bin: Path | None = None) -> None:
    cards = compatible_volumes()
    if not cards:
        warn("Nenhum cartao SD compativel foi encontrado.")
        print("Use um cartao SD/SDHC removivel, FAT32, de ate 32 GB.")
        return
    card = cards[0]
    if len(cards) > 1:
        labels = [f"{item.root}  {item.label}  {item.size / 1024**3:.1f} GB  {item.bus}/{item.filesystem}" for item in cards]
        card = cards[select("Escolha o cartao SD", labels)[0]]
    source = _choose_boot_image() if boot_bin is None else resolve_file(boot_bin)
    destination = card.root / "BOOT.bin"
    shutil.copy2(source, destination)
    ok(f"BOOT.bin copiado para '{destination}'.")
    print(f"Origem: {source}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="python deploy.py", description=__doc__)
    parser.add_argument("--boot-bin", type=Path)
    args = parser.parse_args()
    try:
        deploy(args.boot_bin)
    except Cancelled:
        return 130
    return 0


if __name__ == "__main__":
    entrypoint(main)
