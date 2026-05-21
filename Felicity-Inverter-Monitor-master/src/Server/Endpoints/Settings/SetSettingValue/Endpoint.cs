using InverterMon.Server.InverterService;

namespace InverterMon.Server.Endpoints.Settings.SetSettingValue;

public class Endpoint : Endpoint<Shared.Models.SetSetting, bool>
{
    public FelicitySolarInverter Inverter { get; set; }

    public override void Configure()
    {
        Get("settings/set-setting/{Setting}/{Value}");
        AllowAnonymous();
    }

    public override async Task HandleAsync(Shared.Models.SetSetting r, CancellationToken c)
    {
        if (Env.IsDevelopment())
        {
            await SendAsync(true, cancellation: c);

            return;
        }

        try
        {
            Inverter.SetSetting(r.Setting, r.Value);
            await SendAsync(true, cancellation: c);
        }
        catch
        {
            await SendAsync(false, cancellation: c);
        }
    }
}