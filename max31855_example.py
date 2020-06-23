# To use this example, connect the MAX31855 CS to pin 3

import time

from mcp2210 import Mcp2210,  Mcp2210GpioDesignation

mcp = Mcp2210(serial_number="0000992816")
mcp.configure_spi_timing(chip_select_to_data_delay=0,
                         last_data_byte_to_cs=0,
                         delay_between_bytes=0)
mcp.set_spi_mode(0)
mcp.set_gpio_designation(3, Mcp2210GpioDesignation.CHIP_SELECT)

while 1:
    response = mcp.spi_exchange(b'\x00' * 4, cs_pin_number=3)
    print("##############################")
    print("received:", ' '.join("{:02X}".format(x) for x in response))

    response_merged = (response[0] << 24) | (response[1] << 16) | (response[2] << 8) | response[3]

    thermocouple_temp_raw = (response_merged & 0xFFFC0000) >> 18
    if thermocouple_temp_raw & (1 << 13):
        thermocouple_temp = ((thermocouple_temp_raw & 0x1FFF) ^ 0x1FFF) * -0.25
    else:
        thermocouple_temp = thermocouple_temp_raw * 0.25

    internal_temp_raw = (response_merged >> 4) & 0xFFF

    if internal_temp_raw & (1 << 11):
        internal_temp = ((internal_temp_raw) ^ 0x7FF) * -0.0625
    else:
        internal_temp = internal_temp_raw * 0.0625

    print()

    print("fault:", (response_merged & (1 << 16)) != 0)
    print("open circuit:", (response_merged & (1 << 0)) != 0)
    print("short to GND:", (response_merged & (1 << 1)) != 0)
    print("short to VCC:", (response_merged & (1 << 2)) != 0)

    print()

    print("thermocouple temp:", thermocouple_temp)
    print("internal temp:", internal_temp)

    print("\n")

    time.sleep(1)
