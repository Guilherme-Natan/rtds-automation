# Automação RTDS

Automação em Python para transformar netlists de circuitos elétricos em hardware para a **ZedBoard**, executar simulações no Vivado, comparar os resultados com o PSIM e copiar a imagem de boot para um cartão SD.

O fluxo utiliza `rtds-circuit-analysis` para gerar C++, Vitis HLS para criar o IP, Vivado para integrar e implementar o hardware e Vitis para preparar o boot. Os métodos disponíveis são **forward**, **backward** e **trapezoidal**.

## Conteúdo do repositório

```text
rtds-automation/
├── generate.py                 # Geração completa do hardware e do boot
├── simulate.py                 # Simulações e comparação com o PSIM
├── deploy.py                   # Cópia de BOOT.bin para cartão SD
├── scripts/
│   ├── cli.py                  # Menus interativos
│   ├── common.py               # Configuração e utilitários compartilhados
│   ├── stages.py               # Etapas de geração
│   └── gerar_graficos.py       # Conversão do VCD e gráficos de comparação
├── templates/
│   ├── circuit_block_design.template.tcl
│   └── simulation.template.tcl
├── arquivos_vivado/
│   ├── sources_vhdl/           # Módulos de clock, XADC, mapeamento, DAC e seleção
│   └── constraints/            # Restrições de pinos da ZedBoard
├── .env.example
├── .gitignore
├── requirements.txt
└── LICENSE
```

Os lançadores `.cmd` e os lançadores sem extensão não são distribuídos. Execute os programas com **`python <script>.py`**. Caches, logs, temporários, netlists pessoais e resultados gerados também não fazem parte do pacote.

## Requisitos

- **Python 3.13 ou superior**, exigido pela versão 0.3.2 de `rtds-circuit-analysis`.
- Dependências de `requirements.txt`: `rtds-circuit-analysis`, `matplotlib` e a dependência condicional dos menus `curses`.
- **Vivado 2022.2**, Vitis HLS e Vitis da mesma versão, com suporte ao dispositivo `xc7z020clg484-1`. O template de block design verifica a versão 2022.2 e interrompe o fluxo se ela não corresponder.
- Comandos das ferramentas disponíveis no `PATH`: `vivado`, `vitis_hls`, `vitis`, `xsct` e `bootgen`, além de `rtds-circuit-analysis` e `rtds-vitis`, instalados pelo pacote Python.
- Acesso à internet na primeira preparação para baixar os arquivos da **ZedBoard Avnet 1.4** do Xilinx Board Store. Eles são armazenados em `RTDS_ROOT`; instalações completas são reutilizadas.
- Netlist do circuito e, para comparação das simulações, um CSV exportado pelo PSIM. O programa não executa o PSIM nem exporta esse CSV automaticamente.
- Para implantação: cartão SD/SDHC removível, montado, formatado em **FAT32** e com capacidade detectada de até **32 GiB**.

O fluxo suporta até **duas entradas analógicas** e de **uma a oito saídas** no IP. Saídas cujo nome começa com `V` usam mapeamento de tensão; nomes começando com `I` usam mapeamento de corrente.

## Instalação e configuração

Clone o repositório e abra um terminal na pasta clonada:

```text
git clone https://github.com/Guilherme-Natan/rtds-automation.git
cd rtds-automation
python -m pip install -r requirements.txt
```

Copie `.env.example` para um arquivo chamado **`.env` na raiz do repositório**, ao lado dos scripts principais. Edite os valores de acordo com suas pastas:

```dotenv
RTDS_ROOT=/caminho/absoluto/rtds-gerados
CIRCUIT_DIRS=/caminho/absoluto/circuitos;/outro/caminho/circuitos
TEST_DIRS=/caminho/absoluto/testes
```

| Variável | Utilização |
| --- | --- |
| `RTDS_ROOT` | Destino dos projetos C++, HLS, Vivado e Vitis, organizados por circuito e método. |
| `CIRCUIT_DIRS` | Uma ou mais pastas pesquisadas recursivamente nos menus de circuitos e de imagens de boot de circuitos. |
| `TEST_DIRS` | Uma ou mais pastas pesquisadas recursivamente por `BOOT.bin` quando a origem escolhida no menu de implantação é **Teste**. |

