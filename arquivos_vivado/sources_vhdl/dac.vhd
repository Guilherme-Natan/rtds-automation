library ieee;
use ieee.std_logic_1164.all;

entity dac is
    port (
        clock          : in  std_logic;
        entrada_sinal  : in  std_logic_vector(15 downto 0);
        iniciar_envio  : in  std_logic;
        serial_DAC_out : out std_logic;
        latch_update   : out std_logic;
        saida_clock    : out std_logic
    );
end entity;

architecture behavioral of dac is

    type estado_t is (OCIOSO, ESPERA, ENVIANDO, LATCH);
    signal estado : estado_t := OCIOSO;

    signal palavra  : std_logic_vector(15 downto 0) := x"0000";
    signal contador : natural range 0 to 15 := 0;
    signal serial   : std_logic := '0';

begin

    serial_DAC_out <= serial;
    saida_clock    <= clock when estado = ENVIANDO else '0';
    latch_update   <= '1' when estado = LATCH else '0';

    process(clock)
    begin
        if falling_edge(clock) then
            case estado is

                when OCIOSO =>
                    serial <= '0';

                    if iniciar_envio = '1' then
                        contador <= 0;
                        estado   <= ESPERA;
                    end if;

                -- Espera 2 ciclos, para dar tempo dos output_map estabilizarem
                when ESPERA =>
                    serial <= '0';

                    if contador < 1 then
                        contador <= contador + 1;
                    else
                        palavra  <= entrada_sinal;
                        serial   <= entrada_sinal(0);
                        contador <= 0;
                        estado   <= ENVIANDO;
                    end if;

                when ENVIANDO =>
                    if contador < 15 then
                        contador <= contador + 1;
                        serial   <= palavra(contador + 1);
                    else
                        serial <= '0';
                        estado <= LATCH;
                    end if;

                when LATCH =>
                    estado <= OCIOSO;

            end case;
        end if;
    end process;

end architecture;