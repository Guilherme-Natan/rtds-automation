library IEEE;
use IEEE.STD_LOGIC_1164.ALL;

entity clock_divider is
    generic (
        DIVISOR : positive := 100_000
    );
    Port (
        clk     : in  STD_LOGIC;
        clk_out : out STD_LOGIC
    );
end clock_divider;

architecture Behavioral of clock_divider is

    constant HALF_DIVISOR : positive := DIVISOR / 2;

    signal counter     : integer range 0 to HALF_DIVISOR - 1 := 0;
    signal clk_out_reg : STD_LOGIC := '0';

begin

    process(clk)
    begin
        if rising_edge(clk) then
            if counter = HALF_DIVISOR - 1 then
                counter     <= 0;
                clk_out_reg <= not clk_out_reg;
            else
                counter <= counter + 1;
            end if;
        end if;
    end process;

    clk_out <= clk_out_reg;

end Behavioral;