Use caminhos absolutos. Separe múltiplas pastas por **ponto e vírgula**; as pastas de entrada configuradas devem existir. `RTDS_ROOT` deve apontar para uma pasta em que você possa gravar os arquivos gerados. O `.env` não é publicado e precisa ser criado localmente. As variáveis são lidas desse arquivo, sem necessidade de carregá-lo no terminal.

## Preparação do circuito

Os menus procuram arquivos `.cir` e `.sp` em `CIRCUIT_DIRS`. Na geração por argumentos, também são aceitas as extensões `.spi`, `.spice`, `.ckt` e `.net`.

Para manter os arquivos organizados, recomenda-se criar uma subpasta para cada circuito e usar o mesmo nome na pasta e no netlist: `<circuito>/<circuito>.cir`, dentro de uma das pastas configuradas em `CIRCUIT_DIRS`. Por exemplo:

```text
circuitos/
├── rlc_series/
│   └── rlc_series.cir
└── rc_series/
    └── rc_series.cir
```

Essa organização mantém os CSVs de referência do PSIM, as imagens de boot e as comparações de cada circuito em sua própria pasta. É uma recomendação de organização; os menus também encontram netlists em outras estruturas, pois a busca é recursiva.

Defina no netlist o timestep com uma linha como:

```text
.STEP 20n
```

O valor aceita segundos ou notação SPICE, como `20n`, `1u` e `1e-6`. O timestep precisa ser positivo e satisfazer **50.000.000 × Ts = inteiro positivo**: o período mínimo é 20 ns, e os demais devem ser múltiplos dele. A geração permite informar `--timestep` para substituir ou suprir o valor do netlist; a simulação exige `.STEP` no próprio arquivo.

Os nomes das saídas nos exemplos, como `VC1` e `IL1`, devem ser substituídos pelos nomes reais do seu circuito.

## Modo interativo

Execute sem argumentos para abrir os menus:

```text
python generate.py
python simulate.py
python deploy.py
```

Use **setas** para mover a seleção, **Espaço** para marcar ou desmarcar itens em escolhas múltiplas e **Enter** para confirmar. **Ctrl+C** ou **Esc** cancela. Na simulação, o programa pode preparar o projeto antes de mostrar as saídas disponíveis.

## Gerar hardware e boot

```text
python generate.py --help
python generate.py /caminho/circuito.cir --forward --timestep 20n --ip-clock 20
python generate.py /caminho/circuito.cir --forward --backward
python generate.py /caminho/circuito.cir --methods forward trapezoidal
python generate.py /caminho/circuito.cir --all
```

Escolha pelo menos um método com os flags individuais, `--methods` ou `--all`. Não combine essas formas de seleção.

| Opção | Comportamento |
| --- | --- |
| `--forward`, `--backward`, `--trapezoidal` | Executa os métodos selecionados; os flags individuais podem ser combinados. |
| `--methods <métodos...>` | Seleciona explicitamente uma lista de métodos. |
| `--all` | Executa os três métodos. |
| `--timestep <valor>` | Timestep em segundos ou notação SPICE; sem a opção, utiliza `.STEP` do netlist. |
| `--ip-clock <ns>` | Período solicitado para o clock do IP HLS; padrão: **20 ns**. Não é uma frequência em MHz. |
| `--hard-reset` | Reexecuta a geração a partir do C++, substituindo artefatos das etapas. Também pode ser usado sozinho para abrir os menus. |

### Etapas do fluxo

1. Preparação dos arquivos da ZedBoard e verificação das ferramentas.
2. Geração do código C++ com `rtds-vitis`.
3. Síntese e exportação do IP em VHDL com Vitis HLS.
4. Criação do projeto Vivado com fontes e constraints.
5. Criação do block design, integração do IP, XADC e DAC.
6. Síntese e verificação de timing.
7. Implementação e verificação de timing.
8. Geração de bitstream e exportação do hardware em XSA.
9. Criação da plataforma Vitis e geração do FSBL.
10. Geração da imagem `BOOT.bin`.
11. Cópia da imagem para um cartão SD compatível, se disponível.

O fluxo interrompe a geração quando o período implementado do IP excede o solicitado ou quando o slack de síntese/implementação é negativo. Sem `--hard-reset`, retoma da primeira etapa cujos artefatos estejam incompletos. Essa retomada verifica artefatos e não detecta automaticamente toda alteração em fontes, netlist, timestep ou clock: use `--hard-reset` após modificar esses elementos.

Ao gerar múltiplos métodos com um cartão conectado, cada método copia sua própria imagem: **o último método executado deixa seu `BOOT.bin` no cartão**. Sem cartão compatível, o programa informa a ausência e mantém as imagens geradas para implantação posterior.

