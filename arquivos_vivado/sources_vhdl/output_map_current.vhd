library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

entity output_map_current is
    Port ( x : in STD_LOGIC_VECTOR (31 downto 0);
           y : out STD_LOGIC_VECTOR (15 downto 0));
end output_map_current;

architecture Dataflow of output_map_current is

    constant X_LIMIT : integer := 1_342_177;
    constant X_RANGE : integer := 2 * X_LIMIT;
    constant Y_RANGE : integer := 65_536;

    signal shifted_x              : SIGNED (32 downto 0);
    signal mapped_y_untruncated   : SIGNED (50 downto 0);
    signal mapped_y               : SIGNED (15 downto 0);

begin

    shifted_x <= resize(signed(x), 33) + to_signed(X_LIMIT, 33);
    mapped_y_untruncated <= (shifted_x * to_signed(Y_RANGE, 18)) / to_signed(X_RANGE, 51);
    mapped_y <= mapped_y_untruncated(15 downto 0);

    y <= x"0000" when signed(x) <= to_signed(-X_LIMIT, 32) else
         x"FFFF" when signed(x) >= to_signed( X_LIMIT, 32) else
         std_logic_vector(mapped_y);

end Dataflow;
