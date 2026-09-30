################################################################
# Template de block design RTDS
# Placeholders substituidos por scripts/stages.py:
#   __DESIGN_NAME__ __HLS_IP_VLNV__ __IP_NAME__
#   __INPUT_NAMES__ __OUTPUT_NAMES__ __OUTPUT_TYPES__
#   __PULSE_DIVISOR__ __PULSE_FREQUENCY_LABEL__ __MUX_SIZE__
################################################################

set scripts_vivado_version 2022.2
set current_vivado_version [version -short]
if {[string first $scripts_vivado_version $current_vivado_version] == -1} {
    error "Template criado para Vivado $scripts_vivado_version; versao atual: $current_vivado_version"
}

set design_name {__DESIGN_NAME__}
set hls_ip_vlnv {__HLS_IP_VLNV__}
set hls_instance {__IP_NAME__}
set input_names [list __INPUT_NAMES__]
set output_names [list __OUTPUT_NAMES__]
set output_types [list __OUTPUT_TYPES__]
set pulse_divisor __PULSE_DIVISOR__
set pulse_frequency_label {__PULSE_FREQUENCY_LABEL__}
set mux_size __MUX_SIZE__

if {[llength $input_names] > 2} { error "Sao suportadas no maximo 2 entradas analogicas." }
if {[llength $output_names] < 1 || [llength $output_names] > 8} { error "Sao suportadas de 1 a 8 saidas." }
if {[llength $output_names] != [llength $output_types]} { error "Listas de saidas e tipos possuem tamanhos diferentes." }
if {$pulse_divisor < 1} { error "O divisor do pulse generator deve ser positivo." }
if {[llength [get_ipdefs -all $hls_ip_vlnv]] != 1} { error "IP HLS nao encontrado no catalogo: $hls_ip_vlnv" }

if {[get_files -quiet ${design_name}.bd] ne ""} { error "O block design '$design_name' ja existe." }
create_bd_design $design_name
current_bd_design $design_name

proc create_module {reference instance_name} {
    if {[can_resolve_reference $reference] == 0} { error "Modulo VHDL nao encontrado: $reference" }
    return [create_bd_cell -type module -reference $reference $instance_name]
}

# Portas externas principais.
set GCLK [create_bd_port -dir I -type clk -freq_hz 100000000 GCLK]
set latch_update [create_bd_port -dir O latch_update]
set saida_clock [create_bd_port -dir O -type clk saida_clock]
set serial_DAC_out [create_bd_port -dir O serial_DAC_out]

# Clock de 100 MHz da placa para 50 MHz.
set clock_50MHz [create_module clock_divider clock_50MHz]
set_property CONFIG.DIVISOR {2} $clock_50MHz
set power_on [create_module power_on power_on]

# Pulse generator: o nome informa a frequencia efetiva.
set pulse_name "pulse_generator_${pulse_frequency_label}MHz"
set pulse_generator [create_module pulse_generator $pulse_name]
set_property CONFIG.DIVISOR $pulse_divisor $pulse_generator

# DAC e IP gerado pelo Vitis HLS.
set dac [create_module dac dac]
set circuit_ip [create_bd_cell -type ip -vlnv $hls_ip_vlnv $hls_instance]

# Processing System configurado pelo preset da ZedBoard Avnet 1.4.
set processing_system7 [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 processing_system7]
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 -config {apply_board_preset "1" make_external "FIXED_IO, DDR" Master "Disable" Slave "Disable"} $processing_system7
set_property CONFIG.PCW_USE_M_AXI_GP0 {0} $processing_system7

