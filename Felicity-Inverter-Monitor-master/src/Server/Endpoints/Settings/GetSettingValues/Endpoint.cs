using InverterMon.Server.InverterService;
using InverterMon.Server.Persistence.Settings;
using InverterMon.Shared.Models;

namespace InverterMon.Server.Endpoints.Settings.GetSettingValues;

public class Endpoint : EndpointWithoutRequest<CurrentSettings>
{
    public UserSettings UserSettings { get; set; }
    public FelicitySolarInverter Inverter { get; set; }

    public override void Configure()
    {
        Get("settings/get-setting-values");
        AllowAnonymous();
    }

    public override async Task HandleAsync(CancellationToken c)
    {
        if (Env.IsDevelopment())
        {
            var res = new CurrentSettings
            {
                BackToBatteryVoltage = 48.1,
                BackToGridVoltage = 48.2,
                FloatChargeVoltage = 48.3,
                ChargePriority = ChargePriority.OnlySolar,
                DischargeCuttOffVoltage = 48.4,
                BulkChargeVoltage = 48.5,
                MaxACChargeCurrent = 10,
                MaxCombinedChargeCurrent = 20,
                OutputPriority = OutputPriority.SolarFirst,
                SystemSpec = UserSettings.ToSystemSpec()
            };
            await SendAsync(res, cancellation: c);

            return;
        }

        try
        {
            var data = Inverter.ReadSettings();
            var res = new CurrentSettings
            {
                BackToBatteryVoltage = data.BatteryBackToDischargeVoltage,
                BackToGridVoltage = data.BatteryBackToChargeVoltage,
                BulkChargeVoltage = data.BatteryCvChargingVoltage,
                ChargePriority = data.ChargingSourcePriority,
                DischargeCuttOffVoltage = data.BatteryCutOffVoltage,
                FloatChargeVoltage = data.BatteryFloatingChargingVoltage,
                MaxACChargeCurrent = data.MaxAcChargingCurrent,
                MaxCombinedChargeCurrent = data.MaxChargingCurrent,
                OutputPriority = data.OutputSourcePriority,
                SystemSpec = UserSettings.ToSystemSpec()
            };
            await SendAsync(res, cancellation: c);
        }
        catch (Exception e)
        {
            Logger.LogError("Unable to read settings from inverter. Details: [{msg}]", e.Message);
            ThrowError("Unable to read settings from inverter!");
        }
    }
}