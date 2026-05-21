using System.Diagnostics.CodeAnalysis;

namespace InverterMon.Shared.Models;

public enum Setting : ushort
{
    ChargePriority = 0x212C,
    OutputPriority = 0x212A,
    CombinedChargeCurrent = 0x212E,
    UtilityChargeCurrent = 0x2130,
    BulkVoltage = 0x2122,
    FloatVoltage = 0x2123,
    DischargeCutOff = 0x211F,
    BackToGrid = 0x2156,
    BackToBattery = 0x2159
}

[SuppressMessage("ReSharper", "InconsistentNaming")]
public enum WorkingMode : ushort
{
    POWER = 0,
    STANDBY = 1,
    BYPASS = 2,
    BATTERY = 3,
    FAULT = 4,
    LINE = 5,
    CHARGING = 6
}

[SuppressMessage("ReSharper", "InconsistentNaming")]
public enum ChargeMode : ushort
{
    NONE = 0,
    BULK = 1,
    ABSORB = 2,
    FLOAT = 3
}