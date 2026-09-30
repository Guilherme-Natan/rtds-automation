"""Implementacao Python das onze etapas do fluxo RTDS."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from common import (
    BOARD_DEVICE_PART,
    BOARD_PART,
    PROJECT_DIR,
    AutomationError,
    board_paths,
    find_tool,
    find_vivado,
    first_file,
    install_board_files,
    ip_metadata,
    method_names,
    ok,
    rtds_root,
    run,
    tcl_path,
    write_utf8,
)


def _require(path: Path, message: str) -> Path:
    if not path.exists():
        raise AutomationError(message)
    return path


def _run_temporary(tool: Path, arguments: list[str], temporary_file: Path, contents: str) -> None:
    write_utf8(temporary_file, contents)
    try:
        run([tool, *arguments, temporary_file])
    finally:
        temporary_file.unlink(missing_ok=True)


def _method_context(netlist: Path, method: str):
    circuit = netlist.stem
    root = rtds_root()
    for name in method_names(method):
        yield circuit, name, root / circuit / name


def check_requirements() -> None:
    print("Preparando a ZedBoard Avnet 1.4 e verificando requisitos do ambiente...\n")
    _, _, version_dir = board_paths(rtds_root())
    install_board_files(version_dir)
    checks = (
        ("rtds-circuit-analysis", None, ["-h"]),
        ("vitis_hls", "Vitis_HLS", ["-version"]),
        ("vivado", "Vivado", ["-version"]),
        ("vitis", "Vitis", ["-version"]),
    )
    failures: list[str] = []
    for command, product, arguments in checks:
        try:
            executable = find_tool(command, product)
            result = subprocess.run(
                [str(executable), *arguments],
                text=True,
                capture_output=True,
                check=False,
            )
            output = (result.stdout or "") + (result.stderr or "")
            # O launcher vitis.bat 2022.2 pode retornar -1 (exibido como
            # 4294967295) para `-version`, apesar de imprimir uma versao valida.
            valid_vitis_banner = command == "vitis" and re.search(
                r"(?im)^Vitis\s+v\d+(?:\.\d+)*\b", output
            )
            if result.returncode != 0 and not valid_vitis_banner:
                details = output.strip() or "nenhuma mensagem de erro foi fornecida."
                raise AutomationError(
                    f"'{executable.name}' terminou com codigo {result.returncode}: {details}"
                )
            first_line = next(
                (line.strip() for line in output.splitlines() if line.strip()),
                str(executable),
            )
            ok(f"{command} - {first_line}")
        except OSError as exc:
            print(f"[ERRO] {command} - o comando falhou ao executar: {exc}")
            failures.append(command)
        except AutomationError as exc:
            print(f"[ERRO] {command} - {exc}")
            failures.append(command)
    if failures:
        raise AutomationError(f"Verificacao reprovada: {len(failures)} requisito(s) ausente(s) ou invalido(s).")
    ok("Todos os requisitos estao disponiveis.")


def generate_cpp(netlist: Path, method: str, time_step: float | None = None) -> None:
    supported = {".cir", ".sp", ".spi", ".spice", ".ckt", ".net"}
    if netlist.suffix.lower() not in supported:
        raise AutomationError(f"Extensao '{netlist.suffix}' nao suportada. Use: {', '.join(sorted(supported))}.")
    executable = find_tool("rtds-vitis")
    for circuit, name, method_dir in _method_context(netlist, method):
        output = method_dir / "codigos_cpp" / f"{circuit}_{name}.cpp"
        output.parent.mkdir(parents=True, exist_ok=True)
        arguments = [str(netlist), f"--{name}"]
        if time_step is not None:
            arguments += ["--time-step", format(time_step, ".17g")]
        print(f"Gerando codigo C++ pelo metodo {name}...")
        result = run([executable, *arguments], capture=True)
        write_utf8(output, result.stdout)
        ok(f"Codigo salvo em '{output}'.")


def _top_function(cpp_file: Path) -> str:
    source = cpp_file.read_text(encoding="utf-8", errors="replace")
    functions = list(dict.fromkeys(re.findall(
        r"(?m)^\s*(?!if\b|for\b|while\b|switch\b)(?:[A-Za-z_]\w*[\s*&]+)+([A-Za-z_]\w*)\s*\([^;]*\)\s*\{",
        source,
    )))
    if len(functions) != 1:
        raise AutomationError(
            f"Era esperada uma unica funcao em '{cpp_file}', mas foram encontradas {len(functions)}: {', '.join(functions)}."
        )
    return functions[0]


def _hls_timing(hls_project: Path, top: str) -> tuple[float, float, float, float]:
    report = hls_project / "solution1/syn/report" / f"{top}_csynth.rpt"
    _require(report, f"Relatorio de sintese nao encontrado em '{report}'.")
    clock_row = next((line for line in report.read_text(encoding="utf-8", errors="replace").splitlines() if re.match(r"^\s*\|\s*(?:ap_clk|default)\s*\|", line)), None)
    if not clock_row:
        raise AutomationError(f"Dados de timing nao encontrados em '{report}'.")
    values = [value.strip() for value in clock_row.split("|") if value.strip()]
    numbers = [re.search(r"\d+(?:\.\d+)?", value) for value in values[1:4]]
    if len(numbers) != 3 or any(match is None for match in numbers):
        raise AutomationError(f"Formato de timing inesperado em '{report}'.")
    implementation = hls_project / "solution1/impl/report/vhdl" / f"{top}_export.rpt"
    _require(implementation, f"Relatorio de implementacao VHDL nao encontrado em '{implementation}'.")
    achieved = re.search(r"^CP achieved post-synthesis:\s*(\d+(?:\.\d+)?)", implementation.read_text(encoding="utf-8", errors="replace"), re.MULTILINE | re.IGNORECASE)
    if not achieved:
        raise AutomationError(f"Periodo implementado nao encontrado em '{implementation}'.")
    target, estimated, uncertainty = (float(match.group()) for match in numbers if match)
    return target, estimated, uncertainty, float(achieved.group(1))


def create_ip(netlist: Path, method: str, ip_clock: float) -> None:
    if ip_clock <= 0:
        raise AutomationError("O periodo do clock do IP deve ser positivo.")
    vitis_hls = find_tool("vitis_hls", "Vitis_HLS")
    for circuit, name, method_dir in _method_context(netlist, method):
        cpp_file = method_dir / "codigos_cpp" / f"{circuit}_{name}.cpp"
        _require(cpp_file, f"Codigo C++ nao encontrado em '{cpp_file}'.")
        top = _top_function(cpp_file)
        hls_project = method_dir / "vitis_hls"
        tcl_file = method_dir / ".create_ip.tcl"
        contents = f"""cd {{{tcl_path(method_dir)}}}
