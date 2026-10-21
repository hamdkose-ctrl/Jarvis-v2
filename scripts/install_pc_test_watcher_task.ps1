param(
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$TaskName = 'Jarvis PC Test Watcher'
$Pattern = 'refs/remotes/origin/gpt/windows-pc-watcher'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Watcher = Join-Path $RepoRoot 'scripts\pc_test_watcher.bat'
$CurrentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name

if ($Remove) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -ne $existing) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host 'Jarvis PC test watcher otomatik baslatma kaldirildi.'
    } else {
        Write-Host 'Jarvis PC test watcher otomatik baslatma zaten kurulu degil.'
    }
    exit 0
}

if (-not (Test-Path -LiteralPath $Watcher -PathType Leaf)) {
    throw "Watcher bulunamadi: $Watcher"
}

$escapedWatcher = $Watcher.Replace("'", "''")
$command = "& '$escapedWatcher' --pattern $Pattern"
$arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command "' + $command.Replace('"', '`"') + '"'

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $CurrentUser
$principal = New-ScheduledTaskPrincipal -UserId $CurrentUser -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Jarvis-v2 yeni watcher commitlerini gercek interaktif Windows PC kabulunden gecirir.' `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Milliseconds 500
$task = Get-ScheduledTask -TaskName $TaskName
$info = Get-ScheduledTaskInfo -TaskName $TaskName

Write-Host "Kuruldu: $TaskName"
Write-Host "Kullanici: $CurrentUser"
Write-Host "Repo: $RepoRoot"
Write-Host "Izlenen dal: $Pattern"
Write-Host "Durum: $($task.State)"
Write-Host "Son sonuc kodu: $($info.LastTaskResult)"
Write-Host 'Windows oturumu acildiginda watcher otomatik baslayacak; servis oturumunda calismaz.'
