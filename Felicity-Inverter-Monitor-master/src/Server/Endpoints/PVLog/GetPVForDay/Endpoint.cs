using InverterMon.Server.Persistence;
using InverterMon.Server.Persistence.Settings;
using InverterMon.Shared.Models;

namespace InverterMon.Server.Endpoints.PVLog.GetPVForDay;

public class Request
{
    public int DayNumber { get; set; }
}

public class Endpoint : Endpoint<Request, PVDay>
{
    public Database Db { get; set; }
    public UserSettings UsrSettings { get; set; }

    public override void Configure()
    {
        Get("/pv-log/get-pv-for-day/{DayNumber}");
        AllowAnonymous();
    }

    public override async Task HandleAsync(Request r, CancellationToken c)
    {
        var pvDay = Db.GetPvGenForDay(r.DayNumber);

        if (pvDay is null)
        {
            await SendNotFoundAsync(c);

            return;
        }

        if (Env.IsDevelopment() && pvDay.TotalWattHours == 0)
        {
            pvDay = new()
            {
                Id = DateOnly.FromDateTime(DateTime.Now).DayNumber,
                TotalWattHours = Random.Shared.Next(3000)
            };

            for (var i = 0; i < 97; i++)
                pvDay.WattPeaks.Add(i.ToString(), Random.Shared.Next(2000));
        }

        Response.GraphRange = UsrSettings.PVGraphRange;
        Response.GraphTickCount = UsrSettings.PVGraphTickCount;
        Response.TotalKiloWattHours = Math.Round(pvDay.TotalWattHours / 1000, 2);
        Response.DayNumber = pvDay.Id;
        Response.DayName = DateOnly.FromDayNumber(pvDay.Id).ToString("dddd MMMM dd");
        Response.WattPeaks = pvDay.WattPeaks.Select(
            p => new PVDay.WattPeak
            {
                MinuteBucket = p.Key,
                PeakWatt = p.Value
            });
    }
}