open_project -reset vitis_hls
set_top {{{top}}}
add_files {{{tcl_path(cpp_file)}}}
open_solution -reset solution1 -flow_target vivado
set_part {{{BOARD_DEVICE_PART}}}
create_clock -period {ip_clock:.17g} -name default
config_export -format ip_catalog -rtl vhdl
csynth_design
export_design -flow impl -rtl vhdl -format ip_catalog
exit
"""
        print(f"Criando IP '{top}' para {name} (clock: {ip_clock:.17g} ns)...")
        _run_temporary(vitis_hls, ["-f"], tcl_file, contents)
        target, estimated, uncertainty, implemented = _hls_timing(hls_project, top)
        print("\n============================================================")
        print(f"  RESULTADO DE TIMING - {name}")
        print("============================================================")
        print(f"  Periodo solicitado    : {target} ns")
        print(f"  Periodo estimado HLS  : {estimated} ns")
        print(f"  Periodo implementado  : {implemented} ns")
        print(f"  Uncertainty           : {uncertainty} ns")
        print("============================================================")
        if implemented > target:
            raise AutomationError(f"O periodo implementado ({implemented} ns) excede o solicitado ({target} ns).")
        ok(f"IP sintetizado e implementado em VHDL em '{hls_project}'.")


def create_vivado_project(netlist: Path, method: str) -> None:
    sources_dir = PROJECT_DIR / "arquivos_vivado/sources_vhdl"
    constraints_dir = PROJECT_DIR / "arquivos_vivado/constraints"
    _require(sources_dir, f"Pasta de sources nao encontrada em '{sources_dir}'.")
    _require(constraints_dir, f"Pasta de constraints nao encontrada em '{constraints_dir}'.")
    constraints = sorted(path for path in constraints_dir.rglob("*.xdc") if path.is_file())
    if not constraints:
        raise AutomationError(f"Nenhum arquivo XDC encontrado em '{constraints_dir}'.")
    vivado = find_vivado()
    root = rtds_root()
    _, avnet_repository, _ = board_paths(root)
    for circuit, name, method_dir in _method_context(netlist, method):
        project_dir = method_dir / "vivado"
        hls_repository = method_dir / "vitis_hls"
        component = hls_repository / "solution1/impl/ip/component.xml"
        metadata = ip_metadata(component)
        if len(metadata.inputs) > 2:
            raise AutomationError(f"O fluxo aceita no maximo 2 entradas analogicas; o IP possui {len(metadata.inputs)}.")
        if not 1 <= len(metadata.outputs) <= 8:
            raise AutomationError(f"O fluxo aceita de 1 a 8 saidas; o IP possui {len(metadata.outputs)}.")
        required = ["clock_divider.vhd", "dac.vhd", "power_on_reset.vhd", "pulse_generators.vhd", "registrador.vhd"]
        if metadata.inputs:
            required.append("input_map.vhd")
        if len(metadata.inputs) == 2:
            required.append("demultiplexer_xadc.vhd")
        if any(output.lower().startswith("v") for output in metadata.outputs):
            required.append("output_map.vhd")
        if any(output.lower().startswith("i") for output in metadata.outputs):
            required.append("output_map_current.vhd")
        if len(metadata.outputs) == 2:
            required.append("multiplexer_output_2.vhd")
        elif len(metadata.outputs) in (3, 4):
            required.append("multiplexer_output_4.vhd")
        elif len(metadata.outputs) >= 5:
            required.append("multiplexer_output_8.vhd")
        source_files = []
        for source_name in dict.fromkeys(required):
            source = sources_dir / source_name
            _require(source, f"Source necessario nao encontrado: '{source}'.")
            source_files.append(source)
        sources_tcl = " ".join(f"{{{tcl_path(path)}}}" for path in source_files)
        constraints_tcl = " ".join(f"{{{tcl_path(path)}}}" for path in constraints)
        tcl = f"""set_param board.repoPaths [list {{{tcl_path(avnet_repository)}}}]
