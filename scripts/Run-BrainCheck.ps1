param(
    [string]$RepoRoot,
    [string]$Ref = 'main',
    [switch]$Install,
    [switch]$Full
)
$ErrorActionPreference = 'Stop'
# BEGIN-CLONE-CLEANUP
function Remove-BrainCheckClone {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $true }
    # .NET silmesi hem uzun hem 8.3 kısa yol biçiminde özyinelemeli çalışır; Remove-Item -LiteralPath kısa adı reddediyor.
    # Başarısızlık yutulmaz, uyarı olarak görünür kalır.
    try {
        [IO.Directory]::Delete($Path, $true)
        return $true
    } catch {
        Write-Warning "Geçici kaynak klonu silinemedi, elle temizlenebilir: $Path"
        return $false
    }
}
# END-CLONE-CLEANUP
$Sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
if ($Sid -in @('S-1-5-18', 'S-1-5-19', 'S-1-5-20')) {
    throw 'Run in the Windows account where Jarvis is configured.'
}
if (-not $RepoRoot) {
    $Task = Get-ScheduledTask -TaskName 'Jarvis PC Test Watcher' -ErrorAction SilentlyContinue
    if ($Task) { $RepoRoot = @($Task.Actions)[0].WorkingDirectory }
}
if (-not $RepoRoot) { $RepoRoot = (Get-Location).Path }
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot 'config.py'))) {
    throw 'Pass -RepoRoot with the installed Jarvis Git folder.'
}
if ($Ref -notmatch '^(main|refs/pull/[0-9]+/head)$') {
    throw 'Ref must be main or refs/pull/<number>/head.'
}
if ($Install) {
    $HomeDir = Join-Path $env:LOCALAPPDATA 'Jarvis\brain-check'
    New-Item -ItemType Directory -Path $HomeDir -Force | Out-Null
    $Installed = Join-Path $HomeDir 'Run-BrainCheck.ps1'
    if ([IO.Path]::GetFullPath($PSCommandPath) -ne [IO.Path]::GetFullPath($Installed)) {
        Copy-Item -LiteralPath $PSCommandPath -Destination $Installed -Force
    }
    $Shell = New-Object -ComObject WScript.Shell
    foreach ($Mode in @('Quick', 'Full')) {
        $LinkPath = Join-Path ([Environment]::GetFolderPath('Desktop')) ("Jarvis Brain $Mode.lnk")
        $Link = $Shell.CreateShortcut($LinkPath)
        $Link.TargetPath = Join-Path $PSHOME 'powershell.exe'
        $Link.Arguments = '-NoExit -NoProfile -File "' + $Installed + '" -RepoRoot "' + $RepoRoot + '" -Ref "' + $Ref + '"'
        if ($Mode -eq 'Full') { $Link.Arguments += ' -Full' }
        $Link.WorkingDirectory = $RepoRoot
        $Link.Save()
    }
    Write-Host 'Installed desktop shortcuts: Jarvis Brain Quick (1 request), Jarvis Brain Full (20 cases).'
    return
}
$Python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$PythonArgs = @()
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    $Python = (Get-Command py -ErrorAction Stop).Source
    $PythonArgs = @('-3.13')
}
# Fetch only; never switch/reset the installed checkout or copy its profile.
& git -C $RepoRoot fetch origin $Ref
if ($LASTEXITCODE -ne 0) { throw 'Cannot fetch the requested source revision.' }
$Commit = (& git -C $RepoRoot rev-parse FETCH_HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $Commit -notmatch '^[0-9a-f]{40}$') { throw 'Cannot resolve the exact source commit.' }
$RunDir = Join-Path $env:TEMP ('jarvis-brain-' + [guid]::NewGuid().ToString('N'))
$ReportDir = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Jarvis-Brain-Acceptance'
New-Item -ItemType Directory -Path $ReportDir -Force | Out-Null
$Scope = if ($Full) { 'holdout' } else { 'connection' }
$Report = Join-Path $ReportDir ("brain-$Scope-" + $Commit.Substring(0,12) + '-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff') + '.json')
$ExitCode = 2
try {
    & git clone --shared --no-checkout $RepoRoot $RunDir
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create the temporary source snapshot.' }
    & git -C $RunDir checkout --detach $Commit
    if ($LASTEXITCODE -ne 0) { throw 'Cannot select the source commit.' }
    $Runner = Join-Path $RunDir 'scripts\brain_output_diagnose_holdout.py'
    $RunArgs = @('--run', '--json', $Report)
    if (-not $Full) { $RunArgs += '--connection-only' }
    & $Python @PythonArgs -X utf8 $Runner @RunArgs
    $ExitCode = $LASTEXITCODE
    if (Test-Path -LiteralPath $Report) {
        Copy-Item -LiteralPath $Report -Destination (Join-Path $ReportDir "brain-$Scope-latest.json") -Force
    }
} finally {
    Remove-BrainCheckClone -Path $RunDir | Out-Null
}
Write-Host "Report: $Report"
Write-Host "Exit: $ExitCode (0=passed, 1=failed, 2=unmeasured). Quick is NOT semantic acceptance."
$global:LASTEXITCODE = $ExitCode
