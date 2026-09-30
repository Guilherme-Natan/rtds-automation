"""Utilitarios compartilhados pela automacao RTDS."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


PROJECT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_DIR / ".env"
METHODS = ("forward", "backward", "trapezoidal")
SIMULATION_TYPES = (
    "behavioral",
    "synthesis",
    "synthesis-timing",
    "implementation",
    "implementation-timing",
)
BOARD_PART = "avnet.com:zedboard:part0:1.4"
BOARD_DEVICE_PART = "xc7z020clg484-1"
BOARD_STORE_BASE_URL = (
    "https://raw.githubusercontent.com/Xilinx/XilinxBoardStore/2022.2/"
    "boards/Avnet/zedboard/1.4"
)
BOARD_FILES = (
    "board.xml",
    "changelog.txt",
    "part0_pins.xml",
    "preset.xml",
    "xitem.json",
    "zed_board.jpg",
)


class AutomationError(RuntimeError):
    """Erro esperado e apresentavel ao usuario."""


@dataclass(frozen=True)
class IpMetadata:
    name: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    vlnv: str = ""


def info(message: str) -> None:
    print(message)


def ok(message: str) -> None:
    print(f"[OK] {message}")


def warn(message: str) -> None:
    print(f"[AVISO] {message}")


def read_env() -> dict[str, str]:
    if not ENV_FILE.is_file():
        raise AutomationError(f"Arquivo .env nao encontrado em '{ENV_FILE}'.")
    values: dict[str, str] = {}
    for raw_line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def env_value(name: str) -> str:
    value = read_env().get(name, "").strip()
    if not value:
        raise AutomationError(f"Defina {name} no arquivo .env.")
    return value


def rtds_root() -> Path:
    return Path(env_value("RTDS_ROOT")).expanduser().resolve()


def env_directories(name: str) -> list[Path]:
    raw = env_value(name)
    directories = [Path(item.strip().strip('"').strip("'")).expanduser() for item in raw.split(";") if item.strip()]
    if not directories:
        raise AutomationError(f"{name} nao possui nenhuma pasta.")
    result: list[Path] = []
    for directory in directories:
        if not directory.is_dir():
            raise AutomationError(f"Pasta configurada em {name} nao encontrada: '{directory}'.")
        result.append(directory.resolve())
    return result


def circuit_files() -> list[Path]:
    files = {
        path.resolve()
        for directory in env_directories("CIRCUIT_DIRS")
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in {".cir", ".sp"}
    }
    if not files:
        raise AutomationError("Nenhum arquivo .cir ou .sp foi encontrado nas pastas de CIRCUIT_DIRS.")
    return sorted(files, key=lambda path: str(path).lower())


def resolve_file(value: str | os.PathLike[str]) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise AutomationError(f"Arquivo nao encontrado: '{value}'.")
    return path


def method_names(method: str) -> tuple[str, ...]:
    if method == "all":
        return METHODS
    if method not in METHODS:
        raise AutomationError(f"Metodo invalido: '{method}'.")
    return (method,)


def parse_spice_number(value: str) -> float:
    match = re.fullmatch(
        r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)(meg|[tgkmunpf]?)",
        value.strip(),
        re.IGNORECASE,
    )
    if not match:
        raise AutomationError(f"Valor SPICE invalido: '{value}'.")
    multipliers = {
        "": 1.0,
        "t": 1e12,
        "g": 1e9,
        "meg": 1e6,
        "k": 1e3,
        "m": 1e-3,
        "u": 1e-6,
        "n": 1e-9,
        "p": 1e-12,
        "f": 1e-15,
    }
    return float(match.group(1)) * multipliers[match.group(2).lower()]


def netlist_time_step(netlist: Path) -> float | None:
    for line in netlist.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if re.match(r"^\s*\*", line):
            continue
        match = re.match(r"^\s*\.STEP\s+(\S+)", line, re.IGNORECASE)
        if match:
            return parse_spice_number(match.group(1))
    return None


def pulse_divider(time_step: float) -> int:
    exact = 50_000_000.0 * time_step
    nearest = max(1, int(exact + 0.5))
    if abs(exact - nearest) > 1e-9:
        recommended = nearest / 50_000_000.0
        raise AutomationError(
            f"50 MHz * Ts deve ser inteiro; o valor atual resulta em {exact}. "
            f"Timestep mais proximo: {recommended:.12g} s (divisor {nearest})."
        )
    return nearest


def tcl_path(path: Path) -> str:
    return path.resolve().as_posix()


def write_utf8(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8", newline="\n")


def run(command: Sequence[str | os.PathLike[str]], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    args = [str(part) for part in command]
    try:
        result = subprocess.run(args, text=True, capture_output=capture, check=False)
    except OSError as exc:
        raise AutomationError(f"Nao foi possivel executar '{args[0]}': {exc}") from exc
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "nenhuma mensagem de erro foi fornecida").strip()
        raise AutomationError(f"'{Path(args[0]).name}' terminou com codigo {result.returncode}: {details}")
    return result


def _version_key(path: Path) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", path.name)
    return tuple(int(number) for number in numbers) if numbers else (0,)


def find_tool(command: str, product: str | None = None) -> Path:
    found = shutil.which(command)
    if found:
        return Path(found)
    if os.name == "nt" and product:
        root = Path(r"C:\Xilinx") / product
        extension = ".bat"
        if root.is_dir():
            for installation in sorted(root.iterdir(), key=_version_key, reverse=True):
                candidate = installation / "bin" / f"{command}{extension}"
                if candidate.is_file():
                    return candidate
    location = f" nem em C:\\Xilinx\\{product}" if product and os.name == "nt" else ""
    raise AutomationError(f"Ferramenta '{command}' nao encontrada no PATH{location}.")


def find_vivado() -> Path:
    return find_tool("vivado", "Vivado")


def ip_metadata(component_file: Path) -> IpMetadata:
    if not component_file.is_file():
        raise AutomationError(f"Metadados do IP nao encontrados em '{component_file}'.")
    root = ET.parse(component_file).getroot()

    def child_text(node: ET.Element, local_name: str, default: str = "") -> str:
        for child in node:
            if child.tag.rsplit("}", 1)[-1] == local_name:
                return (child.text or "").strip()
        return default

    inputs: list[str] = []
    outputs: list[str] = []
    for port in root.iter():
        if port.tag.rsplit("}", 1)[-1] != "port":
            continue
        name = child_text(port, "name")
        direction = ""
        for descendant in port.iter():
            if descendant.tag.rsplit("}", 1)[-1] == "direction":
                direction = (descendant.text or "").strip()
                break
        if name.startswith("ap_") or name.endswith("_ap_vld"):
            continue
        if direction == "in":
            inputs.append(name)
        elif direction == "out":
            outputs.append(name)
    vendor = child_text(root, "vendor")
    library = child_text(root, "library")
    name = child_text(root, "name")
    version = child_text(root, "version")
    vlnv = ":".join((vendor, library, name, version)) if all((vendor, library, name, version)) else ""
    return IpMetadata(name, tuple(sorted(inputs)), tuple(sorted(outputs)), vlnv)


def newest(paths: Iterable[Path]) -> Path | None:
    existing = [path for path in paths if path.is_file()]
    return max(existing, key=lambda path: path.stat().st_mtime, default=None)


def first_file(directory: Path, pattern: str, *, recursive: bool = False) -> Path | None:
    if not directory.is_dir():
        return None
    files = directory.rglob(pattern) if recursive else directory.glob(pattern)
    return next((path for path in sorted(files) if path.is_file()), None)


def stage_complete(stage: int, method_dir: Path, circuit: str, method: str, netlist_dir: Path | None = None) -> bool:
    if stage == 2:
        return (method_dir / "codigos_cpp" / f"{circuit}_{method}.cpp").is_file()
    if stage == 3:
        return (method_dir / "vitis_hls/solution1/impl/ip/component.xml").is_file()
    if stage == 4:
        return (method_dir / "vivado/vivado.xpr").is_file()
    if stage == 5:
        return first_file(method_dir / "vivado", "*_bd_wrapper.vhd", recursive=True) is not None
    vivado = method_dir / "vivado"
    if stage == 6:
        checkpoint = newest((vivado / "vivado.runs/synth_1").glob("*.dcp")) if (vivado / "vivado.runs/synth_1").is_dir() else None
        report = vivado / "reports/timing_synthesis.rpt"
        return bool(checkpoint and report.is_file() and report.stat().st_mtime >= checkpoint.stat().st_mtime)
    if stage == 7:
        synth = newest((vivado / "vivado.runs/synth_1").glob("*.dcp")) if (vivado / "vivado.runs/synth_1").is_dir() else None
        impl = newest((vivado / "vivado.runs/impl_1").glob("*.dcp")) if (vivado / "vivado.runs/impl_1").is_dir() else None
        report = vivado / "reports/timing_implementation.rpt"
        return bool(synth and impl and report.is_file() and impl.stat().st_mtime >= synth.stat().st_mtime and report.stat().st_mtime >= impl.stat().st_mtime)
    if stage == 8:
        xsa = first_file(vivado, "*.xsa")
        bit = newest(vivado.rglob("*.bit"))
        report = vivado / "reports/timing_implementation.rpt"
        return bool(xsa and bit and report.is_file() and xsa.stat().st_mtime >= report.stat().st_mtime and bit.stat().st_mtime >= report.stat().st_mtime)
    if stage == 9:
        fsbl = first_file(method_dir / "vitis", "fsbl.elf", recursive=True)
        xsa = first_file(vivado, "*.xsa")
        return bool(fsbl and xsa and fsbl.stat().st_mtime >= xsa.stat().st_mtime)
    if stage == 10 and netlist_dir:
        boot = netlist_dir / "arquivos_boot" / method / "BOOT.bin"
        fsbl = first_file(method_dir / "vitis", "fsbl.elf", recursive=True)
        xsa = first_file(vivado, "*.xsa")
        return bool(boot.is_file() and fsbl and xsa and boot.stat().st_mtime >= fsbl.stat().st_mtime and boot.stat().st_mtime >= xsa.stat().st_mtime)
    return False


def board_paths(root: Path) -> tuple[Path, Path, Path]:
    repository = root / ".board_files"
    return repository, repository / "Avnet", repository / "Avnet/zedboard/1.4"


def install_board_files(version_directory: Path) -> None:
    missing = [name for name in BOARD_FILES if not (version_directory / name).is_file()]
    if not missing:
        ok(f"ZedBoard Avnet 1.4 encontrada em '{version_directory}'.")
        return
    info("ZedBoard Avnet 1.4 nao encontrada. Baixando do Xilinx Board Store...")
    version_directory.mkdir(parents=True, exist_ok=True)
    try:
        for name in BOARD_FILES:
            urllib.request.urlretrieve(f"{BOARD_STORE_BASE_URL}/{name}", version_directory / name)
    except Exception as exc:
        raise AutomationError(f"Nao foi possivel instalar automaticamente a ZedBoard Avnet 1.4: {exc}") from exc
    ok(f"ZedBoard Avnet 1.4 instalada em '{version_directory}'.")


def entrypoint(main_function) -> None:
    try:
        code = main_function()
    except KeyboardInterrupt:
        print("\nExecucao cancelada pelo usuario.")
        code = 130
    except AutomationError as exc:
        print(f"[ERRO] {exc}", file=sys.stderr)
        code = 1
    except Exception as exc:
        print(f"[ERRO] {exc}", file=sys.stderr)
        code = 1
    raise SystemExit(0 if code is None else code)