set selected_board [get_board_parts -quiet {{{BOARD_PART}}}]
if {{[llength $selected_board] != 1}} {{ error "ZedBoard Avnet 1.4 nao foi reconhecida pelo Vivado: {BOARD_PART}" }}
create_project vivado {{{tcl_path(project_dir)}}} -part {{{BOARD_DEVICE_PART}}} -force
set_property board_part {{{BOARD_PART}}} [current_project]
set_property target_language VHDL [current_project]
import_files -fileset sources_1 [list {sources_tcl}]
import_files -fileset constrs_1 [list {constraints_tcl}]
set_property ip_repo_paths [list {{{tcl_path(hls_repository)}}}] [current_project]
update_ip_catalog
update_compile_order -fileset sources_1
close_project
exit
"""
        method_dir.mkdir(parents=True, exist_ok=True)
        temporary = method_dir / ".create_vivado_project.tcl"
        print(f"Criando projeto Vivado para {name}...")
        _run_temporary(vivado, ["-mode", "batch", "-nolog", "-nojournal", "-source"], temporary, tcl)
        project_file = project_dir / "vivado.xpr"
        _require(project_file, f"Projeto Vivado nao foi criado em '{project_file}'.")
        ok(f"Projeto Vivado criado em '{project_file}'.")


def create_block_design(netlist: Path, method: str, time_step: float, pulse_divider: int) -> None:
    template = PROJECT_DIR / "templates/circuit_block_design.template.tcl"
    _require(template, f"Template TCL nao encontrado em '{template}'.")
    vivado = find_vivado()
    frequency_mhz = (1.0 / time_step) / 1_000_000.0
    frequency_text = str(round(frequency_mhz)) if abs(frequency_mhz - round(frequency_mhz)) < 1e-9 else format(frequency_mhz, ".9g")
    frequency_label = re.sub(r"[^0-9A-Za-z]", "_", frequency_text)
    for _, name, method_dir in _method_context(netlist, method):
        vivado_dir = method_dir / "vivado"
        project_file = vivado_dir / "vivado.xpr"
        component = method_dir / "vitis_hls/solution1/impl/ip/component.xml"
        _require(project_file, f"Projeto Vivado nao encontrado em '{project_file}'.")
        metadata = ip_metadata(component)
        if len(metadata.inputs) > 2 or not 1 <= len(metadata.outputs) <= 8:
            raise AutomationError("O IP deve possuir no maximo duas entradas e de uma a oito saidas.")
        output_types = []
        for output in metadata.outputs:
            if output.lower().startswith("v"):
                output_types.append("V")
            elif output.lower().startswith("i"):
                output_types.append("I")
            else:
                raise AutomationError(f"A saida '{output}' deve comecar com V (tensao) ou I (corrente).")
        mux_size = 1 if len(metadata.outputs) == 1 else 2 if len(metadata.outputs) == 2 else 4 if len(metadata.outputs) <= 4 else 8
        design_name = f"{metadata.name}_bd"
        generated = vivado_dir / f"{design_name}.tcl"
        contents = template.read_text(encoding="utf-8")
        replacements = {
            "__DESIGN_NAME__": design_name,
            "__HLS_IP_VLNV__": metadata.vlnv,
            "__IP_NAME__": metadata.name,
            "__INPUT_NAMES__": " ".join(f"{{{item}}}" for item in metadata.inputs),
            "__OUTPUT_NAMES__": " ".join(f"{{{item}}}" for item in metadata.outputs),
            "__OUTPUT_TYPES__": " ".join(f"{{{item}}}" for item in output_types),
            "__PULSE_DIVISOR__": str(pulse_divider),
            "__PULSE_FREQUENCY_LABEL__": frequency_label,
            "__MUX_SIZE__": str(mux_size),
        }
        for placeholder, value in replacements.items():
            contents = contents.replace(placeholder, value)
        remaining = re.search(r"__[A-Z0-9_]+__", contents)
        if remaining:
            raise AutomationError(f"O TCL gerado ainda contem placeholder: {remaining.group()}.")
        write_utf8(generated, contents)
        runner = f"""open_project {{{tcl_path(project_file)}}}
