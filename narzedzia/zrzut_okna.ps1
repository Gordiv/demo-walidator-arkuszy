<#
.SYNOPSIS
  Zapisuje zrzut okna programu (PNG) do dokumentacji. Opcjonalnie wysyła wcześniej skrót klawiszowy.
.EXAMPLE
  .\narzedzia\zrzut_okna.ps1 -Tytul "Walidator arkuszy" -Plik docs\zrzuty\okno.png -Klawisze "^{ENTER}" -Czekaj 4
#>
param(
    [Parameter(Mandatory)] [string] $Tytul,
    [Parameter(Mandatory)] [string] $Plik,
    [string] $Klawisze = "",
    [double] $Czekaj = 2
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing, System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class Okno {
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
    [DllImport("dwmapi.dll")] public static extern int DwmGetWindowAttribute(IntPtr h, int attr, out RECT r, int size);
}
"@

$okno = [IntPtr]::Zero
for ($i = 0; $i -lt 75 -and $okno -eq [IntPtr]::Zero; $i++) {
    Start-Sleep -Milliseconds 200
    $proces = Get-Process | Where-Object { $_.MainWindowTitle -eq $Tytul } | Select-Object -First 1
    if ($proces) { $okno = $proces.MainWindowHandle }
}
if ($okno -eq [IntPtr]::Zero) { throw ("Nie znaleziono okna o tytule: " + $Tytul) }

if ([Okno]::IsIconic($okno)) { [void][Okno]::ShowWindow($okno, 9) }
[void][Okno]::SetForegroundWindow($okno)
Start-Sleep -Milliseconds 400
if ($Klawisze) { [System.Windows.Forms.SendKeys]::SendWait($Klawisze) }
Start-Sleep -Milliseconds ([int]($Czekaj * 1000))

$caly = New-Object Okno+RECT
[void][Okno]::GetWindowRect($okno, [ref]$caly)
$widoczny = New-Object Okno+RECT
# DWMWA_EXTENDED_FRAME_BOUNDS = 9: the window without the invisible resize border
[void][Okno]::DwmGetWindowAttribute($okno, 9, [ref]$widoczny, 16)

$szer = $caly.Right - $caly.Left
$wys = $caly.Bottom - $caly.Top
$bitmapa = New-Object System.Drawing.Bitmap $szer, $wys
$grafika = [System.Drawing.Graphics]::FromImage($bitmapa)
$dc = $grafika.GetHdc()
# PW_RENDERFULLCONTENT = 2 captures the real content, also of windows drawn by DirectComposition
[void][Okno]::PrintWindow($okno, $dc, 2)
$grafika.ReleaseHdc($dc)

$wyciecie = New-Object System.Drawing.Rectangle ($widoczny.Left - $caly.Left), ($widoczny.Top - $caly.Top), ($widoczny.Right - $widoczny.Left), ($widoczny.Bottom - $widoczny.Top)
$wynik = $bitmapa.Clone($wyciecie, $bitmapa.PixelFormat)
$katalog = Split-Path -Parent $Plik
if ($katalog -and -not (Test-Path $katalog)) { New-Item -ItemType Directory -Force $katalog | Out-Null }
$wynik.Save((Resolve-Path -LiteralPath $katalog).Path + "\" + (Split-Path -Leaf $Plik), [System.Drawing.Imaging.ImageFormat]::Png)
$grafika.Dispose(); $bitmapa.Dispose(); $wynik.Dispose()
Write-Output "Zapisano $Plik ($($wyciecie.Width)x$($wyciecie.Height))"
