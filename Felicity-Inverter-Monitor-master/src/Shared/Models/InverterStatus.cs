using System.Text.Json.Serialization;

// ReSharper disable InconsistentNaming

namespace InverterMon.Shared.Models;

public class InverterStatus
{
    [JsonPropertyName("a")]
    public int BatteryCapacity { get; set; } = 100;

    [JsonPropertyName("b")]
    public double BatteryChargeCRate => BatteryChargeCurrent == 0 ? 0 : Math.Round(Convert.ToDouble(BatteryChargeCurrent) / BatteryCapacity, 2);

    [JsonPropertyName("c")]
    public int BatteryChargeCurrent { get; set; }

    [JsonPropertyName("d")]
    public int BatteryChargeWatts { get; set; }

    [JsonPropertyName("e")]
    public double BatteryDischargeCRate => BatteryDischargeCurrent == 0 ? 0 : Math.Round(Convert.ToDouble(BatteryDischargeCurrent) / BatteryCapacity, 2);

    [JsonPropertyName("f")]
    public int BatteryDischargeCurrent { get; set; }

    [JsonPropertyName("g")]
    public int BatteryDischargePotential => BatteryDischargeCurrent == 0 ? 00 : Convert.ToInt32(Convert.ToDouble(BatteryDischargeCurrent) / BatteryCapacity * 100);

    [JsonPropertyName("h")]
    public int BatteryDischargeWatts { get; set; }

    [JsonPropertyName("i")]
    public double BatteryVoltage { get; set; }

    [JsonPropertyName("j")]
    public int GridUsageWatts => GridVoltage < 10 ? 0 : LoadWatts + BatteryChargeWatts - (PVInputWatt + BatteryDischargeWatts);

    [JsonPropertyName("k")]
    public int GridVoltage { get; set; }

    [JsonPropertyName("l")]
    public WorkingMode WorkingMode { get; set; }

    [JsonPropertyName("m")]
    public double LoadCurrent => LoadWatts == 0 ? 0 : Math.Round(LoadWatts / OutputVoltage, 1);

    [JsonPropertyName("n")]
    public int LoadPercentage { get; set; }

    [JsonPropertyName("o")]
    public int LoadWatts { get; set; }

    [JsonPropertyName("p")]
    public double OutputVoltage { get; set; }

    [JsonPropertyName("q")]
    public double PVInputCurrent => PVInputWatt == 0 || PVInputVoltage == 0 ? 0 : Math.Round(PVInputWatt / PVInputVoltage, 1);

    [JsonPropertyName("r")]
    public double PVInputVoltage { get; set; }

    [JsonPropertyName("s")]
    public int PVInputWatt
    {
        get => pvInputWatt;
        set
        {
            if (value <= 0 || value == pvInputWatt)
                return;

            pvInputWatt = value;
            var interval = (DateTime.Now - pvInputWattHourLastComputed).TotalSeconds;
            PVInputWattHour += value / (3600 / interval);
            pvInputWattHourLastComputed = DateTime.Now;
        }
    }

    [JsonIgnore]
    public double PVInputWattHour { get; private set; }

    [JsonPropertyName("t")]
    public int PV_MaxCapacity { get; set; }

    [JsonPropertyName("u")]
    public int PVPotential => PVInputWatt == 0 ? 0 : Convert.ToInt32(Convert.ToDouble(PVInputWatt) / PV_MaxCapacity * 100);

    [JsonPropertyName("v")]
    public ChargeMode ChargeMode { get; set; }

    int pvInputWatt;
    DateTime pvInputWattHourLastComputed;

    public void RestorePVWattHours(double accruedWattHours)
    {
        PVInputWattHour = accruedWattHours;
        pvInputWattHourLastComputed = DateTime.Now;
    }

    public void ResetPVWattHourAccumulation()
    {
        PVInputWattHour = 0;
        pvInputWattHourLastComputed = DateTime.Now;
    }
}