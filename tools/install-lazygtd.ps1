# Native Windows counterpart to install-lazygtd.sh. Does not edit PATH.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'

$arch = $env:PROCESSOR_ARCHITEW6432
if (-not $arch) { $arch = $env:PROCESSOR_ARCHITECTURE }
$platform = switch ($arch) {
    AMD64 { 'windows-x86_64' }
    ARM64 { 'windows-arm64' }
    default { throw "lazygtd: no Windows release asset for $arch" }
}
if (-not $env:LOCALAPPDATA -or $env:LOCALAPPDATA -notmatch '^[A-Za-z]:\\') {
    throw 'lazygtd: LOCALAPPDATA must identify an absolute directory'
}
$curl = Get-Command -Name curl.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1
$directory = Join-Path $env:LOCALAPPDATA 'Programs\lazygtd'
$destination = Join-Path $directory 'lazygtd.exe'
# Include published previews. A stable tag wins over previews of the same version.
$api = 'https://api.github.com/repos/Lettuce222/lazygtd/releases'
$tagPattern = '^v(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})(?:-preview\.(0|[1-9][0-9]{0,8}))?$'
$best = $null
$bestVersion = [version]'0.0.0.0'
for ($page = 1; $page -le 20; $page++) {
    $json = (& $curl.Source -q --proto '=https' --fail --silent --show-error `
        --connect-timeout 8 --max-time 30 --max-filesize 10000000 `
        --header 'Accept: application/vnd.github+json' "${api}?per_page=100&page=$page") -join "`n"
    if ($LASTEXITCODE -ne 0 -or -not $json.TrimStart().StartsWith('[')) {
        throw 'lazygtd: release metadata unavailable; existing install unchanged'
    }
    $rows = @((ConvertFrom-Json -InputObject $json) | ForEach-Object { $_ })
    foreach ($row in $rows) {
        if ($row.draft -ne $false -or -not $row.published_at -or $row.tag_name -cnotmatch $tagPattern) {
            continue
        }
        $revision = if ($Matches[4]) { [int]$Matches[4] } else { [int]::MaxValue }
        $version = [version]::new([int]$Matches[1], [int]$Matches[2], [int]$Matches[3], $revision)
        if (-not $best -or $version -gt $bestVersion) {
            $best = $row
            $bestVersion = $version
        }
    }
    if ($rows.Count -lt 100) { break }
}
if ($page -gt 20 -or -not $best) {
    throw 'lazygtd: could not find the latest published release; existing install unchanged'
}
$manifests = @($best.assets | Where-Object { $_.name -ceq 'SHA256SUMS' })
if ($manifests.Count -ne 1 -or $manifests[0].state -cne 'uploaded' -or
    $manifests[0].digest -cnotmatch '^sha256:([0-9a-f]{64})$') {
    throw 'lazygtd: latest release has no verifiable SHA256SUMS; existing install unchanged'
}
$sumsDigest = $Matches[1]
$tag = $best.tag_name
$asset = "lazygtd-$tag-$platform.zip"
$download = "https://github.com/Lettuce222/lazygtd/releases/download/$tag"

function Confirm-PlainPath([string] $Path, [bool] $Directory) {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if ($item -and ($item.PSIsContainer -ne $Directory -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint))) {
        throw "lazygtd: $Path has an unexpected file type; left it alone"
    }
}

function Get-ReleaseFile([string] $Name, [string] $Target) {
    & $curl.Source -q --proto '=https' --proto-redir '=https' --location --fail --silent --show-error `
        --connect-timeout 8 --max-time 120 --output $Target "$download/$Name"
    if ($LASTEXITCODE -ne 0) {
        throw "lazygtd: $Name unavailable for $tag; existing install unchanged"
    }
}

function Get-Digest([string] $Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

Confirm-PlainPath $directory $true
Confirm-PlainPath $destination $false
[void][IO.Directory]::CreateDirectory($directory)
$scratch = Join-Path $directory ('.install-' + [Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($scratch)
$archive = Join-Path $scratch 'release.zip'
$sums = Join-Path $scratch 'SHA256SUMS'
$executable = Join-Path $scratch 'lazygtd.exe'
$backup = Join-Path $scratch 'previous.exe'
try {
    Get-ReleaseFile 'SHA256SUMS' $sums
    if ((Get-Digest $sums) -cne $sumsDigest) {
        throw 'lazygtd: checksum list digest does not match GitHub release metadata; existing install unchanged'
    }
    $hashes = @(
        foreach ($line in Get-Content -LiteralPath $sums -Encoding UTF8) {
            if ($line -cmatch ('^([A-Fa-f0-9]{64})\s+\*?' + [regex]::Escape($asset) + '$')) {
                $Matches[1].ToLowerInvariant()
            } elseif ($line -cmatch ('\s+\*?' + [regex]::Escape($asset) + '(\s|$)')) {
                throw "lazygtd: checksum list has invalid entry for $asset"
            }
        }
    )
    if ($hashes.Count -ne 1) {
        throw "lazygtd: checksum list has no unique valid entry for $asset"
    }

    Get-ReleaseFile $asset $archive
    if ((Get-Digest $archive) -cne $hashes[0]) {
        throw "lazygtd: checksum mismatch for $asset; existing install unchanged"
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($archive)
    try {
        $seen = @{}
        $allowed = @('lazygtd.exe', 'LICENSE', 'THIRD_PARTY_NOTICES.txt')
        foreach ($entry in $zip.Entries) {
            if ($entry.FullName -cnotin $allowed -or $seen.ContainsKey($entry.FullName)) {
                throw "lazygtd: unexpected contents in $asset"
            }
            $seen[$entry.FullName] = $entry
        }
        $binaryEntry = $seen['lazygtd.exe']
        if (-not $binaryEntry -or $binaryEntry.Length -le 0 -or $binaryEntry.Length -gt 104857600) {
            throw "lazygtd: $asset has no valid binary"
        }
        $inputStream = $binaryEntry.Open()
        try {
            $outputStream = [IO.File]::Open($executable, [IO.FileMode]::CreateNew)
            try { $inputStream.CopyTo($outputStream) } finally { $outputStream.Dispose() }
        } finally { $inputStream.Dispose() }
    } finally { $zip.Dispose() }

    $version = (& $executable --version) -join "`n"
    if ($LASTEXITCODE -ne 0 -or $version -cne ('lazygtd ' + $tag.Substring(1))) {
        throw 'lazygtd: staged binary did not report the expected version'
    }

    Confirm-PlainPath $destination $false
    if ([IO.File]::Exists($destination)) {
        if ((Get-Digest $executable) -ceq (Get-Digest $destination)) {
            Write-Output "lazygtd: $tag already verified at $destination"
            return
        }
        [IO.File]::Replace($executable, $destination, $backup)
    } else {
        [IO.File]::Move($executable, $destination)
    }
    Write-Output "lazygtd: installed $tag to $destination"
} finally {
    foreach ($file in @($archive, $sums, $executable, $backup)) {
        if ([IO.File]::Exists($file)) { [IO.File]::Delete($file) }
    }
    [IO.Directory]::Delete($scratch)
}
