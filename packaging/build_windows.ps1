# Forensic Vision Pro 1.4 - build completa e autonoma per Windows.
# Avvio: doppio clic su build_windows.bat nella cartella principale del progetto.
#
# Verifica e, se manca, installa automaticamente tutto ciò che serve:
#   Python 3.12 (winget o installer ufficiale python.org con firma Authenticode verificata)
#   dipendenze Python (versioni fissate in requirements.lock.txt)
#   ExifTool, FFmpeg/FFprobe (bin\tools.json, archivi verificati con SHA-256)
#   Inno Setup 6 per l'installer (winget o installer ufficiale con firma verificata; facoltativo)
# Poi esegue i test, crea l'eseguibile, verifica l'eseguibile finito con --selfcheck e produce
# versione portable, installer e SHA256SUMS.txt.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root
$Version = "1.4.0"
New-Item -ItemType Directory -Force build | Out-Null
Start-Transcript -Path "build\build.log" -Force | Out-Null

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "ATTENZIONE: $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "`nERRORE: $msg" -ForegroundColor Red; Write-Host "Registro completo: build\build.log"; Stop-Transcript | Out-Null; exit 1 }
function Run($exe, [string[]]$argsList) {
    # Out-Host porta l'output dei programmi esterni anche nel registro build\build.log (Start-Transcript)
    & $exe @argsList | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail "comando non riuscito: $exe $($argsList -join ' ') (codice $LASTEXITCODE)" }
}
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
}
function Has-Winget { return [bool](Get-Command winget -ErrorAction SilentlyContinue) }
function Download-Signed($url, $dest, $signerPattern) {
    Write-Host "Download $url"
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    $sig = Get-AuthenticodeSignature $dest
    if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notmatch $signerPattern) {
        Remove-Item $dest -Force
        throw "firma digitale non valida per $url (stato $($sig.Status), firmatario $($sig.SignerCertificate.Subject))"
    }
    Write-Host "Firma verificata: $($sig.SignerCertificate.Subject)"
}

function Find-Python {
    foreach ($cand in @(@("py", "-3.12"), @("py", "-3"), @("python"))) {
        $cmd = Get-Command $cand[0] -ErrorAction SilentlyContinue
        if (-not $cmd -or $cmd.Source -like "*WindowsApps*") { continue }
        $a = @(); if ($cand.Count -gt 1) { $a = $cand[1..($cand.Count - 1)] }
        $exe = & $cand[0] @a -c "import sys; print(sys.executable if sys.version_info >= (3,10) and sys.maxsize > 2**32 else '')" 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) { return $exe.Trim() }
    }
    $local = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
    if (Test-Path $local) { return $local }
    return $null
}

Step "1/9 Python"
$py = Find-Python
if (-not $py) {
    Write-Host "Python 3.10+ a 64 bit non trovato: installazione automatica di Python 3.12."
    if (Has-Winget) {
        & winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
        Refresh-Path
        $py = Find-Python
    }
    if (-not $py) {
        $inst = Join-Path $env:TEMP "python-3.12.10-amd64.exe"
        try { Download-Signed "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" $inst "Python Software Foundation" }
        catch { Fail "download di Python non riuscito: $_" }
        $p = Start-Process $inst -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0" -Wait -PassThru
        if ($p.ExitCode -ne 0) { Fail "installazione di Python non riuscita (codice $($p.ExitCode))" }
        Refresh-Path
        $py = Find-Python
    }
    if (-not $py) { Fail "Python non disponibile dopo l'installazione automatica." }
}
Write-Host "Python: $py ($(& $py --version))"

Step "2/9 Ambiente virtuale e dipendenze Python"
if (-not (Test-Path ".venv\Scripts\python.exe")) { Run $py @("-m", "venv", ".venv") }
$vpy = Join-Path $Root ".venv\Scripts\python.exe"
Run $vpy @("-m", "pip", "install", "--upgrade", "pip", "--disable-pip-version-check", "-q")
& $vpy -m pip install -r requirements.lock.txt --disable-pip-version-check -q | Out-Host
if ($LASTEXITCODE -ne 0) {
    Warn "versioni fissate non installabili su questo Python: uso requirements.txt (versioni compatibili più recenti)."
    Run $vpy @("-m", "pip", "install", "-r", "requirements.txt", "--disable-pip-version-check", "-q")
}
& $vpy -m pip freeze --disable-pip-version-check | Out-File -Encoding utf8 "build\pip-freeze.txt"
Write-Host "Pacchetti installati registrati in build\pip-freeze.txt"

Step "3/9 Strumenti esterni (bin\tools.json)"
Run $vpy @("tools\fetch_tools.py")
# Modelli della stima della posa (Persone e movimento): se l'impronta non e' ancora fissata in bin\tools.json la si
# fissa scaricando i file da OpenMMLab e dal mirror Hugging Face e accettandoli solo se i due SHA-256 coincidono.
$tj = Get-Content "bin\tools.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$unpinned = @($tj.tools | Where-Object { $_.group -eq "pose-models" -and -not $_.sha256 })
if ($unpinned.Count -gt 0) {
    Write-Host "Modelli della posa senza impronta: confronto tra le due sorgenti (fetch_tools.py --pin pose-models)."
    & $vpy tools\fetch_tools.py --pin pose-models | Out-Host
    if ($LASTEXITCODE -ne 0) { Warn "impronte dei modelli della posa non fissate (sorgenti diverse o non raggiungibili)." }
    else { Write-Host "Impronte scritte in bin\tools.json: conservare e committare il file (documenta i modelli usati)." }
}
& $vpy tools\fetch_tools.py --only pose-models | Out-Host
if ($LASTEXITCODE -ne 0) { Warn "modelli della posa non installati: Persone e movimento non sara' disponibile nell'eseguibile." }

# Sports2D e Pose2Sim originali in un ambiente separato (facoltativo; FVP_SKIP_SPORTS2D=1 per saltarlo)
if ($env:FVP_SKIP_SPORTS2D -ne "1") {
    Write-Host "`nSports2D e Pose2Sim originali: ambiente separato in $env:USERPROFILE\ForensicVisionPro\sports2d-env"
    & $py tools\install_sports2d.py --target "$env:USERPROFILE\ForensicVisionPro\sports2d-env" | Out-Host
    if ($LASTEXITCODE -ne 0) { Warn "Sports2D non installato: il modulo dei programmi originali restera' non disponibile." }
}

