# High frequency inverter external communication protocol

## Definition of communication interface

> The external communication adopts UART communication, and the communication settings are: baud rate 2400bps, 8 data bits, 1 stop bit, no parity check, no flow control. The communication method adopts the half-duplex communication method. At the same time, only one of the master and the slave can send data, and the other can receive data. The external communication is initiated by the external controller (upper computer), and the inverter controller responds (does not actively initiate communication). Communication frame is MODBUS protocol frame.

## Communication frame definition (frame structure)

- **Slave address field**: 1-31 (decimal) (31 is broadcast address)
- **Functional domain**:
  - 0x03: Read multiple parameters
  - 0x06: Write a single parameter
  - 0x10: Write multiple parameters
  - 0x17: Master-slave synchronization data
  - 0x41: Firmware upgrade
- **Data field**: The data field includes the address field and the data payload field
- **CRC field**: 16bit CRC check value

### 2.1. Communication frame command and frame description

CRC check range is frame address ~ CRC field (excluding CRC field).

#### 2.1.1, 0x03 read multiple registers

The function code (command) is used to read the contents of a continuous block in the register. The request protocol data unit specifies the starting register address and the number of registers. In the corresponding register data, each register data contains two bytes (the binary number is right-aligned in each byte). For each register, the first byte is high and the second byte is low.

For example, request to read register 0x0001-0x0002:

| ask | ÿHexÿ | answer | ÿHexÿ |
| --- | --- | --- | --- |
| slave address | 01 | slave address | 01 |
| Order | 03 | Order | 03 |
| Register start address high | 00 | number of bytes | 04 |
| Register start address low | 01 | Register value high bit (01) | 0F |
| High register number | 00 | Register value low (01) | A0 |
| Low register number | 02 | Register value high bit (02) | 01 |
| CRC low bit | ------ | Low register value (02) | C2 |
| CRC high | ------ | CRC low bit | ------ |

#### 2.1.2, 0x06 write a single register

This function code (command) is used to write a holding register in the slave device. The request specifies the address of the register to be written. The normal response is the reply to the request, and then returns the written value of the contents of the register.

For example, it is required to write the address of register 0x0008 to write the value of 0xAAAA:

| ask | ÿHexÿ | answer | ÿHexÿ |
| --- | --- | --- | --- |
| slave address | 01 | slave address | 01 |
| Order | 06 | Order | 06 |
| Register start address high | 00 | Register start address high | 00 |
| Register start address low | 08 | Register start address low | 08 |
| register value high | AA | register value high | AA |
| register value low | AA | register value low | AA |
| CRC low bit | ------ | CRC low bit | ------ |
| CRC high | ------ | CRC high | ------ |

#### 2.1.3, 0x10 write multiple registers

This function code (command) is used to write a segment (sequence) of continuous address values into registers. The value to be written is the requirement specified in the data field. The data is a two-byte number register. Normal response returns the function code, start address and register write quantity.

For example, the data written to register 0x0001 address is data 0x1194, and the data written to register 0x0002 address is 0x01CC.

| ask | ÿHexÿ | answer | ÿHexÿ |
| --- | --- | --- | --- |
| slave address | 01 | slave address | 01 |
| Order | 10 | Order | 10 |
| Register start address high | 00 | Register start address high | 00 |
| Register start address low | 01 | Register start address low | 01 |
| High register number | 00 | High register number | 00 |
| Low register number | 02 | Low register number | 02 |
| number of bytes | 04 | CRC low bit | ------ |
| Register value high (01) | 11 | CRC high | ------ |
| Register value low (01) | 94 | | |
| Register value high bit (02) | 11 | | |
| Low register value (02) | CC | | |
| CRC low bit | ------ | | |
| CRC high | ------ | | |

## 3. Data register definition

### 3.1, Information Data register definition

