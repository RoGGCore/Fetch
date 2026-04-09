# FETCH — Başlangıçtan Kaldır
# Yönetici olarak çalıştırın!

$TaskName = "FETCH Medya Indirici"

if (-NOT ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "HATA: Yönetici olarak çalıştırın!" -ForegroundColor Red
    Pause; Exit 1
}

Stop-ScheduledTask  -TaskName $TaskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Write-Host "FETCH başlangıçtan kaldırıldı." -ForegroundColor Green
Pause