## Simular e comparar com o PSIM

### CSV de referência

Coloque o CSV do PSIM em uma pasta `simulacoes/` ao lado do netlist:

```text
pasta-do-circuito/
├── circuito.cir
└── simulacoes/
    └── psim_5.csv
```

O nome deve ser `psim_<amplitude>.csv`, por exemplo `psim_1.csv`, `psim_2.5.csv` ou `psim_5.csv`. Para amplitude 5, `psim.csv` também é aceito, mas `psim_5.csv` tem preferência. A pasta legada `simulacao/` é aceita com aviso.

O CSV deve usar **vírgulas** como separador, **ponto** decimal, uma coluna **`Time` em segundos** e colunas com nomes idênticos às saídas selecionadas, respeitando maiúsculas e minúsculas:

```csv
Time,VC1,IL1
0.000000,0.0,0.0
0.000020,0.1,0.0001
```

Gere a referência PSIM para o mesmo circuito, estímulo e amplitude usados na simulação.

### Execução

```text
python simulate.py --help
python simulate.py /caminho/circuito.cir --forward behavioral VC1 --csv
python simulate.py /caminho/circuito.cir --all behavioral synthesis implementation VC1 IL1
python simulate.py /caminho/circuito.cir --trapezoidal implementation-timing VC1 --serial-window 1 --amplitude 1 --csv
```

A sintaxe é `python simulate.py <netlist> <método...> <tipo...> [saídas...] [opções]`. Se as saídas forem omitidas, o programa lista as disponíveis e solicita os nomes no terminal.

| Tipo | Simulação Vivado | Preparação necessária |
| --- | --- | --- |
| `behavioral` | Comportamental | Até o block design, etapa 5. |
| `synthesis` | Pós-síntese funcional | Até a síntese, etapa 6. |
| `synthesis-timing` | Pós-síntese com timing | Até a síntese, etapa 6. |
| `implementation` | Pós-implementação funcional | Até a implementação, etapa 7. |
| `implementation-timing` | Pós-implementação com timing | Até a implementação, etapa 7. |

É possível selecionar vários métodos, tipos e saídas na mesma execução. Os cinco tipos usam **`templates/simulation.template.tcl`**; o comando que inicia cada modo é definido por `simulate.py`.

| Opção | Comportamento |
| --- | --- |
| `--forward`, `--backward`, `--trapezoidal` | Seleciona os métodos; não combine com `--all`. |
| `--all` | Seleciona os três métodos. |
| `--amplitude <V>` | Pico da onda quadrada entre **0 e 5 V**; padrão: **5 V**. |
| `--serial-window <ns>` | Janela após a descida do clock para leitura do sinal serial; padrão: **1 ns**, valor não negativo. |
| `--csv` | Salva os valores reconstruídos do DAC em CSV, além do gráfico. |
| `--soft-reset` | Refaz os VCDs e gráficos, aproveitando os artefatos de geração disponíveis. |
| `--hard-reset` | Refaz a preparação do projeto e as simulações. Não pode ser combinado com `--soft-reset`. |

`python simulate.py --soft-reset` e `python simulate.py --hard-reset` também abrem a configuração interativa.

Cada execução simula **5 ms**, com uma barra atualizada a cada **0,1 ms**, após compilação e elaboração. As entradas são forçadas depois do XADC e antes de `input_map`: amplitude 5 usa os códigos de 12 bits `000`/`FFF`; amplitude 1 usa `666`/`999`. O estímulo tem período de 1 ms; com duas entradas, a segunda alterna nos instantes de 250 e 750 µs.

VCDs concluídos são reutilizados quando os artefatos de preparação permitem e a amplitude coincide; o gráfico é refeito. Alterações na janela serial são aplicadas durante a conversão do VCD. Use `--soft-reset` para forçar nova captura e `--hard-reset` quando mudar o circuito ou os fontes de hardware.

Para saídas começando com `I`, o conversor aplica automaticamente a escala de corrente, dividindo o valor reconstruído por 1000.

## Arquivos produzidos

