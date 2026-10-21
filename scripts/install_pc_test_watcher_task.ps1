param([switch]$Remove)

$ErrorActionPreference = 'Stop'
$TaskName = 'Jarvis PC Test Watcher'
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
        Write-Host 'Jarvis PC test watcher zaten kurulu degil.'
    }
    exit 0
}

if (-not (Test-Path -LiteralPath $Watcher -PathType Leaf)) {
    throw "Watcher bulunamadi: $Watcher"
}

$escapedWatcher = $Watcher.Replace("'", "''")
$command = "& '$escapedWatcher'"
$arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command "' + $command.Replace('"', '`"') + '"'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $CurrentUser
$principal = New-ScheduledTaskPrincipal -UserId $CurrentUser -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Jarvis-v2 gpt/* dallarini gercek Windows PC kabulunden gecirir ve Terra takip dongusunu calistirir.' -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "Kuruldu: $TaskName"
Write-Host "Kullanici: $CurrentUser"
Write-Host "Repo: $RepoRoot"
Write-Host 'Izlenen dallar: refs/remotes/origin/gpt/*'
