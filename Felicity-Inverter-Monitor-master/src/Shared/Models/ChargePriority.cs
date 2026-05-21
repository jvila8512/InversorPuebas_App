namespace InverterMon.Shared.Models;

public static class ChargePriority
{
    public const byte SolarFirst = 1;
    public const byte SolarAndUtility = 2;
    public const byte OnlySolar = 3;
    public const byte UtilityFirst = 0;
}