| Address(Hex) | SIZE(Word) | register name | Data Type | Override | Unit | Attribute | Register Description | Remark |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0xF800 | 1 | Equipment Type | INT16U | 0 | - | R | DeviceType Category 0x50: High Frequency Inverter | |
| 0xF801 | 1 | SubType | INT16U | 0 | - | R | Device subclass 0x0204: 3024 (3000VA/24V) 0x0408: 5048 (5000VA/48V) | |
| 0xF804 | 5 | Serial number/SN | INT16U | 0 | - | R | The SN code is a 14-digit pure number, such as: SN=01354820250001, then: SN[0]=0135; SN[1]=4820; SN[2]=2500; SN[3]=0100; SN[4]=0000; invalid value: 0x00 | |
| 0xF80B | 1 | CPU1 F/W Version | INT16U | -2 | - | R | CPU1 F/W Version Invalid value: 0xFFFF | |
| 0xF80C | 1 | CPU2 F/W Version | INT16U | -2 | - | R | CPU2 F/W Version Invalid value: 0xFFFF | |

### 3.2, Realtime Data register definition

| Address(Hex) | SIZE(Word) | register name | Data Type | Override | Unit | Attribute | Register Description | Remark |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0x1100 | 1 | SettingDataSn | INT16U | 0 | - | R | The data in the serial number setting area of the setting parameter area has changed +1 | |
| 0x1101 | 1 | Working mode | INT16U | 0 | - | R | 0=power-on mode/PowerOnMode 1=standby mode/StandbyMode 2=bypass mode/BypassMode 3=battery mode/BatteryMode 4=fault mode/FaultMode 5=mains mode/LineMode 6=charging mode/PVChargeMode | |
| 0x1102 | 1 | Battery charging stage | INT16U | 0 | - | R | 0=no charging / No charge 1=Constant current charge/Bulk charge 2=Constant voltage charge/Absorption charge 3=Float charge/Float charge | |
| 0x1103 | 1 | Fault Code | INT16U | 0 | - | R | For fault code/Fault ID , see the high-frequency inverter fault alarm table for details | |
| 0x1104 | 1 | PowerFlowMsg | INT16U | 0 | - | R | energy flow information: b15: 0: Battery disconnected, 1: Battery connected; b14: 0: Line abnormal, 1: Line normal; b13: 0: PV input abnormal, 1: PV input normal; b12: 0: Load connect unallowed, 1: Load connect allowable; b11b10: 00: No power flow, 01: Battery charging, 10: Battery discharging; b9b8: 00: No power flow, 01: Draw power from Line, 10: Feed power to Line; b7: 0: No power flow, 1: PV MPPT working; b6: 0: No power flow, 1: Load connected; b0: 0: Power flow version unsupported, 1: Power flow version supported | |
| 0x1108 | 1 | Battery voltage | INT16U | -2 | V | R | battery voltage/Voltage | |
| 0x1109 | 1 | Battery current | INT16S | 0 | A | R | The battery current/Current has positive and negative values, the negative value is the positive and negative value of the discharge current | |
| 0x110A | 1 | Battery power | INT16S | 0 | W | R | Battery power, the negative value represents the discharge power | |
| 0x1111 | 1 | AC output voltage | INT16U | -1 | V | R | AC output voltage/Voltage | |
| 0x1117 | 1 | AC input voltage | INT16U | -1 | V | R | AC input voltage/Voltage | |
| 0x1119 | 1 | AC input frequency | INT16U | -2 | Hz | R | AC input frequency/Frequency | |
| 0x111E | 1 | AC output active power | INT16S | 0 | W | R | Output active power/Watt | |
| 0x111F | 1 | AC output apparent power | INT16U | 0 | VA | R | Output apparent power/VA | |
| 0x1120 | 1 | Load percentage | INT16U | 0 | % | R | Duty ratio/Pecent | |
| 0x1126 | 1 | PV input voltage | INT16U | -1 | V | R | PV voltage/Voltage | |
| 0x112A | 1 | PV input power | INT16S | 0 | W | R | PV power/Watt | |

### 3.3, Setting Data register definition

