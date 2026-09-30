library IEEE;
use IEEE.STD_LOGIC_1164.ALL;

entity pulse_generator is
    generic (
        DIVISOR : positive := 2
    );
    Port (
        clk       : in  STD_LOGIC;
        enable    : in  STD_LOGIC;
        pulse_out : out STD_LOGIC
    );
end pulse_generator;

architecture Behavioral of pulse_generator is

    signal counter : integer range 0 to DIVISOR - 1 := 0;

begin

    process(clk)
    begin
        if rising_edge(clk) and enable = '1' then
            if counter = DIVISOR - 1 then
                counter <= 0;
            else
                counter <= counter + 1;
            end if;
        end if;
    end process;

    pulse_out <= '1' when counter = DIVISOR - 1 else '0';

end Behavioral;