source {{{tcl_path(generated)}}}
set bd_file [get_files -quiet {{{design_name}.bd}}]
if {{[llength $bd_file] != 1}} {{ error "Block design nao foi criado: {design_name}" }}
generate_target all $bd_file
export_ip_user_files -of_objects $bd_file -no_script -sync -force -quiet
set wrapper_files [make_wrapper -files $bd_file -top]
add_files -norecurse $wrapper_files
update_compile_order -fileset sources_1
close_project
exit
"""
        temporary = method_dir / ".run_block_design.tcl"
        print(f"Gerando block design '{design_name}'...")
        _run_temporary(vivado, ["-mode", "batch", "-nolog", "-nojournal", "-source"], temporary, runner)
        ok(f"TCL salvo e executado em '{generated}'.")


def synthesize_vivado(netlist: Path, method: str) -> None:
    vivado = find_vivado()
    jobs = max(1, os.cpu_count() or 1)
    for _, name, method_dir in _method_context(netlist, method):
        vivado_dir = method_dir / "vivado"
        project = vivado_dir / "vivado.xpr"
        component = method_dir / "vitis_hls/solution1/impl/ip/component.xml"
        _require(project, f"Projeto Vivado nao encontrado em '{project}'.")
        wrapper = f"{ip_metadata(component).name}_bd_wrapper"
        report = vivado_dir / "reports/timing_synthesis.rpt"
        report.parent.mkdir(parents=True, exist_ok=True)
        tcl = f"""open_project {{{tcl_path(project)}}}
