using InverterMon.Shared.Models;
using System.Runtime.CompilerServices;
using InverterMon.Server.InverterService;

namespace InverterMon.Server.Endpoints.GetStatus;

public class Endpoint : EndpointWithoutRequest<object>
{
    public FelicitySolarInverter Inverter { get; set; } = null!;
    public IHostApplicationLifetime AppLife { get; set; } = null!;

    public override void Configure()
    {
        Get("status");
        AllowAnonymous();
    }

    public override async Task HandleAsync(CancellationToken c)
    {
        try
        {
            await SendAsync(GetDataStream(c), cancellation: c);
        }
        catch (TaskCanceledException)
        {
            //nothing to do here
        }
    }

    async IAsyncEnumerable<InverterStatus> GetDataStream([EnumeratorCancellation] CancellationToken c)
    {
        while (!c.IsCancellationRequested && !AppLife.ApplicationStopping.IsCancellationRequested)
        {
            if (Env.IsDevelopment())
            {
                var status = new InverterStatus
                {
                    ChargeMode = ChargeMode.ABSORB,
                    OutputVoltage = Random.Shared.Next(240),
                    LoadWatts = Random.Shared.Next(3500),
                    LoadPercentage = Random.Shared.Next(100),
                    BatteryVoltage = Random.Shared.Next(24),
                    BatteryChargeCurrent = Random.Shared.Next(20),
                    BatteryDischargeCurrent = Random.Shared.Next(300),
                    PVInputVoltage = 0, //Random.Shared.Next(300),
                    PVInputWatt = Random.Shared.Next(1000),
                    PV_MaxCapacity = 1000,
                    BatteryCapacity = 100
                };

                yield return status;
            }
            else
                yield return Inverter.Status;

            await Task.Delay(2000, c);
        }
    }
}