# XADC embutido: uma entrada usa VP/VN; duas usam VP/VN e VAUX0.
set input_count [llength $input_names]
if {$input_count > 0} {
    set Vp_Vn [create_bd_intf_port -mode Slave -vlnv xilinx.com:interface:diff_analog_io_rtl:1.0 -portmaps {V_N {physical_name Vp_Vn_v_n direction I} V_P {physical_name Vp_Vn_v_p direction I}} Vp_Vn]
    set_property HDL_ATTRIBUTE.LOCKED {TRUE} $Vp_Vn
    set xadc_wiz [create_bd_cell -type ip -vlnv xilinx.com:ip:xadc_wiz:3.3 xadc_wiz]
    if {$input_count == 1} {
        set_property -dict [list CONFIG.ENABLE_RESET {true} CONFIG.INTERFACE_SELECTION {ENABLE_DRP} CONFIG.SINGLE_CHANNEL_ENABLE_CALIBRATION {true} CONFIG.SINGLE_CHANNEL_SELECTION {VP_VN}] $xadc_wiz
    } else {
        set_property -dict [list CONFIG.CHANNEL_ENABLE_VAUXP0_VAUXN0 {true} CONFIG.CHANNEL_ENABLE_VP_VN {true} CONFIG.ENABLE_RESET {true} CONFIG.EXTERNAL_MUX_CHANNEL {VP_VN} CONFIG.INTERFACE_SELECTION {ENABLE_DRP} CONFIG.SEQUENCER_MODE {Continuous} CONFIG.SINGLE_CHANNEL_ENABLE_CALIBRATION {true} CONFIG.SINGLE_CHANNEL_SELECTION {VP_VN} CONFIG.XADC_STARUP_SELECTION {channel_sequencer}] $xadc_wiz
    }
    set xadc_slice [create_bd_cell -type ip -vlnv xilinx.com:ip:xlslice:1.0 xadc_slice_16_to_12]
    set_property -dict [list CONFIG.DIN_FROM {15} CONFIG.DIN_TO {4} CONFIG.DIN_WIDTH {16}] $xadc_slice
    set constant_0_16bit [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 constant_0_16bit]
    set_property -dict [list CONFIG.CONST_VAL {0} CONFIG.CONST_WIDTH {16}] $constant_0_16bit
    set constant_0_1bit [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 constant_0_1bit]
    set_property -dict [list CONFIG.CONST_VAL {0} CONFIG.CONST_WIDTH {1}] $constant_0_1bit
    connect_bd_intf_net [get_bd_intf_ports Vp_Vn] [get_bd_intf_pins xadc_wiz/Vp_Vn]
    connect_bd_net [get_bd_ports GCLK] [get_bd_pins xadc_wiz/dclk_in]
    connect_bd_net [get_bd_pins power_on/reset] [get_bd_pins xadc_wiz/reset_in]
    connect_bd_net [get_bd_pins xadc_wiz/do_out] [get_bd_pins xadc_slice_16_to_12/Din]
    connect_bd_net [get_bd_pins xadc_wiz/eoc_out] [get_bd_pins xadc_wiz/den_in]
    connect_bd_net [get_bd_pins constant_0_16bit/dout] [get_bd_pins xadc_wiz/di_in]
    connect_bd_net [get_bd_pins constant_0_1bit/dout] [get_bd_pins xadc_wiz/dwe_in]

    if {$input_count == 1} {
        set constant_3_7bit [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 constant_3_7bit]
        set_property -dict [list CONFIG.CONST_VAL {3} CONFIG.CONST_WIDTH {7}] $constant_3_7bit
        connect_bd_net [get_bd_pins constant_3_7bit/dout] [get_bd_pins xadc_wiz/daddr_in]
        set input_map [create_module input_map input_map]
        connect_bd_net [get_bd_pins xadc_slice_16_to_12/Dout] [get_bd_pins input_map/x]
        connect_bd_net [get_bd_pins input_map/y] [get_bd_pins $hls_instance/[lindex $input_names 0]]
    } else {
        set Vaux0 [create_bd_intf_port -mode Slave -vlnv xilinx.com:interface:diff_analog_io_rtl:1.0 Vaux0]
        connect_bd_intf_net [get_bd_intf_ports Vaux0] [get_bd_intf_pins xadc_wiz/Vaux0]
        set xadc_demultiplexer [create_module demultiplexer_xadc xadc_demultiplexer]
        set channel_concat [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat:2.1 channel_concat]
        set_property -dict [list CONFIG.IN0_WIDTH {5} CONFIG.IN1_WIDTH {2}] $channel_concat
        set constant_0_2bit [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 constant_0_2bit]
        set_property -dict [list CONFIG.CONST_VAL {0} CONFIG.CONST_WIDTH {2}] $constant_0_2bit
        connect_bd_net [get_bd_ports GCLK] [get_bd_pins xadc_demultiplexer/clk]
        connect_bd_net [get_bd_pins power_on/reset] [get_bd_pins xadc_demultiplexer/reset]
        connect_bd_net [get_bd_pins xadc_wiz/channel_out] [get_bd_pins xadc_demultiplexer/channel] [get_bd_pins channel_concat/In0]
        connect_bd_net [get_bd_pins constant_0_2bit/dout] [get_bd_pins channel_concat/In1]
        connect_bd_net [get_bd_pins channel_concat/dout] [get_bd_pins xadc_wiz/daddr_in]
        connect_bd_net [get_bd_pins xadc_wiz/drdy_out] [get_bd_pins xadc_demultiplexer/valid]
        connect_bd_net [get_bd_pins xadc_slice_16_to_12/Dout] [get_bd_pins xadc_demultiplexer/data_in]
        set input_map_0 [create_module input_map "input_map_[lindex $input_names 0]"]
        set input_map_1 [create_module input_map "input_map_[lindex $input_names 1]"]
        connect_bd_net [get_bd_pins xadc_demultiplexer/out_vpvn] [get_bd_pins $input_map_0/x]
        connect_bd_net [get_bd_pins xadc_demultiplexer/out_vaux0] [get_bd_pins $input_map_1/x]
        connect_bd_net [get_bd_pins $input_map_0/y] [get_bd_pins $hls_instance/[lindex $input_names 0]]
        connect_bd_net [get_bd_pins $input_map_1/y] [get_bd_pins $hls_instance/[lindex $input_names 1]]
    }
}