set_property top {{{wrapper}}} [current_fileset]
update_compile_order -fileset sources_1
reset_run synth_1
launch_runs synth_1 -jobs {jobs}
wait_on_run synth_1
set run_status [get_property STATUS [get_runs synth_1]]
if {{![string match "*Complete*" $run_status]}} {{ error "Run 'synth_1' falhou ou nao terminou. Status: $run_status" }}
open_run synth_1
report_timing_summary -delay_type max -max_paths 10 -file {{{tcl_path(report)}}}
set worst_path [get_timing_paths -quiet -delay_type max -max_paths 1 -nworst 1]
if {{[llength $worst_path] == 0}} {{ error "Nao foi possivel encontrar um caminho de timing apos a sintese." }}
set slack [get_property SLACK $worst_path]
puts "SLACK APOS SINTESE: $slack ns"
if {{$slack < 0.0}} {{ error "Timing nao atendido apos sintese: slack $slack ns." }}
close_design
close_project
exit
"""
        print(f"Executando sintese para {name} com {jobs} jobs...")
        _run_temporary(vivado, ["-mode", "batch", "-nolog", "-nojournal", "-source"], method_dir / ".synthesize_vivado.tcl", tcl)
        _require(report, f"Relatorio de sintese nao encontrado em '{report}'.")
        ok(f"Sintese concluida: '{report}'.")


def implement_vivado(netlist: Path, method: str) -> None:
    vivado = find_vivado()
    jobs = max(1, os.cpu_count() or 1)
    for _, name, method_dir in _method_context(netlist, method):
        vivado_dir = method_dir / "vivado"
        project = vivado_dir / "vivado.xpr"
        synthesis_report = vivado_dir / "reports/timing_synthesis.rpt"
        report = vivado_dir / "reports/timing_implementation.rpt"
        _require(project, f"Projeto Vivado nao encontrado em '{project}'.")
        _require(synthesis_report, "Execute a etapa 06 de sintese antes da implementacao.")
        tcl = f"""open_project {{{tcl_path(project)}}}
set synth_status [get_property STATUS [get_runs synth_1]]
if {{![string match "*Complete*" $synth_status]}} {{ error "A sintese nao esta concluida. Status: $synth_status" }}
reset_run impl_1
launch_runs impl_1 -to_step route_design -jobs {jobs}
wait_on_run impl_1
set run_status [get_property STATUS [get_runs impl_1]]
if {{![string match "*Complete*" $run_status]}} {{ error "Run 'impl_1' falhou ou nao terminou. Status: $run_status" }}
open_run impl_1
report_timing_summary -delay_type max -max_paths 10 -file {{{tcl_path(report)}}}
set worst_path [get_timing_paths -quiet -delay_type max -max_paths 1 -nworst 1]
if {{[llength $worst_path] == 0}} {{ error "Nao foi possivel encontrar um caminho de timing apos a implementacao." }}
set slack [get_property SLACK $worst_path]
puts "SLACK APOS IMPLEMENTACAO: $slack ns"
if {{$slack < 0.0}} {{ error "Timing nao atendido apos implementacao: slack $slack ns." }}
close_design
close_project
exit
"""
        print(f"Executando implementacao para {name} com {jobs} jobs...")
        _run_temporary(vivado, ["-mode", "batch", "-nolog", "-nojournal", "-source"], method_dir / ".implement_vivado.tcl", tcl)
        _require(report, f"Relatorio de implementacao nao encontrado em '{report}'.")
        ok(f"Implementacao concluida: '{report}'.")


def generate_vivado_artifacts(netlist: Path, method: str) -> None:
    vivado = find_vivado()
    jobs = max(1, os.cpu_count() or 1)
    for _, name, method_dir in _method_context(netlist, method):
        vivado_dir = method_dir / "vivado"
        project = vivado_dir / "vivado.xpr"
        component = method_dir / "vitis_hls/solution1/impl/ip/component.xml"
        implementation_report = vivado_dir / "reports/timing_implementation.rpt"
        _require(project, f"Projeto Vivado nao encontrado em '{project}'.")
        _require(implementation_report, "Execute a etapa 07 de implementacao antes de gerar os artefatos.")
        wrapper = f"{ip_metadata(component).name}_bd_wrapper"
        hardware = vivado_dir / f"{wrapper}.xsa"
        tcl = f"""open_project {{{tcl_path(project)}}}