Step "4/9 Controllo del sistema (sorgenti)"
$env:PYTHONPATH = "src"
$env:FVP_HOME = Join-Path $Root "build\fvp_home"
Run $vpy @("-m", "fvp", "--selfcheck", "build\selfcheck-src.json")

Step "5/9 Test automatici"
$env:QT_QPA_PLATFORM = "offscreen"
& $vpy -m pytest -q -p no:cacheprovider -rfE --tb=short --junitxml build\test-results.xml | Tee-Object -FilePath "build\test-output.txt" | Out-Host
if ($LASTEXITCODE -ne 0) {
    Write-Host "`nTest non superati: il dettaglio completo è in build\test-output.txt" -ForegroundColor Red
    Fail "alcuni test automatici non sono stati superati."
}
Remove-Item Env:\QT_QPA_PLATFORM

Step "6/9 Eseguibile (PyInstaller)"
# Licenze di tutti i componenti inclusi: la build si ferma se un componente di runtime non ne ha
Run $vpy @("tools\collect_licenses.py", "build\third_party_licenses")
Run $vpy @("-m", "PyInstaller", "packaging\fvp.spec", "--noconfirm", "--distpath", "dist", "--workpath", "build\pyi")
$exe = "dist\ForensicVisionPro\ForensicVisionPro.exe"
if (-not (Test-Path $exe)) { Fail "PyInstaller non ha prodotto $exe" }
# Note e licenze anche accanto all'eseguibile (visibili nella versione portable e nell'installazione)
Copy-Item "THIRD_PARTY_NOTICES.md" "dist\ForensicVisionPro\" -Force
Copy-Item "build\third_party_licenses" "dist\ForensicVisionPro\licenses" -Recurse -Force

Step "7/9 Verifica dell'eseguibile finito (--selfcheck)"
$report = Join-Path $Root "build\selfcheck-exe.json"
$p = Start-Process $exe -ArgumentList "--selfcheck `"$report`"" -Wait -PassThru
$r = Get-Content $report -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($c in $r.checks) {
    $color = if ($c.ok) { "Green" } elseif ($c.level -eq "essenziale") { "Red" } else { "Yellow" }
    Write-Host ("[{0}] {1}: {2} {3}" -f ($(if ($c.ok) { "OK" } else { "KO" })), $c.name, $c.detail, $c.version) -ForegroundColor $color
}
if (-not $r.ok -or $p.ExitCode -ne 0) { Fail "l'eseguibile finito non supera il controllo di sistema (vedi sopra)." }
Remove-Item Env:\PYTHONPATH, Env:\FVP_HOME

Step "8/9 Versione portable"
$zip = "dist\ForensicVisionPro-$Version-portable.zip"
"" | Out-File -Encoding ascii "dist\ForensicVisionPro\portable.flag"
Compress-Archive -Path "dist\ForensicVisionPro\*" -DestinationPath $zip -Force
Remove-Item "dist\ForensicVisionPro\portable.flag"

Step "9/9 Installer (Inno Setup)"
function Find-Iscc {
    $c = (Get-Command iscc -ErrorAction SilentlyContinue).Source
    if ($c) { return $c }
    foreach ($p in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
                     "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) { if (Test-Path $p) { return $p } }
    return $null
}
$iscc = Find-Iscc
if (-not $iscc) {
    Write-Host "Inno Setup non trovato: installazione automatica."
    if (Has-Winget) {
        & winget install -e --id JRSoftware.InnoSetup --silent --accept-package-agreements --accept-source-agreements
        $iscc = Find-Iscc
    }
    if (-not $iscc) {
        try {
            $inst = Join-Path $env:TEMP "innosetup.exe"
            Download-Signed "https://jrsoftware.org/download.php/is.exe" $inst "Jordan Russell|JRSoftware|Inno"
            $p = Start-Process $inst -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER" -Wait -PassThru
            $iscc = Find-Iscc
        } catch { Warn "installazione automatica di Inno Setup non riuscita: $_" }
    }
}
if ($iscc) {
    Run $iscc @("/Qp", "packaging\installer.iss")
} else {
    Warn "Inno Setup non disponibile: creati eseguibile e versione portable, senza installer."
}

Step "Risultato"
$out = Get-ChildItem dist -Recurse -Include *.exe, *.zip | Where-Object { $_.FullName -notlike "*\_internal\*" }
$lines = $out | ForEach-Object { "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.FullName.Substring($Root.Length + 1) }
$lines | Out-File -Encoding utf8 "dist\SHA256SUMS.txt"
$lines | ForEach-Object { Write-Host $_ }
Write-Host "`nBuild completata. Eseguibile: dist\ForensicVisionPro\ForensicVisionPro.exe" -ForegroundColor Green
Stop-Transcript | Out-Null
