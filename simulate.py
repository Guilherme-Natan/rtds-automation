#!/usr/bin/env python3
"""Executa simulacoes Vivado e gera comparacoes com o PSIM."""

from __future__ import annotations

import math
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))

from common import (
    METHODS,
    PROJECT_DIR,
    SIMULATION_TYPES,
    AutomationError,
    circuit_files,
    entrypoint,
    find_tool,
    find_vivado,
    ip_metadata,
    netlist_time_step,
    pulse_divider,
    resolve_file,
    rtds_root,
    run,
    stage_complete,
    tcl_path,
    write_utf8,
)
from stages import (
    check_requirements,
    create_block_design,
    create_ip,
    create_vivado_project,
    generate_cpp,
    implement_vivado,
    synthesize_vivado,
)
from cli import Cancelled, input_value, select


TYPE_ALIASES = {
    "behavioral": "behavioral",
    "behavorial": "behavioral",
    "synthesis": "synthesis",
    "sintese": "synthesis",
    "synthesis-timing": "synthesis-timing",
    "sintese-timing": "synthesis-timing",
    "implementation": "implementation",
    "implementacao": "implementation",
    "implementation-timing": "implementation-timing",
    "implementacao-timing": "implementation-timing",
}


@dataclass
class Config:
    netlist: Path
    methods: list[str]
    simulation_types: list[str]
    outputs: list[str]
    hard_reset: bool = False
    soft_reset: bool = False
    save_csv: bool = False
    serial_window: float = 1.0
    amplitude: float = 5.0
    prepared_methods: set[str] = field(default_factory=set)
    requirements_checked: bool = False


