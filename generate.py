#!/usr/bin/env python3
"""Gera, implementa e implanta um circuito RTDS."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))

from common import (
    METHODS,
    AutomationError,
    circuit_files,
    entrypoint,
    ip_metadata,
    netlist_time_step,
    parse_spice_number,
    pulse_divider,
    resolve_file,
    rtds_root,
    stage_complete,
)
from stages import (
    check_requirements,
    copy_boot_to_sd,
    create_block_design,
    create_ip,
    create_vitis_platform,
    create_vivado_project,
    generate_boot_image,
    generate_cpp,
    generate_vivado_artifacts,
    implement_vivado,
    synthesize_vivado,
)
from cli import Cancelled, input_value, select


def _positive_spice(value: str) -> float:
    parsed = parse_spice_number(value)
    if parsed <= 0:
        raise ValueError("O timestep deve ser positivo.")
    return parsed


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError("Use um numero positivo.") from exc
    if parsed <= 0:
        raise ValueError("Use um numero positivo.")
    return parsed


def _interactive_arguments() -> argparse.Namespace:
    files = circuit_files()
    chosen_file = files[select("Escolha o circuito", [path.name for path in files])[0]]
    method_indexes = select("Escolha os metodos", list(METHODS), multiple=True)
    methods = [METHODS[index] for index in method_indexes]
    time_step = netlist_time_step(chosen_file)
    if time_step is None:
        time_step = input_value(
            "Timestep",
            "Informe o timestep em segundos ou notacao SPICE; Ctrl+C cancela.",
            default="",
            validator=_positive_spice,
        )
    ip_clock = input_value(
        "IP clock",
        "Informe o periodo em ns. Enter usa 15 ns; Ctrl+C cancela.",
        default="15",
        validator=_positive_float,
    )
    return argparse.Namespace(netlist=chosen_file, methods=methods, time_step=time_step, ip_clock=ip_clock, hard_reset=False, interactive=True)


def _parse_args() -> argparse.Namespace:
    if len(sys.argv) == 1 or sys.argv[1:] == ["--hard-reset"]:
        reset = sys.argv[1:] == ["--hard-reset"]
        args = _interactive_arguments()
        args.hard_reset = reset
        return args
    parser = argparse.ArgumentParser(prog="python generate.py", description=__doc__)
    parser.add_argument("netlist", type=Path)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true")
    group.add_argument("--methods", nargs="+", choices=METHODS)
    parser.add_argument("--forward", action="store_true")
    parser.add_argument("--backward", action="store_true")
    parser.add_argument("--trapezoidal", action="store_true")
    parser.add_argument("--timestep")
    parser.add_argument("--ip-clock", type=float, default=15.0)
    parser.add_argument("--hard-reset", action="store_true")
    args = parser.parse_args()
    flags = [name for name in METHODS if getattr(args, name)]
    if flags:
        if args.all or args.methods:
            parser.error("os flags --forward/--backward/--trapezoidal nao podem ser combinados com --all/--methods")
        args.methods = flags
    elif args.all:
        args.methods = list(METHODS)
    if not args.methods:
        parser.error("informe --all, --methods ou pelo menos um flag de metodo")
    args.time_step = parse_spice_number(args.timestep) if args.timestep else None
    args.interactive = False
    return args


def _worst_slack(report: Path) -> float | None:
    if not report.is_file():
        return None
    text = report.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"^\s*Setup\s*:.*?Worst Slack\s+([+-]?(?:\d+(?:\.\d*)?|\.\d+))ns", text, re.MULTILINE | re.IGNORECASE)
    if not match:
        match = re.search(r"^\s*Slack\s+\((?:MET|VIOLATED)\)\s*:\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))ns", text, re.MULTILINE | re.IGNORECASE)
    return float(match.group(1)) if match else None


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    widths = [len(header) for header in headers]
    for row in rows:
        widths = [max(width, len(str(cell))) for width, cell in zip(widths, row)]
    format_row = lambda row: " | ".join(str(cell).ljust(width) for cell, width in zip(row, widths)).rstrip()
    return [format_row(headers), "-+-".join("-" * width for width in widths), *(format_row(row) for row in rows)]


def _write_summary(circuit: str, netlist_dir: Path, root: Path, methods: list[str]) -> None:
    metadata = ip_metadata(root / circuit / methods[0] / "vitis_hls/solution1/impl/ip/component.xml")
    for method in methods[1:]:
        other = ip_metadata(root / circuit / method / "vitis_hls/solution1/impl/ip/component.xml")
        if other.inputs != metadata.inputs or other.outputs != metadata.outputs:
            raise AutomationError("As portas dos IPs diferem; nao e possivel gerar um resumo unico.")
    lines = ["=" * 60, "                     RESUMO FINAL RTDS", "=" * 60, f"Circuito: {circuit}", f"Metodos : {', '.join(methods)}", "", "TIMING SLACK", "------------"]
    timing_rows = []
    for method in methods:
        vivado = root / circuit / method / "vivado/reports"
        synthesis = _worst_slack(vivado / "timing_synthesis.rpt")
        implementation = _worst_slack(vivado / "timing_implementation.rpt")
        status = "INCOMPLETO" if synthesis is None or implementation is None else "OK" if synthesis >= 0 and implementation >= 0 else "ERRO"
        timing_rows.append([method, "N/D" if synthesis is None else f"{synthesis:.3f} ns", "N/D" if implementation is None else f"{implementation:.3f} ns", status])
    lines += _table(["Metodo", "Sintese", "Implementacao", "Status"], timing_rows)
    lines += ["", "CONEXOES DA ZEDBOARD", "--------------------"]
    connections: list[list[str]] = []
    seen: set[str] = set()
    pattern = re.compile(r"^\s*set_property\s+PACKAGE_PIN\s+(\S+)\s+\[get_ports\s+\{?([^}\]\s]+)", re.IGNORECASE)
    for constraint in sorted((Path(__file__).resolve().parent / "arquivos_vivado/constraints").rglob("*.xdc")):
        for line in constraint.read_text(encoding="utf-8", errors="replace").splitlines():
            match = pattern.match(line)
            if not match or re.match(r"^(?:SW\d+|GCLK)$", match.group(2), re.IGNORECASE) or match.group(2).lower() in seen:
                continue
            seen.add(match.group(2).lower())
            comment = re.search(r'#\s*"?([^"\r\n]+?)"?\s*$', line)
            connections.append([match.group(2), comment.group(1).strip() if comment else match.group(2)])
    if metadata.inputs:
        connections.append([metadata.inputs[0], "VP: pino 2; VN: pino 1"])
    if len(metadata.inputs) >= 2:
        connections.append([metadata.inputs[1], "VAUX0P: pino 3; VAUX0N: pino 6"])
    lines += _table(["Sinal", "ZedBoard"], connections)
    lines += ["", "SELECAO DAS SAIDAS", "------------------"]
    select_width = 0 if len(metadata.outputs) <= 1 else 1 if len(metadata.outputs) <= 2 else 2 if len(metadata.outputs) <= 4 else 3
    if select_width == 0:
        lines.append(f"Nenhuma chave de selecao e necessaria. Saida fixa: {metadata.outputs[0]}")
    else:
        lines.append("SW0 e o bit menos significativo do codigo de selecao.")
        rows = []
        for code in range(2**select_width):
            rows.append([str((code >> bit) & 1) for bit in range(select_width)] + [metadata.outputs[code] if code < len(metadata.outputs) else "0 (nao utilizada)"])
        lines += _table([*(f"SW{bit}" for bit in range(select_width)), "Saida"], rows)
    lines.append("=" * 60)
    summary = netlist_dir / "arquivos_boot" / f"{circuit}_resumo.txt"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nResumo salvo em '{summary}'.")


def main() -> int:
    try:
        args = _parse_args()
    except Cancelled:
        return 130
    netlist = resolve_file(args.netlist)
    time_step = args.time_step if args.time_step is not None else netlist_time_step(netlist)
    if time_step is None or time_step <= 0:
        raise AutomationError("Informe --timestep ou defina .STEP no netlist.")
    if args.ip_clock <= 0:
        raise AutomationError("Clock do IP invalido.")
    divider = pulse_divider(time_step)
    print("=== Etapa 1: preparacao da placa e verificacao de requisitos ===")
    check_requirements()
    root = rtds_root()
    for method in args.methods:
        method_dir = root / netlist.stem / method
        start_stage = 2 if args.hard_reset else next((stage for stage in range(2, 11) if not stage_complete(stage, method_dir, netlist.stem, method, netlist.parent)), 11)
        print()
        if start_stage == 11:
            ok_message = f"[OK] As etapas de geracao de '{method}' ja foram concluidas."
            print(ok_message)
        else:
            print(("Hard reset solicitado" if args.hard_reset else "Retomando") + f" '{method}' a partir da etapa {start_stage}.")
        actions = (
            (2, "geracao do codigo C++", lambda: generate_cpp(netlist, method, time_step)),
            (3, "criacao e implementacao do IP", lambda: create_ip(netlist, method, args.ip_clock)),
            (4, "criacao do projeto Vivado", lambda: create_vivado_project(netlist, method)),
            (5, "criacao do block design", lambda: create_block_design(netlist, method, time_step, divider)),
            (6, "sintese e verificacao de slack", lambda: synthesize_vivado(netlist, method)),
            (7, "implementacao e verificacao de slack", lambda: implement_vivado(netlist, method)),
            (8, "bitstream e exportacao do hardware", lambda: generate_vivado_artifacts(netlist, method)),
            (9, "plataforma Vitis e build do FSBL", lambda: create_vitis_platform(netlist, method)),
            (10, "geracao da imagem de boot", lambda: generate_boot_image(netlist, method)),
        )
        for stage, title, action in actions:
            if start_stage <= stage:
                print(f"=== Etapa {stage}: {title} ===")
                action()
        print("=== Etapa 11: envio da imagem de boot para o cartao SD ===")
        copy_boot_to_sd(netlist, method)
    if args.interactive:
        os.system("cls" if os.name == "nt" else "clear")
    _write_summary(netlist.stem, netlist.parent, root, list(args.methods))
    return 0


if __name__ == "__main__":
    entrypoint(main)
