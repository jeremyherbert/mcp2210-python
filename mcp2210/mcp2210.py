import struct
import logging
import time
import math
import platform

from typing import List

import hid

from enum import IntEnum
from .validated_dataclass import ValidatedDataClass, check_in_closed_interval

# logger object for logging errors/debug information
logger = logging.getLogger()


def bytes_to_hex_string(data: bytes) -> str:
    """
    Converts a bytes object into a string of hex characters. For example, b"\\\\x00\\\\x01" becomes "00 01".

    :param data: bytes object
    :return: a hex string of the bytes
    """
    return ' '.join("{:02X}".format(x) for x in data)

def find_connected_mcp2210() -> list[str]:
    """
    Searches for connected MCP2210 devices and returns their serial numbers.

    Returns:
        list[str]: A list of serial numsbers of available MCP2210 devices.
    """
    connected_mcps: list[str] = []

    try:
        for hid_handler in hid.enumerate(vendor_id = 0x04d8, product_id = 0x00de):
            connected_mcps.append(hid_handler['serial_number'])
    except Exception as e:
        print(f"Error finding connected MCP2210 devices: {e}")
        return []

    return connected_mcps

class Mcp2210Commands(IntEnum):
    """
    Command codes for the MCP2210
    """
    GET_SPI_TRANSFER_SETTINGS = 0x41
    SET_SPI_TRANSFER_SETTINGS = 0x40

    GET_GPIO_SETTINGS = 0x20
    SET_GPIO_SETTINGS = 0x21

    GET_GPIO_PIN_DIRECTION = 0x33
    SET_GPIO_PIN_DIRECTION = 0x32

    GET_GPIO_PIN_VALUE = 0x31
    SET_GPIO_PIN_VALUE = 0x30

    TRANSFER_SPI_DATA = 0x42
    REQUEST_SPI_BUS_RELEASE = 0x80

    GET_STATUS = 0x10


class Mcp2210CommandResult(IntEnum):
    """
    Results codes for the MCP2210.
    """
    SUCCESS = 0x00
    SPI_DATA_NOT_ACCEPTED = 0xF7
    TRANSFER_IN_PROGRESS = 0xF8


class Mcp2210SpiTransferStatus(IntEnum):
    """
    Codes which indicate the current state of an SPI transfer.
    """
    SPI_TRANSFER_COMPLETE = 0x10
    SPI_TRANSFER_PENDING_NO_RECEIVED_DATA = 0x20
    SPI_TRANSFER_PENDING_RECEIVED_DATA_AVAILABLE = 0x30


class Mcp2210CommandFailedException(Exception):
    """
    Indicates that the device either reported a command failure, or returned some unexpected data.
    """
    pass


class Mcp2210CommandResponseDesyncException(Exception):
    """
    The MCP2210 returned a command response that didn't correspond to a request.
    """
    pass


class Mcp2210UsbBusyException(Exception):
    """
    A USB transaction is in progress, so the MCP2210 cannot execute the command.
    """
    pass


class Mcp2210SpiBusLockedException(Exception):
    """
    An external master is locking the SPI bus.
    """
    pass


