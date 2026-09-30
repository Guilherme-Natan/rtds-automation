set_property PACKAGE_PIN Y11  [get_ports {serial_DAC_out}];  # "JA1"
set_property PACKAGE_PIN AA11 [get_ports {latch_update}];    # "JA2"
set_property PACKAGE_PIN Y10  [get_ports {saida_clock}];     # "JA3"

set_property PACKAGE_PIN F22 [get_ports {SW0}];  # "SW0"
set_property PACKAGE_PIN G22 [get_ports {SW1}];  # "SW1"
set_property PACKAGE_PIN H22 [get_ports {SW2}];  # "SW2"

set_property PACKAGE_PIN Y9 [get_ports {GCLK}]

create_clock -name GCLK -period 10.000 -waveform {0.000 5.000} [get_ports {GCLK}];

set_property IOSTANDARD LVCMOS18 [get_ports -of_objects [get_iobanks 35]];
set_property IOSTANDARD LVCMOS33 [get_ports -of_objects [get_iobanks 13]];