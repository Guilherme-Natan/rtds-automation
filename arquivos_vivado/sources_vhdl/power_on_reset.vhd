library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

entity power_on is
    port (
        clk       : in  std_logic;
        reset : out std_logic;
        enable : out std_logic
    );
end power_on;

architecture Behavioral of power_on is

    signal counter   : unsigned(6 downto 0) := (others => '0');
    signal reset_reg : std_logic := '1';

    attribute X_INTERFACE_INFO : string;
    attribute X_INTERFACE_PARAMETER : string;

    attribute X_INTERFACE_INFO of reset : signal is
        "xilinx.com:signal:reset:1.0 reset RST";

    attribute X_INTERFACE_PARAMETER of reset : signal is
        "POLARITY ACTIVE_HIGH";

begin

    process(clk)
    begin
        if rising_edge(clk) then

            if reset_reg = '1' then
                -- Contagem de 0 até 99: 100 ciclos de clock.
                if counter = to_unsigned(99, counter'length) then
                    reset_reg <= '0';
                else
                    counter <= counter + 1;
                end if;
            end if;

        end if;
    end process;

    reset <= reset_reg;
    enable <= not reset_reg;

end Behavioral;