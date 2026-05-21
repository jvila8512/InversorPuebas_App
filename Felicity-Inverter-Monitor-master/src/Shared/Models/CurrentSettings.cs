namespace InverterMon.Shared.Models;

public class CurrentSettings
{
    public byte ChargePriority { get; set; }
    public byte OutputPriority { get; set; }
    public byte MaxACChargeCurrent { get; set; }
    public byte MaxCombinedChargeCurrent { get; set; }

    double _backToGrid;

    public double BackToGridVoltage
    {
        get => _backToGrid;
        set => _backToGrid = value; //RoundToHalfPoints(value);
    }

    double _dischargeCuttOff;

    public double DischargeCuttOffVoltage
    {
        get => _dischargeCuttOff;
        set => _dischargeCuttOff = value; // RoundToOneDecimalPoint(value);
    }

    double _bulkVoltage;

    public double BulkChargeVoltage
    {
        get => _bulkVoltage;
        set => _bulkVoltage = value; // RoundToOneDecimalPoint(value < _floatVoltage ? _floatVoltage : value);
    }

    double _floatVoltage;

    public double FloatChargeVoltage
    {
        get => _floatVoltage;
        set => _floatVoltage = value; // RoundToOneDecimalPoint(value > _bulkVoltage ? _bulkVoltage : value);
    }

    double _backToBattery;

    public double BackToBatteryVoltage
    {
        get => _backToBattery;
        set => _backToBattery = value; //RoundToHalfPoints(value);
    }

    public SystemSpec SystemSpec { get; set; } = new();

    // static double RoundToHalfPoints(double value)
    //     => Math.Round(value * 2, MidpointRounding.AwayFromZero) / 2;

    // static double RoundToOneDecimalPoint(double value)
    //     => Math.Round(value, 1, MidpointRounding.AwayFromZero);
}