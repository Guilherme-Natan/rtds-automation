-- Faz o mapeamento de -5 para 0000, e 5 para ffff, para uma entrada em ponto fixo de 32 bits,
-- 4 deles, incluindo o de sinal, antes da vírgula.
-- Para fazer isto:
-- Shifta a entrada 1342177280 para cima (+5 em ponto fixo)
-- Divide por 40960 (faz com que o valor máximo, +5, vá para 65535)
-- Tira os bits mais significativos (inúteis)
-- Se o valor for menor que -5, trava em 0. Maior que 5, trava em 65535 (fff). Entre os dois, coloca o valor calculado

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

entity output_map is
    Port ( x : in STD_LOGIC_VECTOR (31 downto 0);
           y : out STD_LOGIC_VECTOR (15 downto 0));
end output_map;

architecture Dataflow of output_map is

    constant X_LIMIT : integer := 1_342_177_280;
    constant DIVISOR : integer := 40_960; -- 2 * X_LIMIT / 65_536


    signal shifted_x: SIGNED (32 downto 0);
    signal mapped_y_untruncated: SIGNED (32 downto 0);
    signal mapped_y: SIGNED (15 downto 0);

    begin

        shifted_x <= resize(signed(x), 33) + to_signed(X_LIMIT, 33);
        mapped_y_untruncated <= shifted_x / to_signed(DIVISOR, 33);
        mapped_y <= mapped_y_untruncated(15 downto 0);

        y <= x"0000" when signed(x) <= to_signed(-X_LIMIT, 32) else
             x"FFFF" when signed(x) >= to_signed(X_LIMIT, 32) else
             std_logic_vector(mapped_y);
end Dataflow;
