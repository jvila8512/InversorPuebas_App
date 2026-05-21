using InverterMon.Server.Persistence;
using InverterMon.Server.Persistence.Settings;

namespace InverterMon.Server.InverterService;

class StatusRetriever(
    Database db,
    FelicitySolarInverter inverter,
    UserSettings userSettings,
    IConfiguration config,
    ILogger<StatusRetriever> log,
    IHostApplicationLifetime appLife)
    : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken c)
    {
        var port = config["LaunchSettings:DeviceAddress"] ?? throw new ArgumentException("Device address not specified in appsettings.json file!");

        while (!inverter.Connect(port))
        {
            log.LogCritical("Unable to connect to the inverter at [{port}]. Retrying in 5 seconds...", port);
            await Task.Delay(5000);
        }

        log.LogInformation("Connected to inverter at device address: [{port}]", port);

        appLife.ApplicationStopping.Register(inverter.Close);

        while (!c.IsCancellationRequested && !appLife.ApplicationStopping.IsCancellationRequested)
        {
            inverter.Status.BatteryCapacity = userSettings.BatteryCapacity;
            inverter.Status.PV_MaxCapacity = userSettings.PV_MaxCapacity;

            try
            {
                inverter.UpdateStatus();
            }
            catch (Exception e)
            {
                log.LogError("Error while reading inverter status data! Details: [{msg}]", e.Message);
                await Task.Delay(2000);

                continue;
            }

            try
            {
                db.UpdateTodaysPvGeneration(c);
            }
            catch
            {
                //do nothing
            }

            await Task.Delay(2000, CancellationToken.None);
        }
    }
}