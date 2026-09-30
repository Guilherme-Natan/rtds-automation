library IEEE;
use IEEE.STD_LOGIC_1164.ALL;

entity registrador_32bits is
    Port (
        clock  : in  STD_LOGIC;
        enable : in  STD_LOGIC;
        entrada : in  STD_LOGIC_VECTOR(31 downto 0);
        saida   : out STD_LOGIC_VECTOR(31 downto 0)
    );
end registrador_32bits;

architecture Behavioral of registrador_32bits is

    signal registro : STD_LOGIC_VECTOR(31 downto 0) := (others => '0');

begin

    process(clock)
    begin
        if falling_edge(clock) then
            if enable = '1' then
                registro <= entrada;
            end if;
        end if;
    end process;

    saida <= registro;

end Behavioral;