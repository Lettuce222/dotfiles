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
# Read the public Atom feed instead of the REST API: unauthenticated API calls
# share a 60/hour per-IP limit. The feed lists published releases only (no
# drafts) but does not mark previews, so pick the highest tag. A stable tag
# wins over previews of the same version.
$feedUrl = 'https://github.com/Lettuce222/lazygtd/releases.atom'
$tagPrefix = 'https://github.com/Lettuce222/lazygtd/releases/tag/'
$tagPattern = '^v(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})(?:-preview\.(0|[1-9][0-9]{0,8}))?$'

function Get-LatestTag([string] $Path) {
    $settings = [Xml.XmlReaderSettings]::new()
    # The feed never needs a DTD; refusing one rules out entity expansion.
    $settings.DtdProcessing = [Xml.DtdProcessing]::Prohibit
    $settings.XmlResolver = $null
    $stream = [IO.File]::OpenRead($Path)
    try {
        $reader = [Xml.XmlReader]::Create($stream, $settings)
        try {
            $document = [Xml.XmlDocument]::new()
            $document.XmlResolver = $null
            $document.Load($reader)
        } finally { $reader.Dispose() }
    } finally { $stream.Dispose() }
    $namespaces = [Xml.XmlNamespaceManager]::new($document.NameTable)
    $namespaces.AddNamespace('atom', 'http://www.w3.org/2005/Atom')
    if (-not $document.SelectSingleNode('/atom:feed', $namespaces)) {
        throw 'unexpected release feed'
    }
    $best = $null
    $bestVersion = [version]'0.0.0.0'
    foreach ($link in $document.SelectNodes('/atom:feed/atom:entry/atom:link', $namespaces)) {
        $rel = $link.GetAttribute('rel')
        $href = $link.GetAttribute('href')
        if (($rel -and $rel -cne 'alternate') -or -not $href.StartsWith($tagPrefix, [StringComparison]::Ordinal)) {
            continue
        }
        $candidate = $href.Substring($tagPrefix.Length)
        if ($candidate -cnotmatch $tagPattern) {
            continue
        }
        $revision = if ($Matches[4]) { [int]$Matches[4] } else { [int]::MaxValue }
        $version = [version]::new([int]$Matches[1], [int]$Matches[2], [int]$Matches[3], $revision)
        if (-not $best -or $version -gt $bestVersion) {
            $best = $candidate
            $bestVersion = $version
        }
    }
    if (-not $best) {
        throw 'no published lazygtd release'
    }
    return $best
}

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
$feed = Join-Path $scratch 'releases.atom'
try {
    & $curl.Source -q --proto '=https' --fail --silent --show-error `
        --connect-timeout 8 --max-time 30 --max-filesize 10000000 `
        --header 'Accept: application/atom+xml' --output $feed $feedUrl
    if ($LASTEXITCODE -ne 0) {
        throw 'lazygtd: release feed unavailable; existing install unchanged'
    }
    try {
        $tag = Get-LatestTag $feed
    } catch {
        throw "lazygtd: could not find the latest published release ($($_.Exception.Message)); existing install unchanged"
    }
    $asset = "lazygtd-$tag-$platform.zip"
    $download = "https://github.com/Lettuce222/lazygtd/releases/download/$tag"

    Get-ReleaseFile 'SHA256SUMS' $sums
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
    foreach ($file in @($feed, $archive, $sums, $executable, $backup)) {
        if ([IO.File]::Exists($file)) { [IO.File]::Delete($file) }
    }
    [IO.Directory]::Delete($scratch)
}