set impl_status [get_property STATUS [get_runs impl_1]]
if {{![string match "*Complete*" $impl_status]}} {{ error "A implementacao nao esta concluida. Status: $impl_status" }}
launch_runs impl_1 -to_step write_bitstream -jobs {jobs}
wait_on_run impl_1
set run_status [get_property STATUS [get_runs impl_1]]
if {{![string match "*Complete*" $run_status]}} {{ error "Geracao da bitstream falhou. Status: $run_status" }}
open_run impl_1
write_hw_platform -fixed -include_bit -force -file {{{tcl_path(hardware)}}}
close_design
close_project
exit
"""
        print(f"Gerando bitstream e exportando hardware para {name} com {jobs} jobs...")
        _run_temporary(vivado, ["-mode", "batch", "-nolog", "-nojournal", "-source"], method_dir / ".generate_vivado_artifacts.tcl", tcl)
        _require(hardware, f"Hardware exportado nao encontrado em '{hardware}'.")
        bitstream = first_file(vivado_dir, f"{wrapper}.bit", recursive=True)
        if not bitstream:
            raise AutomationError(f"Bitstream '{wrapper}.bit' nao encontrada no projeto.")
        ok(f"Bitstream: '{bitstream}'.")
        ok(f"Hardware exportado: '{hardware}'.")


def create_vitis_platform(netlist: Path, method: str) -> None:
    xsct = find_tool("xsct", "Vitis")
    for _, name, method_dir in _method_context(netlist, method):
        vivado_dir = method_dir / "vivado"
        vitis_dir = method_dir / "vitis"
        xsa = first_file(vivado_dir, "*.xsa")
        if not xsa:
            raise AutomationError(f"Nenhum XSA encontrado em '{vivado_dir}'.")
        with zipfile.ZipFile(xsa) as archive:
            if not any(entry.lower().endswith(".bit") for entry in archive.namelist()):
                raise AutomationError(f"O XSA '{xsa}' nao contem uma bitstream. Gere o hardware com -include_bit.")
        tcl = f"""setws {{{tcl_path(method_dir)}}}
catch {{platform remove vitis}}
platform create -name vitis -hw {{{tcl_path(xsa)}}} -proc ps7_cortexa9_0 -os standalone
platform active vitis
platform write
platform generate
exit
"""
        print(f"Criando e compilando a plataforma Vitis para {name}...")
        _run_temporary(xsct, [], method_dir / ".create_vitis_platform.tcl", tcl)
        _require(vitis_dir, f"Projeto Vitis nao encontrado em '{vitis_dir}'.")
        fsbl = first_file(vitis_dir, "fsbl.elf", recursive=True)
        if not fsbl:
            raise AutomationError(f"O build da plataforma nao gerou fsbl.elf em '{vitis_dir}'.")
        ok(f"Plataforma Vitis: '{vitis_dir}'.")
        ok(f"FSBL: '{fsbl}'.")


def generate_boot_image(netlist: Path, method: str) -> None:
    bootgen = find_tool("bootgen", "Vitis")
    for _, name, method_dir in _method_context(netlist, method):
        vivado_dir = method_dir / "vivado"
        xsa = first_file(vivado_dir, "*.xsa")
        fsbl = first_file(method_dir / "vitis", "fsbl.elf", recursive=True)
        if not xsa:
            raise AutomationError(f"Nenhum XSA encontrado em '{vivado_dir}'.")
        if not fsbl:
            raise AutomationError(f"FSBL nao encontrado em '{method_dir / 'vitis'}'. Execute primeiro a etapa 09.")
        temporary_bit = method_dir / ".boot_bitstream.bit"
        bif = method_dir / ".boot_image.bif"
        boot_dir = netlist.parent / "arquivos_boot" / name
        boot_dir.mkdir(parents=True, exist_ok=True)
        boot_image = boot_dir / "BOOT.bin"
        try:
            with zipfile.ZipFile(xsa) as archive:
                entry = next((item for item in archive.infolist() if item.filename.lower().endswith(".bit")), None)
                if not entry:
                    raise AutomationError(f"O XSA '{xsa}' nao contem uma bitstream.")
                with archive.open(entry) as source, temporary_bit.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
            write_utf8(bif, f"the_ROM_image:\n{{\n  [bootloader]{tcl_path(fsbl)}\n  {tcl_path(temporary_bit)}\n}}\n")
            print(f"Gerando a imagem de boot para {name}...")
            run([bootgen, "-arch", "zynq", "-image", bif, "-o", boot_image, "-w", "on"])
        finally:
            bif.unlink(missing_ok=True)
            temporary_bit.unlink(missing_ok=True)
        _require(boot_image, f"Imagem de boot nao encontrada em '{boot_image}'.")
        ok(f"Imagem de boot: '{boot_image}'.")


def copy_boot_to_sd(netlist: Path, method: str) -> None:
    if method == "all":
        raise AutomationError("A etapa 11 aceita somente um metodo por vez.")
    boot = netlist.parent / "arquivos_boot" / method / "BOOT.bin"
    _require(boot, f"Imagem de boot nao encontrada em '{boot}'. Execute primeiro a etapa 10.")
    sys.path.insert(0, str(PROJECT_DIR))
    from deploy import deploy  # import tardio evita ciclo entre os comandos

    deploy(boot)
