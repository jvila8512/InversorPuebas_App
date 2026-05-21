namespace InverterMon.Server.Persistence.PVGen;

public class PVGeneration
{
    public int Id { get; set; }
    public Dictionary<string, int> WattPeaks { get; set; } = new();
    public double TotalWattHours { get; set; }

    public void SetWattPeaks(int newValue)
    {
        var key = DateTime.Now.ToTimeBucket();

        if (WattPeaks.TryGetValue(key, out var value))
        {
            if (value < newValue)
                WattPeaks[key] = newValue;
        }
        else
            WattPeaks[key] = newValue;
    }

    public void SetTotalWattHours(double totalWattHours)
    {
        TotalWattHours = totalWattHours;
    }
}