using System.Buffers;
using System.Diagnostics.CodeAnalysis;
using System.IO.Ports;
using InverterMon.Shared.Models;

namespace InverterMon.Server.InverterService;

sealed class SettingsData
{
    public double BatteryCutOffVoltage { get; init; }
    public double BatteryCvChargingVoltage { get; init; }
    public double BatteryFloatingChargingVoltage { get; init; }
    public double BatteryBackToChargeVoltage { get; init; }
    public double BatteryBackToDischargeVoltage { get; init; }
    public byte OutputSourcePriority { get; init; }
    public byte ChargingSourcePriority { get; init; }
    public byte MaxChargingCurrent { get; init; }
    public byte MaxAcChargingCurrent { get; init; }
}

[SuppressMessage("Performance", "CA1822:Mark members as static"),
 SuppressMessage("ReSharper", "MemberCanBeMadeStatic.Global")]
public sealed class FelicitySolarInverter
{
    public InverterStatus Status { get; } = new();

    const byte SlaveAddress = 0x01;
    static SerialPort _serialPort = null!;

    internal bool Connect(string portName)
    {
        lock (_lock)
        {
            _serialPort = new(portName, 2400, Parity.None, 8, StopBits.One);

            try
            {
                _serialPort.Open();
            }
            catch
            {
                return false;
            }
        }

        return true;
    }

    static byte[]? _cachedStatusFrame;

    // The status registers we need are located between 0x1101 and 0x112A.
    // Total registers to read = (0x112A - 0x1101 + 1)
    const ushort StatusStartAddress = 0x1101;
    const ushort StatusRegisterCount = 0x112A - 0x1101 + 1; // 42 registers

    internal void UpdateStatus()
    {
        var regs = ReadRegisters(StatusStartAddress, StatusRegisterCount);

        lock (_lock)
        {
            if (!_serialPort.IsOpen)
                return;
        }

        Status.WorkingMode = (WorkingMode)regs[0];              // 0x1101: Working mode (offset 0)
        Status.ChargeMode = (ChargeMode)regs[1];                // 0x1102: Battery charging stage (offset 1)
        Status.BatteryVoltage = Math.Round(regs[7] / 100.0, 1); // 0x1108: Battery voltage (offset 0x1108 - 0x1101 = 7)

        var disCur = ChargeStatus(regs[8]); // 0x1109: Battery current (offset 8) -- signed value
        Status.BatteryDischargeCurrent = disCur.IsDischarge ? disCur.PositiveValue : 0;
        Status.BatteryChargeCurrent = disCur.IsDischarge is false ? disCur.PositiveValue : 0;

        var disPow = ChargeStatus(regs[9]); // 0x110A: Battery power (offset 9) -- signed value
        Status.BatteryDischargeWatts = disPow.IsDischarge ? disPow.PositiveValue : 0;
        Status.BatteryChargeWatts = disPow.IsDischarge is false ? disPow.PositiveValue : 0;

        Status.OutputVoltage = Math.Round(regs[16] / 10.0, 0);  // 0x1111: AC output voltage (offset 0x1111 - 0x1101 = 16)
        Status.GridVoltage = Convert.ToInt32(regs[22] / 10.0);  // 0x1111: AC output voltage (offset 0x1117 - 0x1101 = 22)
        Status.LoadWatts = regs[29];                            // 0x111E: AC output active power (offset 0x111E - 0x1101 = 29)
        Status.LoadPercentage = regs[31];                       // 0x1120: Load percentage (offset 0x1120 - 0x1101 = 31)
        Status.PVInputVoltage = Math.Round(regs[37] / 10.0, 0); // 0x1126: PV input voltage (offset 0x1126 - 0x1101 = 37)
        Status.PVInputWatt = regs[41];                          // 0x112A: PV input power (offset 0x112A - 0x1101 = 41) -- signed value

        static (bool IsDischarge, short PositiveValue) ChargeStatus(short value)
        {
            var isNegative = value < 0;
            var positiveValue = isNegative ? (short)-value : value;

            return (isNegative, positiveValue);
        }
    }

    // The settings registers we need are located between 0x211F and 0x2159.
    // Total registers to read = (0x2159 - 0x211F + 1)
    const ushort SettingsStartAddress = 0x211F;
    const ushort SettingsRegisterCount = 0x2159 - 0x211F + 1; // 59 registers

    internal SettingsData ReadSettings()
    {
        var regs = ReadRegisters(SettingsStartAddress, SettingsRegisterCount);

        var settings = new SettingsData
        {
            BatteryCutOffVoltage = regs[0] / 10.0,           // 0x211F: Battery cut-off voltage (offset 0)
            BatteryCvChargingVoltage = regs[3] / 10.0,       // 0x2122: Battery C.V charging voltage (offset = 0x2122 - 0x211F = 3)
            BatteryFloatingChargingVoltage = regs[4] / 10.0, // 0x2123: Battery floating charging voltage (offset = 4)
            OutputSourcePriority = (byte)regs[11],           // 0x212A: Output source priority (offset = 0x212A - 0x211F = 11)
            ChargingSourcePriority = (byte)regs[13],         // 0x212C: Charging source priority (offset = 0x212C - 0x211F = 13)
            MaxChargingCurrent = (byte)regs[15],             // 0x212E: Max charging current (offset = 15)
            MaxAcChargingCurrent = (byte)regs[17],           // 0x2130: Max AC charging current (offset = 17)
            BatteryBackToChargeVoltage = regs[55] / 10.0,    // 0x2156: Battery back to charge voltage (offset = 0x2156 - 0x211F = 55)
            BatteryBackToDischargeVoltage = regs[58] / 10.0  // 0x2159: Battery back to discharge voltage (offset = 0x2159 - 0x211F = 58)
        };

        return settings;
    }

