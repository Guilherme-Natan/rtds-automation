#!/usr/bin/env python3
"""Compara a saída reconstruída do DAC com uma coluna de resultados do PSIM."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, TextIO

import matplotlib

if "--save-image" in sys.argv:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt


_VAR_RE = re.compile(
    r"^\$var\s+\S+\s+\d+\s+(\S+)\s+(\S+)(?:\s+\[[^\]]+\])?\s+\$end$"
)
_TIMESCALE_RE = re.compile(r"^\s*(\d+)\s*(s|ms|us|ns|ps|fs)\s*$")
_UNIT_TO_PS = {
    "s": 10**12,
    "ms": 10**9,
    "us": 10**6,
    "ns": 10**3,
    "ps": 1,
    "fs": 0.001,
}


@dataclass(frozen=True)
class VCDHeader:
    symbols: dict[str, str]
    timescale_ps: float


@dataclass(frozen=True)
class DACSample:
    time_ps: int | float
    value: int


def _read_directive(first_line: str, stream: TextIO) -> str:
    parts = [first_line.strip()]
    while "$end" not in parts[-1]:
        line = stream.readline()
        if not line:
            raise ValueError("Diretiva VCD incompleta no cabeçalho")
        parts.append(line.strip())
    return " ".join(parts)


def read_vcd_header(stream: TextIO) -> VCDHeader:
    """Lê caminhos hierárquicos, símbolos e escala de tempo do VCD."""

    scopes: list[str] = []
    symbols: dict[str, str] = {}
    timescale_ps = 1.0
    while line := stream.readline():
        stripped = line.strip()
        if stripped.startswith("$scope "):
            scopes.append(stripped.split()[2])
        elif stripped.startswith("$upscope"):
            if scopes:
                scopes.pop()
        elif stripped.startswith("$var "):
            match = _VAR_RE.match(_read_directive(stripped, stream))
            if match:
                symbol, reference = match.groups()
                symbols["/".join((*scopes, reference))] = symbol
        elif stripped.startswith("$timescale"):
            directive = _read_directive(stripped, stream)
            content = directive.removeprefix("$timescale").removesuffix("$end")
            match = _TIMESCALE_RE.match(content)
            if not match:
                raise ValueError(f"Escala de tempo VCD inválida: {content!r}")
            magnitude, unit = match.groups()
            timescale_ps = int(magnitude) * _UNIT_TO_PS[unit]
        elif stripped.startswith("$enddefinitions"):
            return VCDHeader(symbols, timescale_ps)
    raise ValueError("O arquivo não contém $enddefinitions")


def resolve_signal(symbols: dict[str, str], requested: str) -> str:
    """Resolve um caminho completo ou um nome de sinal que seja único."""

    normalized = requested.strip("/")
    exact = [(path, symbol) for path, symbol in symbols.items() if path == normalized]
    if exact:
        return exact[0][1]
    matches = [
        (path, symbol)
        for path, symbol in symbols.items()
        if path.rsplit("/", 1)[-1] == requested
    ]
    if len(matches) == 1:
        return matches[0][1]
    if not matches:
        raise ValueError(f"Sinal {requested!r} não encontrado no VCD")
    paths = ", ".join(path for path, _ in matches)
    raise ValueError(
        f"O nome {requested!r} é ambíguo; informe o caminho completo: {paths}"
    )


def iter_vcd_events(stream: TextIO) -> Iterator[tuple[int, dict[str, str]]]:
    """Agrupa todas as mudanças ocorridas no mesmo instante."""

    time: int | None = None
    changes: dict[str, str] = {}
    for raw_line in stream:
        line = raw_line.strip()
        if not line or line.startswith("$"):
            continue
        if line.startswith("#"):
            if time is not None:
                yield time, changes
            time = int(line[1:])
            changes = {}
        elif line[0] in "01xXzZ":
            changes[line[1:]] = line[0].lower()
        elif line[0] in "bBrR":
            value, symbol = line.split(maxsplit=1)
            changes[symbol] = value[1:].lower()
    if time is not None:
        yield time, changes


def extract_dac_samples(
    stream: TextIO,
    *,
    clock: str,
    valid: str,
    serial: str,
    latch: str,
    bits: int = 16,
    strict: bool = False,
    serial_window_ps: int = 1000,
) -> list[DACSample]:
    """Reconstrói palavras LSB-first e detecta sua transferência ao DAC.

    Se a saída serial não mudar junto com a descida do clock, a amostragem
    aguarda uma mudança por ``serial_window_ps``. Sem mudança nessa janela,
    conserva o valor que já estava na saída.
    """

    if bits <= 0:
        raise ValueError("A quantidade de bits deve ser positiva")
    if serial_window_ps < 0:
        raise ValueError("A janela do sinal serial não pode ser negativa")
    header = read_vcd_header(stream)
    clock_id = resolve_signal(header.symbols, clock)
    valid_id = resolve_signal(header.symbols, valid)
    serial_id = resolve_signal(header.symbols, serial)
    latch_id = resolve_signal(header.symbols, latch)
    watched = {clock_id, valid_id, serial_id, latch_id}
    state = {symbol: "x" for symbol in watched}
    receiving = False
    frame_bits: list[int] = []
    samples: list[DACSample] = []
    pending_serial: tuple[float, str] | None = None
    remaining_delay_cycles = 0

    def append_serial_bit(bit: str, timestamp: int) -> None:
        if bit not in ("0", "1"):
            raise ValueError(f"Bit serial indefinido ({bit}) no tempo {timestamp}")
        frame_bits.append(int(bit))

    for timestamp, changes in iter_vcd_events(stream):
        if pending_serial is not None and timestamp > pending_serial[0]:
            _, previous_serial = pending_serial
            append_serial_bit(previous_serial, timestamp)
            pending_serial = None

        previous = state.copy()
        for symbol, value in changes.items():
            if symbol in state:
                state[symbol] = value
        clock_fall = previous[clock_id] == "1" and state[clock_id] == "0"
        clock_rise = previous[clock_id] == "0" and state[clock_id] == "1"

        if not receiving and clock_fall and state[valid_id] == "1":
            receiving = True
            frame_bits = []
            remaining_delay_cycles = 2
        if receiving and clock_fall and remaining_delay_cycles > 0:
            remaining_delay_cycles -= 1
        elif receiving and clock_fall and len(frame_bits) < bits:
            if pending_serial is not None:
                _, previous_serial = pending_serial
                append_serial_bit(previous_serial, timestamp)
                pending_serial = None
            if serial_id in changes:
                append_serial_bit(state[serial_id], timestamp)
            else:
                window_ticks = serial_window_ps / header.timescale_ps
                pending_serial = (timestamp + window_ticks, state[serial_id])
        elif (
            receiving
            and pending_serial is not None
            and timestamp <= pending_serial[0]
            and serial_id in changes
        ):
            append_serial_bit(state[serial_id], timestamp)
            pending_serial = None
        if receiving and clock_rise and state[latch_id] == "1":
            if pending_serial is not None:
                _, previous_serial = pending_serial
                append_serial_bit(previous_serial, timestamp)
                pending_serial = None
            if len(frame_bits) != bits:
                raise ValueError(
                    f"Latch no tempo {timestamp} após {len(frame_bits)} bits; "
                    f"eram esperados {bits}"
                )
            value = sum(bit << index for index, bit in enumerate(frame_bits))
            time_ps = timestamp * header.timescale_ps
            if float(time_ps).is_integer():
                time_ps = int(time_ps)
            samples.append(DACSample(time_ps, value))
            receiving = False
            frame_bits = []

    if pending_serial is not None:
        _, previous_serial = pending_serial
        append_serial_bit(previous_serial, 0)
    if receiving and strict:
        raise ValueError(
            f"Fim do arquivo durante uma transmissão ({len(frame_bits)}/{bits} bits)"
        )
    return samples


def ajustar_output(output: int) -> float:
    """Converte a palavra de 16 bits para a faixa de -5 V a +5 V."""

    return 5 * output / 2**15 - 5


def ajustar_output_corrente(output: int) -> float:
    """Aplica a conversão do DAC usada para corrente no script original."""

    return ajustar_output(output) / 1000


def resolver_vcd(source: Path) -> Path:
    """Aceita um VCD ou extrai do TCL o caminho passado ao comando open_vcd."""

    source = source.expanduser().resolve()
    if source.suffix.lower() == ".vcd":
        if not source.is_file():
            raise FileNotFoundError(f"Arquivo VCD não encontrado: {source}")
        return source
    if source.suffix.lower() != ".tcl":
        raise ValueError("A entrada deve ser um arquivo .vcd ou .tcl")

    content = source.read_text(encoding="utf-8-sig")
    match = re.search(
        r"(?im)^\s*open_vcd\s+(?:\{([^}]+)\}|\"([^\"]+)\"|(\S+))", content
    )
    if not match:
        raise ValueError(f"Nenhum comando open_vcd encontrado em {source}")

    raw_path = next(group for group in match.groups() if group is not None)
    vcd_path = Path(raw_path).expanduser()
    if not vcd_path.is_absolute():
        vcd_path = source.parent / vcd_path
    vcd_path = vcd_path.resolve()
    if not vcd_path.is_file():
        raise FileNotFoundError(
            f"O TCL {source} aponta para um VCD inexistente: {vcd_path}"
        )
    return vcd_path


def ler_dac(
    vcd_path: Path,
    *,
    clock: str,
    valid: str,
    serial: str,
    latch: str,
    bits: int,
    strict: bool,
    corrente: bool,
    serial_window_ps: int,
) -> tuple[list[DACSample], list[float], list[float]]:
    """Reconstrói o DAC e devolve tempo em ms e valores já convertidos."""

    with vcd_path.open(encoding="utf-8") as stream:
        samples = extract_dac_samples(
            stream,
            clock=clock,
            valid=valid,
            serial=serial,
            latch=latch,
            bits=bits,
            strict=strict,
            serial_window_ps=serial_window_ps,
        )
    converter = ajustar_output_corrente if corrente else ajustar_output
    time_ms = [float(sample.time_ps) / 1e9 for sample in samples]
    values = [converter(sample.value) for sample in samples]
    return samples, time_ms, values


def ler_psim(path: Path, column: str) -> tuple[list[float], list[float]]:
    """Lê uma coluna do PSIM; a coluna Time é interpretada em segundos."""

    time_ms: list[float] = []
    values: list[float] = []
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames or []
        missing = [name for name in ("Time", column) if name not in columns]
        if missing:
            raise ValueError(
                f"Coluna(s) {', '.join(missing)} ausente(s) em {path}. "
                f"Disponíveis: {', '.join(columns)}"
            )
        for row in reader:
            time_ms.append(float(row["Time"]) * 1000)
            values.append(float(row[column]))
    return time_ms, values


def salvar_csv(
    path: Path,
    samples: list[DACSample],
    time_ms: list[float],
    adjusted: list[float],
) -> None:
    """Exporta o valor decimal bruto e o valor convertido usado no gráfico."""

    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("time_ms", "dac_decimal", "dac_adjusted"))
        for sample, timestamp, value in zip(samples, time_ms, adjusted):
            writer.writerow((timestamp, sample.value, value))


def plotar(
    dac_time: list[float],
    dac_values: list[float],
    psim_time: list[float],
    psim_values: list[float],
    *,
    psim_column: str,
    ylabel: str,
    title: str,
    save_image: Path | None,
) -> None:
    """Plota primeiro o PSIM e depois o DAC, deixando o DAC no topo."""

    _, axis = plt.subplots()
    axis.plot(psim_time, psim_values, linewidth=3, label=f"PSIM ({psim_column})")
    axis.plot(dac_time, dac_values, linewidth=1.5, label="DAC", zorder=3)
    axis.set_xlabel("Tempo (ms)")
    axis.set_ylabel(ylabel)
    axis.set_title(title)
    axis.grid(True)
    axis.legend()
    plt.tight_layout()
    if save_image is not None:
        plt.savefig(save_image, dpi=150)
        plt.close()
    else:
        plt.show()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python scripts/gerar_graficos.py",
        description=(
            "Reconstrói a saída serial do DAC a partir de um VCD e compara "
            "seus valores com uma coluna do PSIM."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""exemplos:
  Abrir o gráfico:
    python scripts/gerar_graficos.py vc/behavioral_vc.vcd --psim-column V1 --sinal VC1

  Escolher outro CSV do PSIM:
    python scripts/gerar_graficos.py simulacao.vcd --psim outro_psim.csv \\
      --psim-column V1 --sinal VC1

  Ler o caminho do VCD de um comando open_vcd dentro de um TCL:
    python scripts/gerar_graficos.py gerar_vcd.tcl --psim-column I2 \\
      --sinal IL1 --corrente

  Exportar também os dados decimais reconstruídos:
    python scripts/gerar_graficos.py simulacao.vcd --psim-column V1 \\
      --sinal VC1 --csv dac.csv

  Salvar o gráfico sem abrir uma janela:
    python scripts/gerar_graficos.py simulacao.vcd --psim-column V1 \\
      --sinal VC1 --save-image comparacao.png

  Usar nomes de sinais diferentes:
    python scripts/gerar_graficos.py outro.vcd --psim psim.csv --psim-column V1 \\
      --clock clk --valid outro_inicio --sinal VC1 \\
      --serial dac_out --latch dac_latch
""",
    )
    parser.add_argument(
        "source",
        type=Path,
        help="arquivo VCD ou TCL contendo open_vcd (obrigatório)",
    )
    parser.add_argument(
        "--psim",
        type=Path,
        default=Path("psim.csv"),
        help="CSV exportado pelo PSIM (padrão: psim.csv)",
    )
    parser.add_argument(
        "--psim-column",
        required=True,
        help="coluna do PSIM que será plotada (obrigatório)",
    )
    parser.add_argument("--clock", default="clock", help="nome/caminho do clock")
    parser.add_argument(
        "--valid",
        default="iniciar_envio",
        help="nome/caminho do sinal que inicia a transmissão (padrão: iniciar_envio)",
    )
    parser.add_argument("--serial", default="serial_DAC_out")
    parser.add_argument("--latch", default="latch_update")
    parser.add_argument("--bits", type=int, default=16)
    parser.add_argument(
        "--serial-window-ns",
        type=float,
        default=1.0,
        help="janela após a descida do clock para aguardar o serial (padrão: 1 ns)",
    )
    parser.add_argument(
        "--corrente",
        action="store_true",
        help="divide a saída convertida por 1000, como no script original",
    )
    parser.add_argument(
        "--sinal",
        default="SINAL",
        help="nome da grandeza exibido no gráfico (padrão: SINAL)",
    )
    parser.add_argument(
        "--ylabel",
        help="rótulo do eixo vertical (padrão: valor de --sinal)",
    )
    parser.add_argument(
        "--title",
        help='título do gráfico (padrão: "<sinal> ao longo do tempo")',
    )
    parser.add_argument(
        "--csv",
        type=Path,
        metavar="ARQUIVO",
        help="também exporta os valores do DAC em CSV",
    )
    parser.add_argument(
        "--save-image",
        type=Path,
        metavar="IMAGEM",
        help="salva a imagem em vez de abrir a janela do gráfico",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="gera erro se o VCD terminar no meio de uma transmissão",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    vcd_path = resolver_vcd(args.source)
    ylabel = args.ylabel if args.ylabel is not None else args.sinal
    title = (
        args.title
        if args.title is not None
        else f"{args.sinal} ao longo do tempo"
    )
    samples, dac_time, dac_values = ler_dac(
        vcd_path,
        clock=args.clock,
        valid=args.valid,
        serial=args.serial,
        latch=args.latch,
        bits=args.bits,
        strict=args.strict,
        corrente=args.corrente,
        serial_window_ps=int(args.serial_window_ns * 1000),
    )
    psim_time, psim_values = ler_psim(args.psim, args.psim_column)

    if args.csv is not None:
        salvar_csv(args.csv, samples, dac_time, dac_values)
        print(f"{len(samples)} amostras do DAC gravadas em {args.csv}")

    plotar(
        dac_time,
        dac_values,
        psim_time,
        psim_values,
        psim_column=args.psim_column,
        ylabel=ylabel,
        title=title,
        save_image=args.save_image,
    )
    if args.save_image is not None:
        print(f"Gráfico gravado em {args.save_image}")


if __name__ == "__main__":
    main()
