using InverterMon.Server.Persistence;
using InverterMon.Server.Persistence.Settings;

namespace InverterMon.Server.Endpoints.Settings.SetSystemSpec;

public class Endpoint : Endpoint<Shared.Models.SystemSpec>
{
    public UserSettings UserSettings { get; set; }
    public Database Db { get; set; }

    public override void Configure()
    {
        Post("settings/set-system-spec");
        AllowAnonymous();
    }

    public override async Task HandleAsync(Shared.Models.SystemSpec r, CancellationToken c)
    {
        UserSettings.FromSystemSpec(r);
        Db.UpdateUserSettings(UserSettings);
        await SendOkAsync();
    }
}