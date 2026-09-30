# Template compartilhado pelas simulacoes behavioral, post-synthesis e post-implementation.
open_vcd {__VCD_PATH__}

# Clock externo de 100 MHz da ZedBoard.
add_force {/__SIM_TOP__/GCLK} {0 0ns} {1 5ns} -repeat_every 10ns

__SWITCH_FORCES__

# As entradas analogicas sao forcadas depois do XADC e antes do input_map.
__INPUT_FORCES__

set dac_signal_names {clock iniciar_envio serial_DAC_out latch_update}
foreach signal $dac_signal_names {
    set dac_signal_paths($signal) {}
}

foreach object [get_objects -r -filter {NAME =~ *dac*}] {
    if {[regexp {/(dac[^/]*)/(clock|iniciar_envio|serial_DAC_out|latch_update)$} $object match instance signal]} {
        lappend dac_signal_paths($signal) $object
    }
}

set dac_objects_to_log {}
foreach signal $dac_signal_names {
    set paths $dac_signal_paths($signal)
    if {[llength $paths] != 1} {
        error "Esperado um caminho direto dac*/$signal; encontrados [llength $paths]: $paths"
    }
    lappend dac_objects_to_log [lindex $paths 0]
}
log_vcd $dac_objects_to_log

# Avanca 100 us por vez: 50 etapas preservam os 5 ms de simulacao.
# A porcentagem so avanca depois de cada intervalo simulado.
set simulation_steps 50
set simulation_step_us 100
set progress_width 25
for {set step 0} {$step <= $simulation_steps} {incr step} {
    set percent [expr {100 * $step / $simulation_steps}]
    set filled [expr {$progress_width * $step / $simulation_steps}]
    set elapsed_ms [expr {$step * $simulation_step_us / 1000.0}]
    set total_ms [expr {$simulation_steps * $simulation_step_us / 1000.0}]
    puts -nonewline [format "\rSimulacao \[%s%s\] %3d%% | %.1f / %.1f ms" \
        [string repeat "#" $filled] \
        [string repeat "-" [expr {$progress_width - $filled}]] \
        $percent $elapsed_ms $total_ms]
    flush stdout
    if {$step < $simulation_steps} {
        run $simulation_step_us us
    } else {
        puts ""
    }
}
close_vcd
