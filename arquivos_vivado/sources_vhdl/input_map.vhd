-- Faz o mapeamento de 000 para -5, e FFF para +5, para uma entrada de 12 bits, e saída de 32 bits em ponto fixo,
-- sendo 4 bits antes da virgula (incluindo o de sinal).
-- Para fazer isto:
-- Shifta a entrada 2048 para cima (podendo acontecer overflow; isso basicamente troca o sinal do bit mais significativo)
-- Multiplica por 5/8 (fazendo com que vá de -5 até 5, ao invés de -8 até 8).
-- Concatena o valor final com 0000, deixando-o com 32 bits

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

entity input_map is
    Port ( x : in STD_LOGIC_VECTOR (11 downto 0);
           y : out STD_LOGIC_VECTOR (31 downto 0));
end input_map;

architecture Dataflow of input_map is

    constant X_LIMIT : integer := 2_048;

    signal shifted_x: UNSIGNED (11 downto 0);
    signal mapped_y: SIGNED (15 downto 0);

    begin

        shifted_x <= unsigned(x) - to_unsigned(X_LIMIT, 12);
        mapped_y <= signed(shifted_x) * to_signed(5, 4) / 8;
        y(31 downto 20) <= std_logic_vector(mapped_y(11 downto 0));
        y(19 downto 0) <= x"00000";

end Dataflow;