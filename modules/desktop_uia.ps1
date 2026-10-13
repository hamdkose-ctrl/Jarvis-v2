# Long-lived worker: one JSON request per stdin line, one JSON reply per stdout line.
# User/model strings are data, never PowerShell source.
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
function Invoke-Request([string]$line) {
$attempted = $false
try {
    $request = $line | ConvertFrom-Json
    $hwnd = [IntPtr][long]$request.hwnd
    $root = [System.Windows.Automation.AutomationElement]::FromHandle($hwnd)
    if ($null -eq $root) { throw 'Hedef pencere artık açık değil.' }
    $walker = [System.Windows.Automation.TreeWalker]::RawViewWalker
    $queue = New-Object 'System.Collections.Generic.Queue[System.Windows.Automation.AutomationElement]'
    $queue.Enqueue($root)
    $controls = New-Object System.Collections.ArrayList
    $elements = @{}
    $processes = @{}
    $scanned = 0
    while ($queue.Count -gt 0 -and $scanned -lt 500) {
        $element = $queue.Dequeue()
        $scanned++
        try {
            $current = $element.Current
            $expressionEvidence = $current.AutomationId -eq 'CalculatorExpression' -and
                $current.ControlType -eq [System.Windows.Automation.ControlType]::Text -and
                [System.Diagnostics.Process]::GetProcessById($current.ProcessId).ProcessName.ToLowerInvariant() -in @('calc','calculator','calculatorapp')
            if (-not $current.IsOffscreen -or $expressionEvidence) {
                $id = $element.GetRuntimeId() -join '-'
                $patterns = @()
                $value = ''
                $p = $null
                if ($element.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$p)) { $patterns += 'invoke' }
                $p = $null
                if ($element.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$p)) {
                    if (-not $current.IsPassword) { $value = ([string]$p.Current.Value) }
                    if (-not $p.Current.IsReadOnly) { $patterns += 'fill' }
                }
                $p = $null
                $selected = $null
                if ($element.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$p)) {
                    $patterns += 'select'
                    $selected = $p.Current.IsSelected
                }
                $p = $null
                if ($element.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern, [ref]$p)) {
                    $patterns += 'toggle'
                    $value = [string]$p.Current.ToggleState
                }
                if ($value.Length -gt 6000) { $value = $value.Substring(0,6000) }
                $name = [string]$current.Name
                if ($name.Length -gt 500) { $name = $name.Substring(0,500) }
                if ($current.IsOffscreen -or $expressionEvidence) { $patterns = @() }
                $row = @{id=$id;name=$name;type=$current.ControlType.ProgrammaticName;automation_id=$current.AutomationId;offscreen=$current.IsOffscreen;
                    process_id=$current.ProcessId;enabled=$current.IsEnabled;password=$current.IsPassword;value=$value;selected=$selected;patterns=@($patterns)}
                if (-not $processes.ContainsKey([int]$current.ProcessId)) {
                    $processes[[int]$current.ProcessId] = [System.Diagnostics.Process]::GetProcessById($current.ProcessId).ProcessName.ToLowerInvariant()
                }
                [void]$controls.Add($row)
                if (-not $current.IsOffscreen -and -not $expressionEvidence) { $elements[$id] = $element }
            }
            $child = $walker.GetFirstChild($element)
            while ($null -ne $child -and ($queue.Count + $scanned) -lt 500) {
                $queue.Enqueue($child)
                $child = $walker.GetNextSibling($child)
            }
        } catch [System.Windows.Automation.ElementNotAvailableException] { }
    }
    $appPid = [int]$root.Current.ProcessId
    $appName = [System.Diagnostics.Process]::GetProcessById($appPid).ProcessName.ToLowerInvariant()
    if ($appName -eq 'applicationframehost') {
        # A host name alone grants no permission. Resolve only Calculator controls
        # found beneath this exact HWND, owned by a real Calculator process.
        $calculatorPids = @($controls | Where-Object {
            $_.automation_id -eq 'CalculatorResults' -and
            $processes[[int]$_.process_id] -in @('calculatorapp','calculator','calc')
        } | ForEach-Object { [int]$_.process_id } | Select-Object -Unique)
        if ($calculatorPids.Count -eq 1) {
            $appPid = $calculatorPids[0]
            $appName = $processes[$appPid]
        } else {
            # Other hosted (UWP) apps: only when exactly one non-host process owns controls under this HWND.
            $hosted = @($processes.Keys | Where-Object { [int]$_ -ne $appPid -and $processes[$_] -ne 'applicationframehost' })
            if ($hosted.Count -eq 1) {
                $appPid = [int]$hosted[0]
                $appName = $processes[$appPid]
            }
        }
    }
    if ($request.op -eq 'observe') {
        [Console]::Out.WriteLine((@{ok=$true;pid=$root.Current.ProcessId;app=$appName;app_pid=$appPid;controls=@($controls.ToArray())} | ConvertTo-Json -Depth 8 -Compress))
        return
    }
    if ($request.op -notin @('invoke','fill','select','toggle')) { throw 'Bu masaüstü işlemi desteklenmiyor.' }
    if ($root.Current.ProcessId -ne [int]$request.pid) { throw 'Hedef pencerenin işlemi değişti.' }
    if ($appPid -ne [int]$request.app_pid -or $appName -cne [string]$request.app) { throw 'Hedef uygulama kimliği değişti.' }
    # UIA targets the validated element directly, without keyboard/mouse input.
    # A foreground-window switch does not change that target.
    $target = $elements[[string]$request.target.id]
    if ($null -eq $target) { throw 'Hedef kontrol bulunamadı.' }
    $row = @($controls | Where-Object { $_.id -eq $request.target.id })[0]
    if ($row.password -or -not $row.enabled) { throw 'Şifre alanı veya devre dışı kontrol kullanılamaz.' }
    foreach ($field in @('name','type','automation_id','value','selected','process_id')) {
        if ([string]$row[$field] -cne [string]$request.target.$field) { throw 'Hedef kontrol değişti; işlem gönderilmedi.' }
    }
    if ($request.op -notin $row.patterns) { throw 'Kontrol istenen işlemi desteklemiyor.' }
    # The element must belong to the selected window process, not an unrelated overlay.
    if ($target.Current.ProcessId -ne $appPid) { throw 'Hedef başka bir uygulamaya ait.' }
    $attempted = $true
    switch ($request.op) {
        'invoke' { $target.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke() }
        'fill' { $target.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue([string]$request.value) }
        'select' { $target.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select() }
        'toggle' { $target.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern).Toggle() }
    }
    [Console]::Out.WriteLine((@{ok=$true;sent=$true} | ConvertTo-Json -Compress))
} catch {
    [Console]::Out.WriteLine((@{ok=$false;sent=$attempted;message=$_.Exception.Message} | ConvertTo-Json -Compress))
}
}
while ($null -ne ($line = [Console]::In.ReadLine())) {
    if ($line.Trim().Length -eq 0) { continue }
    Invoke-Request $line
    [Console]::Out.Flush()
}