class Mcp2210TransferConfiguration(ValidatedDataClass):
    """
    Holds and validates the SPI transaction parameters.
    """

    bit_rate: int = 1000000  # Hz
    idle_chip_select_value: int = 0  # bit mask
    active_chip_select_value: int = 0  # bit mask
    chip_select_to_data_delay: int = 0  # 100us per LSB
    last_data_byte_to_cs_delay: int = 0  # 100us per LSB
    delay_between_bytes: int = 0  # 100us per LSB
    transfer_size: int = 0  # transfer size in bytes
    mode: int = 0  # SPI mode (0-3)

    # this is a format string for the binary structure of the configuration
    _structure = "<IHHHHHHB"

    def _validate(self):
        """
        Validates the current SPI configuration.
        """
        check_in_closed_interval(self.bit_rate, 1.5e3, 12e6,
                                 "Clock rate must be between 1.5kHz and 12MHz")

        check_in_closed_interval(self.idle_chip_select_value, 0x0, 0xFFFF,
                                 "Idle chip select mask out of range")

        check_in_closed_interval(self.active_chip_select_value, 0x0, 0xFFFF,
                                 "Active chip select mask out of range")

        check_in_closed_interval(self.chip_select_to_data_delay, 0x0, 0xFFFF,
                                 "Chip select to data delay out of range")

        check_in_closed_interval(self.last_data_byte_to_cs_delay, 0x0, 0xFFFF,
                                 "Last data byte to chip select delay out of range")

        check_in_closed_interval(self.delay_between_bytes, 0x0, 0xFFFF,
                                 "Delay between bytes out of range")

        check_in_closed_interval(self.transfer_size, 0x0, 0xFFFF,
                                 "Transfer size out of range")

        check_in_closed_interval(self.mode, 0, 3, "SPI mode invalid")

    def pack(self) -> bytes:
        """
        Packs the configuration into the binary format understood by the device.

        :return: the packed binary data
        """
        return struct.pack(Mcp2210TransferConfiguration._structure,
                           self.bit_rate,
                           self.idle_chip_select_value,
                           self.active_chip_select_value,
                           self.chip_select_to_data_delay,
                           self.last_data_byte_to_cs_delay,
                           self.delay_between_bytes,
                           self.transfer_size,
                           self.mode)

    def unpack_from(self, data: bytes):
        """
        Unpacks the configuration from the binary format generated by the device.

        :data: the packed binary data
        """
        self.bit_rate, \
        self.idle_chip_select_value, \
        self.active_chip_select_value, \
        self.chip_select_to_data_delay, \
        self.last_data_byte_to_cs_delay, \
        self.delay_between_bytes, \
        self.transfer_size, \
        self.mode = struct.unpack(Mcp2210TransferConfiguration._structure, data)


class Mcp2210GpioDesignation(IntEnum):
    """
    The designations which can be applied to a pin.
    """
    GPIO = 0x00
    CHIP_SELECT = 0x01
    DEDICATED_FUNCTION = 0x02


class Mcp2210InterruptCountingMode(IntEnum):
    """
    MCP2210 interrupt counting modes. Currently unused and only present for compatibility.
    """
    COUNT_HIGH_PULSES = 0b100
    COUNT_LOW_PULSES = 0b011
    COUNT_RISING_EDGES = 0b010
    COUNT_FALLING_EDGES = 0b001
    NO_COUNTING = 0b000


class Mcp2210GpioDirection(IntEnum):
    """
    GPIO direction codes.
    """
    OUTPUT = 0
    INPUT = 1


class Mcp2210AccessControl(IntEnum):
    """
    MCP2210 password state. Currently unused and only present for compatibility.
    """
    NOT_PROTECTED = 0x00
    PASSWORD_PROTECTED = 0x40
    PERMANENTLY_LOCKED = 0x80