    internal void SetSetting(Setting setting, double value)
    {
        value *= setting switch
        {
            Setting.DischargeCutOff or Setting.BulkVoltage or Setting.FloatVoltage or Setting.BackToGrid or Setting.BackToBattery => 10,
            _ => 1
        };

        var registerAddress = (ushort)setting;
        var settingValue = (ushort)value;

        // Build request frame:
        // [Slave Address][Function Code 0x06][Register Address Hi][Register Address Lo]
        // [Value Hi][Value Lo][CRC Lo][CRC Hi]
        var frame = new byte[8];
        frame[0] = SlaveAddress;
        frame[1] = 0x06;
        frame[2] = (byte)(registerAddress >> 8);
        frame[3] = (byte)(registerAddress & 0xFF);
        frame[4] = (byte)(settingValue >> 8);
        frame[5] = (byte)(settingValue & 0xFF);
        var crc = CalculateCrc(frame, 6);
        frame[6] = (byte)(crc & 0xFF);
        frame[7] = (byte)(crc >> 8);

        SendModbusRequest(frame);
    }

    internal void Close()
    {
        lock (_lock)
        {
            if (_serialPort.IsOpen)
                _serialPort.Close();
        }
    }

    static short[] ReadRegisters(ushort startAddress, ushort numberOfPoints)
    {
        // Build Modbus request frame:
        // [Slave Address][Function Code 0x03][Start Address Hi][Start Address Lo][Quantity Hi][Quantity Lo][CRC Lo][CRC Hi]

        byte[] frame;

        var statusRequest = startAddress == StatusStartAddress && numberOfPoints == StatusRegisterCount;

        if (statusRequest && _cachedStatusFrame is not null)
            frame = _cachedStatusFrame;
        else
        {
            frame = new byte[8];
            frame[0] = SlaveAddress;
            frame[1] = 0x03;
            frame[2] = (byte)(startAddress >> 8);
            frame[3] = (byte)(startAddress & 0xFF);
            frame[4] = (byte)(numberOfPoints >> 8);
            frame[5] = (byte)(numberOfPoints & 0xFF);
            var crc = CalculateCrc(frame, 6);
            frame[6] = (byte)(crc & 0xFF);
            frame[7] = (byte)(crc >> 8);

            if (statusRequest)
                _cachedStatusFrame = frame;
        }

        var response = SendModbusRequest(frame);

        if (response.Length == 0)
            return [];

        // Expected response structure:
        // [Slave Address][Function Code][Byte Count][Data...][CRC Lo][CRC Hi]

        int byteCount = response[2];
        var expectedDataBytes = numberOfPoints * 2;

        if (byteCount != expectedDataBytes)
            throw new InvalidDataException("Unexpected byte count in response!");

        var registers = new short[numberOfPoints];
        for (var i = 0; i < numberOfPoints; i++)
            registers[i] = (short)((response[3 + i * 2] << 8) | response[3 + i * 2 + 1]);

        return registers;
    }

    static readonly object _lock = new();

    static byte[] SendModbusRequest(byte[] request)
    {
        lock (_lock) //prevent concurrent access
        {
            if (!_serialPort.IsOpen)
                return [];

            _serialPort.DiscardInBuffer();
            _serialPort.DiscardOutBuffer();

            var oldTimeout = _serialPort.ReadTimeout;
            var buffer = ArrayPool<byte>.Shared.Rent(256);

            try
            {
                _serialPort.ReadTimeout = 1000;
                _serialPort.Write(request, 0, request.Length);

                var totalBytesRead = ReadBytes(buffer, 0, 3); // Read fixed header (3 bytes)

                if ((buffer[1] & 0x80) != 0)                   // Handle Modbus exceptions (function code with high bit set)
                    totalBytesRead += ReadBytes(buffer, 3, 2); // Error response: read remaining 2 bytes (CRC)
                else
                {
                    // Calculate remaining bytes based on function code
                    var bytesToRead = GetRemainingBytes(buffer[1], buffer[2]);
                    totalBytesRead += ReadBytes(buffer, 3, bytesToRead);
                }

                var response = new byte[totalBytesRead];
                Buffer.BlockCopy(buffer, 0, response, 0, totalBytesRead);

                return response;
            }
            finally
            {
                ArrayPool<byte>.Shared.Return(buffer);
                _serialPort.ReadTimeout = oldTimeout;
            }
        }

        static int ReadBytes(byte[] b, int offset, int count)
        {
            var bytesRead = 0;

            while (bytesRead < count)
            {
                var read = _serialPort.Read(b, offset + bytesRead, count - bytesRead);

                if (read == 0)
                    throw new TimeoutException("No data received");

                bytesRead += read;
            }

            return bytesRead;
        }

        static int GetRemainingBytes(byte functionCode, byte byteCount)
        {
            return functionCode switch
            {
                0x03 => 2 + byteCount, // Read holding registers
                0x06 => 4,             // Write single register (fixed 4 bytes)
                0x10 => 4,             // Write multiple registers (fixed 4 bytes)
                _ => throw new NotSupportedException($"Function code 0x{functionCode:X2} not supported")
            };
        }
    }

    static ushort CalculateCrc(byte[] data, int length)
    {
        ushort crc = 0xFFFF;

        for (var pos = 0; pos < length; pos++)
        {
            crc ^= data[pos];

            for (var i = 0; i < 8; i++)
            {
                if ((crc & 0x0001) != 0)
                {
                    crc >>= 1;
                    crc ^= 0xA001;
                }
                else
                    crc >>= 1;
            }
        }

        return crc;
    }
}