def _nonnegative(value: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise ValueError("Use um numero maior ou igual a zero.") from exc
    if result < 0:
        raise ValueError("Use um numero maior ou igual a zero.")
    return result


def _amplitude(value: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise ValueError("Informe uma amplitude entre 0 e 5.") from exc
    if not math.isfinite(result) or not 0 <= result <= 5:
        raise ValueError("Informe uma amplitude entre 0 e 5.")
    return 0.0 if result == 0 else result


def _amplitude_codes(amplitude: float) -> tuple[str, str]:
    minimum = round((5 - amplitude) * 4095 / 10)
    maximum = round((5 + amplitude) * 4095 / 10)
    return f"{minimum:03X}", f"{maximum:03X}"


def _available_outputs(netlist: Path, methods: list[str]) -> list[str]:
    method_root = rtds_root() / netlist.stem
    for method in methods:
        component = method_root / method / "vitis_hls/solution1/impl/ip/component.xml"
        if component.is_file():
            return list(ip_metadata(component).outputs)
    source = ""
    for method in methods:
        cpp = method_root / method / "codigos_cpp" / f"{netlist.stem}_{method}.cpp"
        if cpp.is_file():
            source = cpp.read_text(encoding="utf-8", errors="replace")
            break
    if not source:
        executable = find_tool("rtds-vitis")
        arguments = [netlist, f"--{methods[0]}"]
        time_step = netlist_time_step(netlist)
        if time_step is not None:
            arguments += ["--time-step", format(time_step, ".17g")]
        source = run([executable, *arguments], capture=True).stdout
    signature = re.search(r"\bvoid\s+[A-Za-z_]\w*\s*\((.*?)\)\s*\{", source, re.DOTALL)
    if not signature:
        raise AutomationError("Nao foi possivel localizar a funcao principal no C++ gerado.")
    outputs = sorted(set(re.findall(r"\*\s*([A-Za-z_]\w*)", signature.group(1))))
    if not outputs:
        raise AutomationError("Nenhuma saida foi encontrada no circuito selecionado.")
    return outputs


def _prepare_until_five(config: Config) -> None:
    time_step = netlist_time_step(config.netlist)
    if time_step is None or time_step <= 0:
        raise AutomationError("Defina .STEP no netlist para preparar o block design.")
    divider = pulse_divider(time_step)
    root = rtds_root()
    pending: list[tuple[str, int]] = []
    for method in config.methods:
        method_dir = root / config.netlist.stem / method
        start = 2 if config.hard_reset else next((stage for stage in range(2, 6) if not stage_complete(stage, method_dir, config.netlist.stem, method)), 6)
        if start <= 5:
            pending.append((method, start))
    if not pending:
        return
    print("Preparando os projetos antes da escolha das saidas...")
    print("=== Verificacao de requisitos ===")
    check_requirements()
    config.requirements_checked = True
    for method, start in pending:
        print(f"\n=== Preparacao de {method} a partir da etapa {start} ===")
        if start <= 2:
            generate_cpp(config.netlist, method, time_step)
        if start <= 3:
            create_ip(config.netlist, method, 15.0)
        if start <= 4:
            create_vivado_project(config.netlist, method)
        if start <= 5:
            create_block_design(config.netlist, method, time_step, divider)
        config.prepared_methods.add(method)


def _interactive_config(reset_flag: str | None) -> Config:
    files = circuit_files()
    netlist = files[select("Escolha o circuito", [path.name for path in files])[0]]
    indexes = select("Escolha os metodos", list(METHODS), multiple=True)
    config = Config(
        netlist=netlist,
        methods=[METHODS[index] for index in indexes],
        simulation_types=[],
        outputs=[],
        hard_reset=reset_flag == "--hard-reset",
        soft_reset=reset_flag == "--soft-reset",
    )
    _prepare_until_five(config)
    outputs = _available_outputs(netlist, config.methods)
    indexes = select("Escolha as saidas para simular", outputs, multiple=True)
    config.outputs = [outputs[index] for index in indexes]
    labels = ["Behavioral", "Sintese", "Sintese com timing", "Implementacao", "Implementacao com timing"]
    indexes = select("Escolha os tipos de simulacao", labels, multiple=True)
    config.simulation_types = [SIMULATION_TYPES[index] for index in indexes]
    config.serial_window = input_value(
        "Serial window",
        "Informe o valor em ns. Enter usa 1 ns; Ctrl+C cancela.",
        default="1",
        validator=_nonnegative,
    )
    config.amplitude = input_value(
        "Amplitude da onda quadrada",
        "Informe o pico em V, entre 0 e 5. Enter usa 5 V; Ctrl+C cancela.",
        default="5",
        validator=_amplitude,
    )
    config.save_csv = select("Salvar tambem os arquivos CSV?", ["Nao", "Sim"])[0] == 1
    return config


def _argument_config(arguments: list[str]) -> Config:
    if len(arguments) < 3:
        raise AutomationError(
            "Uso: python simulate.py <netlist> <--forward|--backward|--trapezoidal|--all> "
            "<behavioral|synthesis|synthesis-timing|implementation|implementation-timing> [saidas...] [opcoes]"
        )
    netlist = Path(arguments[0])
    methods: list[str] = []
    all_methods = False
    types: list[str] = []
    outputs: list[str] = []
    hard_reset = soft_reset = save_csv = False
    serial_window = 1.0
    amplitude = 5.0
    index = 1
    while index < len(arguments):
        argument = arguments[index]
        if argument in ("--forward", "--backward", "--trapezoidal"):
            methods.append(argument[2:])
        elif argument == "--all":
            all_methods = True
        elif argument == "--hard-reset":
            hard_reset = True
        elif argument == "--soft-reset":
            soft_reset = True
        elif argument == "--csv":
            save_csv = True
        elif argument == "--serial-window":
            index += 1
            if index >= len(arguments):
                raise AutomationError("Informe um valor depois de --serial-window.")
            serial_window = _nonnegative(arguments[index])
        elif argument == "--amplitude":
            index += 1
            if index >= len(arguments):
                raise AutomationError("Informe um valor depois de --amplitude.")
            amplitude = _amplitude(arguments[index])
        elif argument in TYPE_ALIASES:
            types.append(TYPE_ALIASES[argument])
        elif argument.startswith("--"):
            raise AutomationError(f"Opcao desconhecida: '{argument}'.")
        elif not types:
            raise AutomationError(f"Argumento desconhecido antes do tipo de simulacao: '{argument}'.")
        else:
            outputs.append(argument)
        index += 1
    if hard_reset and soft_reset:
        raise AutomationError("Escolha somente --hard-reset ou --soft-reset.")
    if all_methods and methods:
        raise AutomationError("--all nao pode ser combinado com outros metodos.")
    if all_methods:
        methods = list(METHODS)
    methods = list(dict.fromkeys(methods))
    types = list(dict.fromkeys(types))
    if not methods or not types:
        raise AutomationError("Informe pelo menos um metodo e um tipo de simulacao.")
    return Config(
        netlist=netlist,
        methods=methods,
        simulation_types=types,
        outputs=outputs,
        hard_reset=hard_reset,
        soft_reset=soft_reset,
        save_csv=save_csv,
        serial_window=serial_window,
        amplitude=amplitude,
    )


def _parse_config() -> Config:
    reset = sys.argv[1] if len(sys.argv) == 2 and sys.argv[1] in ("--hard-reset", "--soft-reset") else None
    if len(sys.argv) == 1 or reset:
        return _interactive_config(reset)
    return _argument_config(sys.argv[1:])


def _psim_file(netlist: Path, amplitude: float) -> Path:
    amplitude_label = str(amplitude).removesuffix(".0")
    filenames = [f"psim_{amplitude_label}.csv"]
    if amplitude == 5:
        filenames.append("psim.csv")
    for filename in filenames:
        for directory in ("simulacoes", "simulacao"):
            candidate = netlist.parent / directory / filename
            if candidate.is_file():
                if directory == "simulacao":
                    print(f"[AVISO] Usando o caminho legado '{candidate}'. O diretorio padrao e 'simulacoes'.")
                return candidate
    raise AutomationError(f"CSV do PSIM nao encontrado para amplitude {amplitude_label}: {', '.join(filenames)} em 'simulacoes' ou 'simulacao'.")


def _run_simulations(config: Config) -> None:
    netlist = config.netlist
    time_step = netlist_time_step(netlist)
    if time_step is None or time_step <= 0:
        raise AutomationError("Defina .STEP no netlist para preparar o block design.")
    divider = pulse_divider(time_step)
    psim = _psim_file(netlist, config.amplitude)
    template = PROJECT_DIR / "templates/simulation.template.tcl"
    converter = PROJECT_DIR / "scripts/gerar_graficos.py"
    if not template.is_file() or not converter.is_file():
        raise AutomationError("Template de simulacao ou conversor de graficos nao encontrado.")
    vivado = find_vivado()
    root = rtds_root()
    print("=== Verificacao de requisitos ===")
    if config.requirements_checked:
        print("[OK] Requisitos ja verificados durante a preparacao da CLI interativa.")
    else:
        check_requirements()
    required_stage = 7 if any(item.startswith("implementation") for item in config.simulation_types) else 6 if any(item.startswith("synthesis") for item in config.simulation_types) else 5
    for method in config.methods:
        print(f"\n=== Preparacao da simulacao para {method} ===")
        method_dir = root / netlist.stem / method
        if config.hard_reset:
            start = 6 if method in config.prepared_methods else 2
        else:
            start = next((stage for stage in range(2, required_stage + 1) if not stage_complete(stage, method_dir, netlist.stem, method)), required_stage + 1)
        flow_changed = start <= required_stage or method in config.prepared_methods
        if start <= required_stage:
            print(f"Preparando o projeto a partir da etapa {start} ate a etapa {required_stage}...")
            if start <= 2:
                generate_cpp(netlist, method, time_step)
            if start <= 3:
                create_ip(netlist, method, 15.0)
            if start <= 4:
                create_vivado_project(netlist, method)
            if start <= 5:
                create_block_design(netlist, method, time_step, divider)
            if required_stage >= 6 and start <= 6:
                synthesize_vivado(netlist, method)
            if required_stage >= 7 and start <= 7:
                implement_vivado(netlist, method)
        else:
            print(f"[OK] Projeto ja esta pronto ate a etapa {required_stage}.")
        metadata = ip_metadata(method_dir / "vitis_hls/solution1/impl/ip/component.xml")
        selected = list(config.outputs)
        if not selected:
            print(f"Saidas disponiveis para {method}: {', '.join(metadata.outputs)}")
            selected = [item for item in re.split(r"[,\s]+", input("Digite uma ou mais saidas: ").strip()) if item]
        for output in selected:
            if output not in metadata.outputs:
                raise AutomationError(f"Saida '{output}' invalida. Disponiveis: {', '.join(metadata.outputs)}.")
        design = f"{metadata.name}_bd"
        wrapper = f"{design}_wrapper"
        project = method_dir / "vivado/vivado.xpr"
        comparison_root = netlist.parent / "comparacoes" / method
        bd_refreshed = False
        for simulation_type in config.simulation_types:
            launch = {
                "behavioral": "launch_simulation -simset sim_1 -mode behavioral",
                "synthesis": "launch_simulation -simset sim_1 -mode post-synthesis -type functional",
                "synthesis-timing": "launch_simulation -simset sim_1 -mode post-synthesis -type timing",
                "implementation": "launch_simulation -simset sim_1 -mode post-implementation -type functional",
                "implementation-timing": "launch_simulation -simset sim_1 -mode post-implementation -type timing",
            }[simulation_type]
            open_design = "" if simulation_type == "behavioral" else "open_run synth_1" if simulation_type.startswith("synthesis") else "open_run impl_1"
            close_design = "" if simulation_type == "behavioral" else "catch {close_design}"
            print(f"\n=== Simulacao {method} / {simulation_type} ===")
            for output in selected:
                output_index = metadata.outputs.index(output)
                output_dir = comparison_root / output
                output_dir.mkdir(parents=True, exist_ok=True)
                vcd = output_dir / f"{simulation_type}.vcd"
                image = output_dir / f"{simulation_type}.png"
                csv = output_dir / f"{simulation_type}.csv"
                completion = Path(str(vcd) + ".complete")
                completion_contents = f"amplitude={config.amplitude:.17g}\n"
                previous_completion = completion.read_text(encoding="utf-8") if completion.is_file() else None
                amplitude_matches = previous_completion == completion_contents or (config.amplitude == 5 and previous_completion == "complete\n")
                must_simulate = config.hard_reset or config.soft_reset or flow_changed or not vcd.is_file() or not amplitude_matches
                if must_simulate:
                    completion.unlink(missing_ok=True)
                    select_width = 0 if len(metadata.outputs) <= 1 else 1 if len(metadata.outputs) <= 2 else 2 if len(metadata.outputs) <= 4 else 3
                    switch_forces = [f"add_force {{/{wrapper}/SW{bit}}} {{{(output_index >> bit) & 1} 0ns}}" for bit in range(select_width)]
                    input_forces = []
                    low_code, high_code = _amplitude_codes(config.amplitude)
                    if len(metadata.inputs) == 1:
                        input_forces.append(f"add_force {{/{wrapper}/{design}_i/xadc_slice_16_to_12_Dout}} -radix hex {{{low_code} 0us}} {{{high_code} 500us}} -repeat_every 1ms")
                    elif len(metadata.inputs) == 2:
                        input_forces += [
                            f"add_force {{/{wrapper}/{design}_i/xadc_demultiplexer_out_vpvn}} -radix hex {{{low_code} 0us}} {{{high_code} 500us}} -repeat_every 1ms",
                            f"add_force {{/{wrapper}/{design}_i/xadc_demultiplexer_out_vaux0}} -radix hex {{{high_code} 0us}} {{{low_code} 250us}} {{{high_code} 750us}} -repeat_every 1ms",
                        ]
                    simulation_tcl = method_dir / "simulation_tcl" / output / f"{simulation_type}.tcl"
                    contents = template.read_text(encoding="utf-8")
                    replacements = {
                        "__VCD_PATH__": tcl_path(vcd),
                        "__SIM_TOP__": wrapper,
                        "__DESIGN_NAME__": design,
                        "__SWITCH_FORCES__": "\n".join(switch_forces),
                        "__INPUT_FORCES__": "\n".join(input_forces),
                    }
                    for placeholder, value in replacements.items():
                        contents = contents.replace(placeholder, value)
                    write_utf8(simulation_tcl, contents)
                    runner_tcl = method_dir / f".run_{simulation_type}_simulation.tcl"
                    refresh_bd = ""
                    if simulation_type == "behavioral" and not bd_refreshed:
                        refresh_bd = f"""set bd_file [get_files -quiet {{{design}.bd}}]
if {{[llength $bd_file] != 1}} {{ error "Block design nao encontrado: {design}.bd" }}
generate_target all $bd_file
export_ip_user_files -of_objects $bd_file -no_script -sync -force -quiet
# Descarta o snapshot incremental, que pode manter instancias antigas do BD.
reset_simulation -mode behavioral sim_1
"""
                    runner_contents = f"""open_project {{{tcl_path(project)}}}
{refresh_bd}set_property top {{{wrapper}}} [get_filesets sim_1]
update_compile_order -fileset sim_1
{open_design}
{launch}
source {{{tcl_path(simulation_tcl)}}}
close_sim
{close_design}
close_project
exit
"""
                    write_utf8(runner_tcl, runner_contents)
                    print(f"Simulando a saida {output} (SW = {output_index})...")
                    try:
                        run([vivado, "-mode", "batch", "-nolog", "-nojournal", "-source", runner_tcl])
                    finally:
                        runner_tcl.unlink(missing_ok=True)
                    if refresh_bd:
                        bd_refreshed = True
                    if not vcd.is_file():
                        raise AutomationError(f"VCD nao gerado em '{vcd}'.")
                    completion.write_text(completion_contents, encoding="utf-8")
                else:
                    print(f"[OK] Reutilizando VCD existente de {output}; somente a imagem sera refeita.")
                converter_args = [
                    sys.executable,
                    converter,
                    vcd,
                    "--psim", psim,
                    "--psim-column", output,
                    "--sinal", output,
                    "--serial-window-ns", format(config.serial_window, ".17g"),
                    "--save-image", image,
                ]
                if output.lower().startswith("i"):
                    converter_args.append("--corrente")
                if config.save_csv:
                    converter_args += ["--csv", csv]
                run(converter_args)


def main() -> int:
    if any(argument in ("-h", "--help") for argument in sys.argv[1:]):
        print(
            "Uso:\n"
            "  python simulate.py                 Abre a CLI interativa.\n"
            "  python simulate.py <netlist> <metodo...> <tipo...> [saidas...] [opcoes]\n\n"
            "Metodos: --forward --backward --trapezoidal --all\n"
            "Tipos: behavioral synthesis synthesis-timing implementation implementation-timing\n"
            "Opcoes: --hard-reset --soft-reset --serial-window <ns> "
            "--amplitude <V> (padrao: 5) --csv"
        )
        return 0
    try:
        config = _parse_config()
    except Cancelled:
        return 130
    config.netlist = resolve_file(config.netlist)
    _run_simulations(config)
    print("\nSimulacoes e imagens concluidas.")
    return 0


if __name__ == "__main__":
    entrypoint(main)
