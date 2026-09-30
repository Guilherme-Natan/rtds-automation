library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

entity multiplexer_output_4 is
    Port (
        input_a0, input_a1, input_a2, input_a3 : in STD_LOGIC_VECTOR (15 downto 0);
        input_b0, input_b1, input_b2, input_b3 : in STD_LOGIC;
        sel                                      : in STD_LOGIC_VECTOR (1 downto 0);
        output_a                                 : out STD_LOGIC_VECTOR (15 downto 0);
        output_b                                 : out STD_LOGIC
    );
end multiplexer_output_4;

architecture Behavioral of multiplexer_output_4 is
    type data_array_t is array (0 to 3) of STD_LOGIC_VECTOR (15 downto 0);
    type valid_array_t is array (0 to 3) of STD_LOGIC;
    signal data_inputs  : data_array_t;
    signal valid_inputs : valid_array_t;
begin
    data_inputs(0) <= input_a0;
    data_inputs(1) <= input_a1;
    data_inputs(2) <= input_a2;
    data_inputs(3) <= input_a3;

    valid_inputs(0) <= input_b0;
    valid_inputs(1) <= input_b1;
    valid_inputs(2) <= input_b2;
    valid_inputs(3) <= input_b3;

    output_a <= data_inputs(to_integer(unsigned(sel)));
    output_b <= valid_inputs(to_integer(unsigned(sel)));
end Behavioral;
