library IEEE;
use IEEE.STD_LOGIC_1164.ALL;

entity demultiplexer_xadc is
    Port (
        clk     : in  std_logic;
        reset   : in  std_logic;
        valid   : in  std_logic;

        data_in : in  std_logic_vector(11 downto 0);
        channel : in  std_logic_vector(4 downto 0);

        out_vpvn  : out std_logic_vector(11 downto 0);
        out_vaux0 : out std_logic_vector(11 downto 0)
    );
end demultiplexer_xadc;

architecture Behavioral of demultiplexer_xadc is
begin

    process(clk)
    begin
        if rising_edge(clk) then

            if reset = '1' then
                out_vpvn  <= (others => '0');
                out_vaux0 <= (others => '0');

            elsif valid = '1' then

                case channel is

                    when "00011" =>      -- 0x03 = VP/VN
                        out_vpvn <= data_in;

                    when "10000" =>      -- 0x10 = VAUX0
                        out_vaux0 <= data_in;

                    when others =>
                        null;

                end case;

            end if;

        end if;
    end process;

end Behavioral;