| Address(Hex) | SIZE(Word) | register name | Data Type | Override | Unit | Attribute | Register Description | Remark | Defaults | Setting Range Minimum | Setting Range Maximum |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0x211F | 1 | Battery cut-off voltage | INT16U | -1 | V | R/W | Discharge cut-off voltage | For model 3024, pcs=2; For model 5048, pcs=4 | 420 | 105/pcs | 135/pcs |
| 0x2122 | 1 | Battery C.V charging voltage | INT16U | -1 | V | R/W | Constant voltage charging voltage / Absorption voltage | For 3024: 24.0V~30.0V; 5048: 48.0V~60.0V | 576 | 120/pcs | 150/pcs |
| 0x2123 | 1 | Battery floating charging voltage | INT16S | -1 | V | R/W | Float charge voltage / Float voltage | For 3024: 24.0V~30.0V; 5048: 48.0V~60.0V | 544 | 120/pcs | 150/pcs |
| 0x2129 | 1 | AC output frequency | INT8U | 0 | Hz | R/W | 0=50Hz/1=60Hz | | 0 | 0 | 1 |
| 0x212A | 1 | Output source priority | INT8U | 0 | - | R/W | Output Priority: 0=Main power priority Utility First, 1=PV priority Solar First, 2=PV battery main power SolarBatUtility | | 0 | 0 | 2 |
| 0x212B | 1 | Application Mode | INT8U | 0 | - | R/W | 0=APL/1=UPS | | 0x00 | 0 | 1 |
| 0x212C | 1 | Charging source priority | INT8U | 0 | - | R/W | 1=PV priority Solar First, 2=PV and mains priority SolarAndUtilityFirst, 3=PV only SolarOnly | | 1 | 1 | 3 |
| 0x212D | 1 | Battery type | INT8U | 0 | - | R/W | 0=Gel battery AGM, 1=Flood battery, 2=User defined, 3=Lithium battery LiFePo4 | | 0 | 0 | 3 |
| 0x212E | 1 | Max. charging current | INT8U | 0 | A | R/W | Total charge current (one grid per 1A) | | 60 | 10 | 100 |
| 0x2130 | 1 | Max. AC charging current | INT8U | 0 | A | R/W | AC charge current (one grid per 1A) | | 30 | 10 | 100 |
| 0x2131 | 1 | Buzzer enable | INT8U | 0 | - | R/W | 0=Disable/1=Enable | | 0x01 | 0 | 1 |
| 0x2133 | 1 | Overload restart enable | INT8U | 0 | - | R/W | Overload restart enable bit: 0=disable/1=enable | | 0x00 | 0 | 1 |
| 0x2134 | 1 | Over temperature restart enable | INT8U | 0 | - | R/W | Over temperature restart enable bit: 0=disable/1=enable | | 0x01 | 0 | 1 |
| 0x2135 | 1 | LCD backlight enable | INT8U | 0 | - | R/W | Backlight: 0=Disable/1=Enable | | 0x00 | 0 | 1 |
| 0x2137 | 1 | OverLoad to bypass | INT8U | 0 | - | R/W | Overload transfer to bypass: 0=disable/1=enable | | 0x00 | 0 | 1 |
| 0x2156 | 1 | Battery back to charge voltage | INT16U | -1 | V | R/W | Battery low voltage to charge | | 460 | 110/pcs | 135/pcs |
| 0x2159 | 1 | Battery back to discharge voltage | INT16U | -1 | V | R/W | Battery high to discharge. If it exceeds the maximum value, it will display FULL. For example, 5048 model, 601 is FULL | | 540 | pcs + 1 | 150/pcs |

**Note**: For 3024 model, pcs=2, so min/max for voltage registers: 105/pcs = 52.5? Wait, interpretation needed. The document likely means the actual value is multiplied by the number of cells. For battery cut-off: 105/pcs means for 3024 (2 cells) it's 105*2=210 => 21.0V. For 5048 (4 cells) 105*4=420 => 42.0V. Same for others. I've kept as per original, but in practice you'd multiply by pcs.
