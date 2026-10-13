<#
.SYNOPSIS
  tools/claude/agents/*.md ajan dosyalarini projenin .claude/agents/ klasorune kurar.

.DESCRIPTION
  Depo kokunu betigin konumundan bulur; kullaniciya ozel sabit yol kullanmaz.
  Tekrar calistirilabilir: ayni dosya "guncel" sayilir, farkli dosya once
  .claude/yedek/agents-<zaman>/ altina yedeklenir. .claude/ Git disinda kalir.
  Kisisel settings.json, giris bilgisi, anahtar, hafiza veya gozlem gunlugune dokunmaz.

.PARAMETER WhatIf
  Hicbir dosya yazmadan ne yapilacagini gosterir.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\claude\kur-ajanlar.ps1
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param()

$ErrorActionPreference = 'Stop'

$kaynak = Join-Path $PSScriptRoot 'agents'
$kok    = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$hedef  = Join-Path $kok '.claude\agents'

if (-not (Test-Path -LiteralPath (Join-Path $kok 'AGENTS.md'))) {
    throw "Jarvis depo kokunde degil gibi gorunuyor (AGENTS.md yok): $kok"
}
$dosyalar = @(Get-ChildItem -LiteralPath $kaynak -Filter '*.md' -File -ErrorAction SilentlyContinue)
if ($dosyalar.Count -eq 0) { throw "Kurulacak ajan dosyasi yok: $kaynak" }

# Get-FileHash -WhatIf altinda deger donmuyor; .NET ile hesaplanir.
# Claude Code CRLF basliklu (---\r\n) ajan dosyalarini yuklemez; kaynak ne olursa olsun LF kurulur.
# Bastaki UTF-8 BOM da atilir (ayni sekilde basligi bozar).
function Get-LfBytes([string]$yol) {
    $b = [System.IO.File]::ReadAllBytes($yol)
    $o = New-Object System.Collections.Generic.List[byte]
    $bas = 0
    if ($b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF) { $bas = 3 }
    for ($i = $bas; $i -lt $b.Length; $i++) {
        if ($b[$i] -eq 13 -and ($i + 1) -lt $b.Length -and $b[$i + 1] -eq 10) { continue }
        $o.Add($b[$i])
    }
    return ,$o.ToArray()
}

function Get-Sha256([byte[]]$bayt) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($sha.ComputeHash($bayt)) }
    finally { $sha.Dispose() }
}

$yedekKlasoru = $null
$kurulan = 0; $guncel = 0; $yedeklenen = 0; $planKur = 0; $planYedek = 0

foreach ($dosya in $dosyalar) {
    # Yalniz beklenen bicimdeki ajanlar: ilk satir '---' ve name alani dosya adiyla ayni olmali.
    # name: yalniz ilk '---' ile ikinci '---' arasindaki baslikta aranir.
    $ilk = @(Get-Content -LiteralPath $dosya.FullName -Encoding UTF8)
    $ad  = [System.IO.Path]::GetFileNameWithoutExtension($dosya.Name)
    $son = -1
    for ($i = 1; $i -lt $ilk.Count; $i++) { if ($ilk[$i].TrimEnd() -eq '---') { $son = $i; break } }
    $baslik = @()
    if ($ilk.Count -gt 0 -and $ilk[0].TrimEnd() -eq '---' -and $son -gt 1) { $baslik = @($ilk[1..($son - 1)]) }
    if (@($baslik -match "^name:\s*$([regex]::Escape($ad))\s*$").Count -eq 0) {
        Write-Warning "$($dosya.Name) atlandi: baslik '---' ile baslamiyor/kapanmiyor veya name: $ad degil."
        continue
    }

    $hedefDosya = Join-Path $hedef $dosya.Name
    if (Test-Path -LiteralPath $hedefDosya) {
        $a = Get-Sha256 (Get-LfBytes $dosya.FullName)
        $b = Get-Sha256 ([System.IO.File]::ReadAllBytes($hedefDosya))
        if ($a -eq $b) {
            Write-Host "Guncel: $($dosya.Name)"
            $guncel++
            continue
        }
        if (-not $yedekKlasoru) {
            $yedekKlasoru = Join-Path $kok ('.claude\yedek\agents-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
        }
        $planYedek++
        if ($PSCmdlet.ShouldProcess($hedefDosya, "yedekle -> $yedekKlasoru")) {
            New-Item -ItemType Directory -Force -Path $yedekKlasoru | Out-Null
            Copy-Item -LiteralPath $hedefDosya -Destination (Join-Path $yedekKlasoru $dosya.Name)
            $yedeklenen++
        }
    }
    $planKur++
    if ($PSCmdlet.ShouldProcess($hedefDosya, 'kur')) {
        New-Item -ItemType Directory -Force -Path $hedef | Out-Null
        [System.IO.File]::WriteAllBytes($hedefDosya, (Get-LfBytes $dosya.FullName))
        Write-Host "Kuruldu: $($dosya.Name)"
        $kurulan++
    }
}

if ($WhatIfPreference) {
    Write-Host ("Plan (hicbir sey yazilmadi): kurulacak={0} yedeklenecek={1} guncel={2}" -f $planKur, $planYedek, $guncel)
} else {
    Write-Host ("Ozet: kurulan={0} guncel={1} yedeklenen={2}" -f $kurulan, $guncel, $yedeklenen)
}
if ($yedekKlasoru -and $yedeklenen -gt 0) { Write-Host "Yedek: $yedekKlasoru" }
Write-Host 'Claude Code aciksa oturumu yeniden baslat (ajan listesi acilista okunur).'