class Mcp2210GpioConfiguration(ValidatedDataClass):
    """
    Holds and validates the GPIO configuration parameters.
    """

    gpio_designations: List[Mcp2210GpioDesignation] = [Mcp2210GpioDesignation.GPIO] * 9  # one for each pin
    gpio_output_level: int = 0  # bitmask
    gpio_direction: int = 0  # bitmask

    # these three are not currently used
    remote_wakeup: bool = False
    interrupt_counting_mode: Mcp2210InterruptCountingMode = Mcp2210InterruptCountingMode.NO_COUNTING
    hold_bus_between_transfers: bool = False

    # This is not actually part of the structure in the datasheet, but it makes sense to store it together
    gpio_input_level: int = 0

    # this is a format string for the binary structure of the configuration
    _structure = "<BBBBBBBBBHHB"

    def _validate(self):
        """
        Validates the GPIO configuration.
        """
        assert type(self.gpio_designations) is list

        if len(self.gpio_designations) != 9:
            raise ValueError("Length of GPIO designations is invalid")
        for i in range(9):
            if self.gpio_designations[i] not in Mcp2210GpioDesignation.__members__.values():
                raise ValueError("GPIO designation {} is invalid".format(i))

        check_in_closed_interval(self.gpio_output_level, 0x0, 0xFFFF,
                                 "GPIO output level is invalid")

        check_in_closed_interval(self.gpio_input_level, 0x0, 0xFFFF,
                                 "GPIO input level is invalid")

        check_in_closed_interval(self.gpio_direction, 0x0, 0xFFFF,
                                 "GPIO direction configuration is invalid")

        if self.interrupt_counting_mode not in Mcp2210InterruptCountingMode.__members__.values():
            raise ValueError("Interrupt counting mode is invalid")

    def check_pin_number_is_gpio(self, pin_number: int):
        """
        Checks if the given pin number is configured as a GPIO. Raises an exception if it is not.

        :param pin_number: The number of the pin of interest
        """
        if not 0 <= pin_number <= 8:
            raise ValueError("Pin number must be between 0 and 8 inclusive")

        if self.gpio_designations[pin_number] != Mcp2210GpioDesignation.GPIO:
            raise ValueError("Pin is not designated as a GPIO")

    def set_gpio_direction_for_pin_number(self, pin_number: int, direction: Mcp2210GpioDirection):
        """
        Sets the direction for a given GPIO.

        :param pin_number: The number of the pin of interest
        :param direction: The direction to set
        """
        self.check_pin_number_is_gpio(pin_number)

        if direction not in Mcp2210GpioDirection.__members__.values():
            raise ValueError("Invalid GPIO direction")

        if direction:
            self.gpio_direction |= (1 << pin_number)
        else:
            self.gpio_direction &= ~(1 << pin_number)

    def get_gpio_direction_for_pin_number(self, pin_number: int) -> Mcp2210GpioDirection:
        """
        Returns the direction for a given GPIO.

        :param pin_number: The number of the pin of interest
        :return: The GPIO direction
        """
        self.check_pin_number_is_gpio(pin_number)
        return Mcp2210GpioDirection((self.gpio_direction & (1 << pin_number)) >> pin_number)

    def set_gpio_output_value_for_pin_number(self, pin_number: int, value: bool):
        """
        Sets a GPIO output value

        :param pin_number: The number of the pin of interest
        :param value: The value to set
        """
        self.check_pin_number_is_gpio(pin_number)

        if self.get_gpio_direction_for_pin_number(pin_number) == Mcp2210GpioDirection.INPUT:
            raise ValueError("GPIO is not an output")

        if value:
            self.gpio_output_level |= (1 << pin_number)
        else:
            self.gpio_output_level &= ~(1 << pin_number)

    def get_gpio_input_value_for_pin_number(self, pin_number: int) -> bool:
        """
        Returns the current state the given GPIO.

        :param pin_number: The number of the pin of interest
        :return: The pin state
        """
        self.check_pin_number_is_gpio(pin_number)

        if self.get_gpio_direction_for_pin_number(pin_number) == Mcp2210GpioDirection.OUTPUT:
            raise ValueError("GPIO is not an input")

        return (self.gpio_input_level & (1 << pin_number)) != 0

    def pack(self) -> bytes:
        """
        Packs the configuration into the binary format understood by the device.

        :return: the packed binary data
        """
        other_chip_settings = (self.remote_wakeup << 4) | \
                              (self.interrupt_counting_mode << 1) | \
                              self.hold_bus_between_transfers

        return struct.pack(Mcp2210GpioConfiguration._structure,
                           *self.gpio_designations,
                           self.gpio_output_level,
                           self.gpio_direction,
                           other_chip_settings)

    def unpack_from(self, data: bytes):
        """
        Unpacks the configuration from the binary format generated by the device.

        :param data: the packed binary data
        """
        unpacked = struct.unpack(Mcp2210GpioConfiguration._structure, data)

        self.gpio_designations = list(unpacked[:9])
        other_chip_settings = unpacked[11]

        self.remote_wakeup = (other_chip_settings & 0x10) != 0
        self.interrupt_counting_mode = (other_chip_settings & 0x0E) >> 1
        self.hold_bus_between_transfers = (other_chip_settings & 0x01) != 0


