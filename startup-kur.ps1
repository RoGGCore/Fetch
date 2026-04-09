# FETCH — Windows Başlangıç Kurulum Scripti
# Yönetici olarak çalıştırın!

$TaskName   = "FETCH Medya Indirici"
$AppDir     = "C:\Users\BilalPC\Desktop\mediaizle"
$PythonW    = (Get-Command pythonw.exe -ErrorAction SilentlyContinue)?.Source

# pythonw bulunamazsa python.exe'yi dene
if (-not $PythonW) {
    $PythonExe = (Get-Command python.exe).Source
    $PythonW   = $PythonExe -replace "python\.exe$", "pythonw.exe"
}

if (-not (Test-Path $PythonW)) {
    Write-Host "HATA: pythonw.exe bulunamadı!" -ForegroundColor Red
    Write-Host "Python'un tam yolunu girin (örn: C:\Python311\pythonw.exe):" -ForegroundColor Yellow
    $PythonW = Read-Host
}

Write-Host ""
Write-Host "=== FETCH Başlangıç Kurulumu ===" -ForegroundColor Cyan
Write-Host "Python  : $PythonW"
Write-Host "Klasör  : $AppDir"
Write-Host ""

# Yönetici kontrolü
if (-NOT ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "HATA: Yönetici olarak çalıştırın!" -ForegroundColor Red
    Pause; Exit 1
}

# Varsa eski görevi kaldır
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

# Görevi oluştur
$action = New-ScheduledTaskAction `
    -Execute $PythonW `
    -Argument "tray.py" `
    -WorkingDirectory $AppDir

# Oturum açılınca tetikle
$trigger = New-ScheduledTaskTrigger -AtLogOn

# Ayarlar: süre sınırı yok, kapanınca dur, hata olunca yeniden başlat
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit 0 `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StopIfGoingOnBatteries $false `
    -DisallowStartIfOnBatteries $false

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Highest `
    -Force | Out-Null

Write-Host "[OK] Görev oluşturuldu." -ForegroundColor Green

# Hemen başlat
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 2

$status = (Get-ScheduledTask -TaskName $TaskName).State
Write-Host "[OK] Görev durumu: $status" -ForegroundColor Green
Write-Host ""
Write-Host "✅ Kurulum tamamlandı!" -ForegroundColor Cyan
Write-Host "   FETCH artık Windows açılınca otomatik başlar." -ForegroundColor White
Write-Host "   Bilgisayar kapanınca da otomatik kapanır." -ForegroundColor White
Write-Host ""
Pause