# Uma cadeia registrador + mapeamento para cada estado de saida.
set mapped_output_pins {}
set valid_output_pins {}
for {set index 0} {$index < [llength $output_names]} {incr index} {
    set output_name [lindex $output_names $index]
    set output_type [lindex $output_types $index]
    set register_cell [create_module registrador_32bits "registrador_${output_name}"]
    set map_reference [expr {$output_type eq "V" ? "output_map" : "output_map_current"}]
    set map_cell [create_module $map_reference "${map_reference}_${output_name}"]
    connect_bd_net [get_bd_pins clock_50MHz/clk_out] [get_bd_pins $register_cell/clock]
    connect_bd_net [get_bd_pins $hls_instance/$output_name] [get_bd_pins $register_cell/entrada]
    connect_bd_net [get_bd_pins $hls_instance/${output_name}_ap_vld] [get_bd_pins $register_cell/enable]
    connect_bd_net [get_bd_pins $register_cell/saida] [get_bd_pins $map_cell/x]
    lappend mapped_output_pins [get_bd_pins $map_cell/y]
    lappend valid_output_pins [get_bd_pins $hls_instance/${output_name}_ap_vld]
}

# Seleciona as saidas para o DAC somente quando necessario.
set output_count [llength $output_names]
if {$output_count == 1} {
    connect_bd_net [lindex $mapped_output_pins 0] [get_bd_pins dac/entrada_sinal]
    connect_bd_net [lindex $valid_output_pins 0] [get_bd_pins dac/iniciar_envio]
} else {
    if {$output_count == 2} {
        set output_mux [create_module multiplexer_output_2 multiplexer_output_2]
        set select_width 1
    } else {
        set mux_reference "multiplexer_output_${mux_size}"
        set output_mux [create_module $mux_reference $mux_reference]
        set select_width [expr {$mux_size == 4 ? 2 : 3}]
    }

    # Os seletores sao expostos individualmente como as chaves fisicas da ZedBoard.
    if {$select_width == 1} {
        set SW0 [create_bd_port -dir I SW0]
        connect_bd_net $SW0 [get_bd_pins $output_mux/sel]
    } else {
        set selector_concat [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat:2.1 selector_concat]
        set_property CONFIG.NUM_PORTS $select_width $selector_concat
        for {set select_index 0} {$select_index < $select_width} {incr select_index} {
            set switch_name "SW${select_index}"
            set switch_port [create_bd_port -dir I $switch_name]
            set concat_pin [get_bd_pins [format {%s/In%d} $selector_concat $select_index]]
            connect_bd_net $switch_port $concat_pin
        }
        connect_bd_net [get_bd_pins $selector_concat/dout] [get_bd_pins $output_mux/sel]
    }
    connect_bd_net [get_bd_pins $output_mux/output_a] [get_bd_pins dac/entrada_sinal]
    connect_bd_net [get_bd_pins $output_mux/output_b] [get_bd_pins dac/iniciar_envio]
    for {set index 0} {$index < $mux_size} {incr index} {
        if {$index < $output_count} {
            connect_bd_net [lindex $mapped_output_pins $index] [get_bd_pins $output_mux/input_a${index}]
            connect_bd_net [lindex $valid_output_pins $index] [get_bd_pins $output_mux/input_b${index}]
        } else {
            if {[llength [get_bd_cells -quiet constant_0_16bit]] == 0} {
                set constant_0_16bit [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 constant_0_16bit]
                set_property -dict [list CONFIG.CONST_VAL {0} CONFIG.CONST_WIDTH {16}] $constant_0_16bit
            }
            if {[llength [get_bd_cells -quiet constant_0_1bit]] == 0} {
                set constant_0_1bit [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 constant_0_1bit]
                set_property -dict [list CONFIG.CONST_VAL {0} CONFIG.CONST_WIDTH {1}] $constant_0_1bit
            }
            connect_bd_net [get_bd_pins constant_0_16bit/dout] [get_bd_pins $output_mux/input_a${index}]
            connect_bd_net [get_bd_pins constant_0_1bit/dout] [get_bd_pins $output_mux/input_b${index}]
        }
    }
}

# Conexoes fixas de clock, reset, controle e DAC.
connect_bd_net [get_bd_ports GCLK] [get_bd_pins clock_50MHz/clk] [get_bd_pins power_on/clk]
connect_bd_net [get_bd_pins clock_50MHz/clk_out] [get_bd_pins dac/clock] [get_bd_pins $pulse_name/clk] [get_bd_pins $hls_instance/ap_clk]
connect_bd_net [get_bd_pins power_on/enable] [get_bd_pins $pulse_name/enable]
connect_bd_net [get_bd_pins power_on/reset] [get_bd_pins $hls_instance/ap_rst]
connect_bd_net [get_bd_pins $pulse_name/pulse_out] [get_bd_pins $hls_instance/ap_start]
connect_bd_net [get_bd_pins dac/latch_update] [get_bd_ports latch_update]
connect_bd_net [get_bd_pins dac/saida_clock] [get_bd_ports saida_clock]
connect_bd_net [get_bd_pins dac/serial_DAC_out] [get_bd_ports serial_DAC_out]

validate_bd_design
save_bd_design
puts "INFO: Block design '$design_name' criado com sucesso."