class Mcp2210(object):
    """
    This class is used to interface with the MCP2210.

    :param serial_number: The serial number of the device to connect to (a 10 digit string)
    :param vendor_id: The vendor ID of the device (defaults to 0x04d8)
    :param product_id: The product ID of the device (defaults to 0x00de)
    :param immediate_gpio_update: If `True`, immediately send any GPIO configuration changes to the device

    A usage example is below.

    .. code-block:: python

        import time
        from mcp2210 import Mcp2210, Mcp2210GpioDesignation, Mcp2210GpioDirection

        # To use this example code:
        #   connect LEDs to pins 0-4
        #   connect MISO to MOSI on the MCP2210 breakout board.

        # You can also connect either VCC or GND to pins 5-8.
        # Note that when unconnected the pins will read as False.

        # connect to the device by serial number
        mcp = Mcp2210(serial_number="0000992816")

        # this only needs to happen once
        # if you don't call this, the device will use the existing settings
        mcp.configure_spi_timing(chip_select_to_data_delay=0,
                                 last_data_byte_to_cs=0,
                                 delay_between_bytes=0)

        # set all pins as GPIO
        for i in range(9):
            mcp.set_gpio_designation(i, Mcp2210GpioDesignation.GPIO)

        # set lower GPIOs to output
        for i in range(0, 5):
            mcp.set_gpio_direction(i, Mcp2210GpioDirection.OUTPUT)

        # set upper GPIOs to input
        for i in range(5, 9):
            mcp.set_gpio_direction(i, Mcp2210GpioDirection.INPUT)
            print("Pin {}:".format(i), mcp.get_gpio_value(i))

        # flash an LED
        mcp.set_gpio_output_value(0, False)
        for i in range(3):
            mcp.set_gpio_output_value(0, True)
            time.sleep(0.5)
            mcp.set_gpio_output_value(0, False)
            time.sleep(0.5)

        # LED slider
        counter = 0
        for _ in range(20):
            counter += 1
            counter %= 5
            for i in range(5):
                mcp.set_gpio_output_value(i, counter == i)
            time.sleep(0.2)

        # turn all LEDs off
        for i in range(0, 5):
            mcp.set_gpio_output_value(i, False)

        # set pin 4 as CS, and transmit the bytes 0 through to 255 inclusive over SPI
        mcp.set_gpio_designation(4, Mcp2210GpioDesignation.CHIP_SELECT)
        tx_data = bytes(range(256))
        rx_data = mcp.spi_exchange(tx_data, cs_pin_number=4)

        # as MOSI is connected to MISO, check that the data matches what we sent
        assert rx_data == tx_data
    """

    def __init__(self, serial_number: str, vendor_id: int = 0x04d8, product_id: int = 0x00de,
                 immediate_gpio_update: bool = True):
        if not serial_number.isdigit():
            raise ValueError("Serial number must be numbers only")
        if len(serial_number) != 10:
            raise ValueError("Serial number must be exactly 10 digits")

        self._serial_number = serial_number
        self._vendor_id = vendor_id
        self._product_id = product_id

        self._immediate_gpio_update = immediate_gpio_update

        logging.info("MCP2210: opening device: " + str(self))
        self._hid = hid.device()
        self._hid.open(serial_number=serial_number, vendor_id=vendor_id, product_id=product_id)

        self._spi_settings = Mcp2210TransferConfiguration()
        self._gpio_settings = Mcp2210GpioConfiguration()

        self._gpio_settings_needs_update = False
        self._gpio_direction_needs_update = False
        self._gpio_output_needs_update = False

        self._get_spi_configuration()
        self._get_gpio_configuration()

        # need to set CS pin state for this to work
        self._spi_settings.idle_chip_select_value = 0x01FF
        self._spi_settings.active_chip_select_value = 0x0000
        self._set_spi_configuration()

    def __repr__(self):
        return "MCP2210 (serial: {}, VID: 0x{:04X}, PID: 0x{:04X})".format(self._serial_number,
                                                                           self._vendor_id,
                                                                           self._product_id)

    def _hid_write(self, payload: bytes, pad_with_zeros: bool = True):
        """
        Internal function to perform a HID write to the device.

        :param payload: Packet to send to the device (maximum 64 bytes)
        :param pad_with_zeros: Whether to pad with zeros up to the 64 byte boundary (default=True)
        """
        assert len(payload) <= 64

        if pad_with_zeros:
            request = payload + b'\x00' * (64 - len(payload))
        else:
            request = payload

        logger.debug("MCP2210: HID write: " + bytes_to_hex_string(request))
        if platform.system() == "Windows":
            # work around windows weirdness requiring prepended report ID for report 0
            self._hid.write(b"\x00" + bytes(request))
        else:
            self._hid.write(bytes(request))

    def _hid_read(self, size: int) -> bytes:
        """
        Internal function to perform a HID read from the device.

        :param size: Number of bytes to read
        :return: the bytes which were read
        """
        read_data = bytes(self._hid.read(size))

        logger.debug("MCP2210: HID read: " + bytes_to_hex_string(read_data))
        return read_data

    def _execute_command(self, request: bytes, pad_with_zeros: bool = True, check_return_code: bool = True) -> bytes:
        """
        Internal function to execute a command on the MCP2210.

        :param request: The request to send
        :param pad_with_zeros: if `True`, pad the request with zeros up to the 64 byte HID limit
        :param check_return_code: if `True`, throw an exception if an non-success code was returned
        :return: response data
        """
        self._hid_write(request, pad_with_zeros=pad_with_zeros)

        response = self._hid.read(64)
        if response[0] != request[0]:
            raise Mcp2210CommandResponseDesyncException

        if check_return_code:
            if response[1] == Mcp2210CommandResult.SUCCESS:
                pass
            elif response[1] == Mcp2210CommandResult.TRANSFER_IN_PROGRESS:
                raise Mcp2210UsbBusyException
            else:
                raise Mcp2210CommandFailedException

        return response

    def _get_spi_configuration(self):
        """
        Internal function which gets the SPI configuration from the MCP2210.
        """
        response = self._execute_command(bytes([Mcp2210Commands.GET_SPI_TRANSFER_SETTINGS]))

        structure_size = response[2]
        assert structure_size == 17  # according to the datasheet, this is always fixed at 17

        payload = bytes(response[4:4 + structure_size])
        self._spi_settings.unpack_from(payload)
        logger.debug("MCP2210: SPI settings read from device: " + str(self._spi_settings))

    def _set_spi_configuration(self):
        """
        Internal function which sends the SPI configuration to the MCP2210.
        """
        request = [Mcp2210Commands.SET_SPI_TRANSFER_SETTINGS, 0x00, 0x00, 0x00]
        packed = self._spi_settings.pack()

        response = self._execute_command(bytes(request) + packed)

        payload = bytes(response[4:21])
        assert packed == payload

        logger.debug("MCP2210: SPI settings sent to device: " + str(self._spi_settings))

    def _get_gpio_configuration(self):
        """
        Internal function which gets the GPIO configuration from the MCP2210.
        """
        response = self._execute_command(bytes([Mcp2210Commands.GET_GPIO_SETTINGS]))

        payload = bytes(response[4:18])
        self._gpio_settings.unpack_from(payload)
        logger.debug("MCP2210: GPIO settings read from device: " + str(self._gpio_settings))

        response = self._execute_command(bytes([Mcp2210Commands.GET_GPIO_PIN_DIRECTION]))
        payload = bytes(response[4:6])
        self._gpio_settings.gpio_direction = struct.unpack("<H", payload)[0]

        self.gpio_update()  # to read the inputs

    def _set_gpio_configuration(self):
        """
        Internal function which sends the GPIO configuration to the MCP2210.
        """
        if self._gpio_settings_needs_update:
            request = [Mcp2210Commands.SET_GPIO_SETTINGS, 0x00, 0x00, 0x00]
            packed = self._gpio_settings.pack()
            self._execute_command(bytes(request) + packed)

            self._gpio_settings_needs_update = False

        # send any direction changes
        if self._gpio_direction_needs_update:
            request = [Mcp2210Commands.SET_GPIO_PIN_DIRECTION, 0x00, 0x00, 0x00]
            packed = struct.pack("<H", self._gpio_settings.gpio_direction)
            self._execute_command(bytes(request) + packed)

            self._gpio_direction_needs_update = False

        # send any output changes
        if self._gpio_output_needs_update:
            request = [Mcp2210Commands.SET_GPIO_PIN_VALUE, 0x00, 0x00, 0x00]
            packed = struct.pack("<H", self._gpio_settings.gpio_output_level)
            self._execute_command(bytes(request) + packed)

    def gpio_update(self):
        """
        Updates any GPIO direction/output levels and reads the latest GPIO input data. If the `immediate_gpio_update`
        was set to `True` when this class was constructed, there is no need to call this function. Otherwise,
        it needs to be called manually each time any GPIO configuration is changed, or when the GPIO inputs are to be
        read.
        """
        self._set_gpio_configuration()

        # get the latest input values for the GPIO
        response = self._execute_command(bytes([Mcp2210Commands.GET_GPIO_PIN_VALUE]))
        payload = bytes(response[4:6])
        self._gpio_settings.gpio_input_level = struct.unpack("<H", payload)[0]

    def set_gpio_designation(self, pin_number: int, designation: Mcp2210GpioDesignation):
        """
        Designates a pin as either GPIO, chip select or alternate function.

        :param pin_number: The number of the pin of interest
        :param designation: The designation to set
        """
        if not 0 <= pin_number <= 8:
            raise ValueError("Pin number must be between 0 and 8 inclusive")

        if designation not in Mcp2210GpioDesignation.__members__.values():
            raise ValueError("Invalid pin designation")

        self._gpio_settings.gpio_designations[pin_number] = designation
        self._gpio_settings_needs_update = True

        if self._immediate_gpio_update:
            self.gpio_update()

    def set_gpio_direction(self, pin_number: int, direction: Mcp2210GpioDirection):
        """
        Configures a GPIO as either input or output

        :param pin_number: The number of the pin of interest
        :param direction: The direction to set
        """
        self._gpio_settings.set_gpio_direction_for_pin_number(pin_number, direction)
        self._gpio_direction_needs_update = True

        if self._immediate_gpio_update:
            self.gpio_update()

    def set_gpio_output_value(self, pin_number: int, value: bool):
        """
        Sets the value of a GPIO output

        :param pin_number: The number of the pin of interest
        :param value: The value to write to the pin
        """
        self._gpio_settings.set_gpio_output_value_for_pin_number(pin_number, value)
        self._gpio_output_needs_update = True

        if self._immediate_gpio_update:
            self.gpio_update()

    def get_gpio_value(self, pin_number: int) -> bool:
        """
        Read the value of a GPIO input.

        :param pin_number: The number of the pin of interest
        :return: The state of the pin
        """
        self.gpio_update()

        return self._gpio_settings.get_gpio_input_value_for_pin_number(pin_number)

    def spi_exchange(self, payload: bytes, cs_pin_number: int) -> bytes:
        """
        Performs an SPI exchange. Note that the pin corresponding to the number provided must already be designated
        as a CS pin using :func:`~mcp2210.Mcp2210.set_gpio_designation`.

        :param payload: The bytes to send in the transaction
        :param cs_pin_number: The pin number which is to be used as CS.
        :return: The bytes which were received as part of the exchange
        """
        if not 0 <= cs_pin_number <= 8:
            raise ValueError("CS pin number must be between 0 and 8 inclusive")

        if self._gpio_settings.gpio_designations[cs_pin_number] != Mcp2210GpioDesignation.CHIP_SELECT:
            raise ValueError("Pin is not designated as a chip select pin")

        self._spi_settings.active_chip_select_value = 0x01FF ^ (1 << cs_pin_number)
        self._spi_settings.transfer_size = len(payload)
        self._set_spi_configuration()
        
        chunked_payload = []
        for i in range(math.ceil(len(payload) / 60)):
            start_index = i * 60
            stop_index = (i + 1) * 60
            chunk = bytes(payload[start_index:stop_index])
            chunked_payload.append(chunk)

        chunk_index = 0
        received_data = []
        while 1:
            if chunk_index == len(chunked_payload):
                next_chunk = b''
            else:
                next_chunk = chunked_payload[chunk_index]

            request = [Mcp2210Commands.TRANSFER_SPI_DATA, len(next_chunk), 0x00, 0x00]
            response = self._execute_command(bytes(request) + next_chunk, check_return_code=False)

            if response[1] == Mcp2210CommandResult.SPI_DATA_NOT_ACCEPTED:
                raise Mcp2210SpiBusLockedException
            elif response[1] == Mcp2210CommandResult.TRANSFER_IN_PROGRESS:
                time.sleep(0.005)
                continue
            elif response[1] == Mcp2210CommandResult.SUCCESS:
                # data was accepted, move to next chunk
                chunk_index += 1

                receive_data_size = response[2]
                spi_transfer_status = response[3]

                if spi_transfer_status == Mcp2210SpiTransferStatus.SPI_TRANSFER_PENDING_NO_RECEIVED_DATA:
                    continue
                elif spi_transfer_status == Mcp2210SpiTransferStatus.SPI_TRANSFER_PENDING_RECEIVED_DATA_AVAILABLE:
                    received_data.append(response[4:receive_data_size + 4])
                    continue
                elif spi_transfer_status == Mcp2210SpiTransferStatus.SPI_TRANSFER_COMPLETE:
                    received_data.append(response[4:receive_data_size + 4])
                    break
                else:
                    raise Mcp2210CommandFailedException("Encountered unknown SPI transfer status")
            else:
                raise Mcp2210CommandFailedException("Received return code 0x{:02X} from device".format(response[1]))

        combined_receive_data = b''.join(bytes(x) for x in received_data)
        if len(combined_receive_data) != len(payload):
            raise RuntimeError("Length of receive data does not match transmit data")

        return combined_receive_data

    def configure_spi_timing(self, chip_select_to_data_delay: int = None, last_data_byte_to_cs: int = None,
                             delay_between_bytes: int = None):
        """
        Configure the timing parameters for an SPI transaction. All delays are in 100 microsecond steps. If these
        delays are not needed, they can be set to 0. Note that there will still be some minimal delays between the
        events due to the way the device works (typically about 30-40us).

        If this function is never called, the delays will be whatever the device was configured with previously.

        If `None` is passed as a parameter, the value will remain unchanged.

        :param chip_select_to_data_delay: Delay between CS assert and first data byte
        :param last_data_byte_to_cs: Delay between the last data byte and CS de-assert
        :param delay_between_bytes: Delay between bytes
        """
        if chip_select_to_data_delay is not None:
            self._spi_settings.chip_select_to_data_delay = chip_select_to_data_delay
        if last_data_byte_to_cs is not None:
            self._spi_settings.last_data_byte_to_cs_delay = last_data_byte_to_cs
        if delay_between_bytes is not None:
            self._spi_settings.delay_between_bytes = delay_between_bytes

        self._set_spi_configuration()

    def set_spi_mode(self, mode: int):
        """
        Sets the SPI mode of the device

        :param mode: the SPI mode (0, 1, 2 or 3)
        """

        self._spi_settings.mode = mode
        self._set_spi_configuration()