| Local | Conteúdo |
| --- | --- |
| `<RTDS_ROOT>/<circuito>/<método>/codigos_cpp/` | C++ gerado. |
| `<RTDS_ROOT>/<circuito>/<método>/vitis_hls/` | Projeto HLS e IP exportado. |
| `<RTDS_ROOT>/<circuito>/<método>/vivado/` | Projeto Vivado, relatórios, bitstream e XSA. |
| `<RTDS_ROOT>/<circuito>/<método>/vitis/` | Plataforma Vitis e FSBL. |
| `<RTDS_ROOT>/<circuito>/<método>/simulation_tcl/<saída>/` | TCL gerado para cada tipo de simulação. |
| `<pasta-do-netlist>/arquivos_boot/<método>/BOOT.bin` | Imagem de boot. |
| `<pasta-do-netlist>/arquivos_boot/<circuito>_resumo.txt` | Resumo de timing, conexões e seleção de saídas. |
| `<pasta-do-netlist>/comparacoes/<método>/<saída>/` | `<tipo>.vcd`, marcador `<tipo>.vcd.complete`, `<tipo>.png` e CSV opcional. |

O nome do circuito é o nome do netlist sem a extensão. Use nomes distintos para circuitos diferentes que compartilhem o mesmo `RTDS_ROOT`.

## Gerar gráficos a partir de um VCD existente

O conversor pode ser executado separadamente, sem iniciar Vivado:

```text
python scripts/gerar_graficos.py --help
python scripts/gerar_graficos.py /caminho/behavioral.vcd --psim /caminho/psim_5.csv --psim-column VC1 --sinal VC1 --save-image /caminho/comparacao.png --csv /caminho/dac.csv
```

`--psim-column` é obrigatório. Sem `--psim`, procura `psim.csv` na pasta de execução. Sem `--save-image`, abre a janela do gráfico. Também aceita um TCL contendo `open_vcd` como entrada, opções para os nomes dos sinais (`--clock`, `--valid`, `--serial`, `--latch`), `--bits`, `--serial-window-ns`, `--corrente`, `--title`, `--ylabel` e `--strict`. A opção `--strict` trata uma transmissão incompleta ao final do VCD como erro.

## Copiar o boot para o cartão SD

```text
python deploy.py --help
python deploy.py
python deploy.py --boot-bin /caminho/arquivos_boot/forward/BOOT.bin
```

O programa detecta cartões removíveis montados com FAT32 e até 32 GiB. Se houver mais de um, apresenta um menu; com apenas um, utiliza esse cartão diretamente. No modo interativo, escolha **Circuito** para imagens em `CIRCUIT_DIRS` ou **Teste** para imagens em `TEST_DIRS`. `--boot-bin` permite informar diretamente a imagem, sem selecionar a origem nos menus.

A operação **copia e substitui `BOOT.bin` na raiz do cartão**. Ela não formata o cartão. Se nenhum cartão compatível for detectado, informa a ausência e termina sem copiar. Após a cópia, ejete o cartão pelo sistema e configure a ZedBoard para inicialização por SD.

## Problemas comuns

| Mensagem ou situação | Como resolver |
| --- | --- |
| `.env` ausente ou variável não definida | Crie `.env` ao lado dos scripts e preencha a variável indicada. |
| Nenhum circuito encontrado | Verifique `CIRCUIT_DIRS`, a existência das pastas e as extensões `.cir`/`.sp`. |
| Ferramenta não encontrada | Confira a instalação e o `PATH`, incluindo os executáveis instalados pelo Python. |
| Versão do Vivado incompatível | Utilize Vivado 2022.2, exigido pelo template. |
| Falha ao instalar arquivos da ZedBoard | Confira a conexão com o Xilinx Board Store e permissão de escrita em `RTDS_ROOT`. |
| Timestep inválido | Defina `.STEP` e utilize um múltiplo positivo de 20 ns. |
| Timing não atendido | Revise os relatórios de HLS/Vivado e o período solicitado para o IP antes de tentar novamente. |
| CSV do PSIM ou coluna ausente | Confira o nome por amplitude, a pasta `simulacoes/` e as colunas `Time` e da saída selecionada. |
| Saída inválida | Utilize os nomes listados pelo programa e presentes nos metadados do IP. |
| Resultado antigo após editar o circuito | Reexecute com `--hard-reset`; a retomada se baseia na presença dos artefatos. |
| Nenhum cartão compatível | Confira se ele está montado, é removível, usa FAT32 e está dentro do limite de capacidade. |

## Licença

Este projeto é distribuído sob a [licença MIT](LICENSE). Copyright © 2026 Guilherme Natan. As ferramentas e dependências externas mantêm suas próprias licenças.
