library IEEE;
use IEEE.STD_LOGIC_1164.ALL;

entity multiplexer_output_2 is
    Port ( input_a0, input_a1: in STD_LOGIC_VECTOR (15 downto 0);
           output_a: out STD_LOGIC_VECTOR (15 downto 0);
           input_b0, input_b1 : in STD_LOGIC;
           output_b: out STD_LOGIC;
           sel : in STD_LOGIC);
end multiplexer_output_2;

architecture Behavioral of multiplexer_output_2 is

begin

    output_a <= input_a0 when sel = '0' else input_a1;
    output_b <= input_b0 when sel = '0' else input_b1;

end Behavioral;
