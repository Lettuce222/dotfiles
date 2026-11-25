# Run with native Windows PowerShell 5.1. Fake curl never accesses the network.
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$parent = [IO.Path]::GetFullPath($env:TEMP)
$work = Join-Path $parent ('lazygtd-installer-test-' + [Guid]::NewGuid().ToString('N'))
$oldEnv = @{}
foreach ($name in @('PATH','LOCALAPPDATA','LAZY_TEST_FILES','LAZY_TEST_CALLS')) {
    $oldEnv[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    [void][IO.Directory]::CreateDirectory($work)
    $build = Join-Path $work 'build'
    [void][IO.Directory]::CreateDirectory($build)
    $files = Join-Path $work 'fixtures'
    [void][IO.Directory]::CreateDirectory($files)
    $fake = Join-Path $work 'curl.exe'
    Add-Type -OutputAssembly $fake -OutputType ConsoleApplication -TypeDefinition @"
using System;
using System.IO;
public static class FakeCurl {
    public static int Main(string[] args) {
        if (args[0] != "-q") return 30;
        int output = Array.IndexOf(args, "--output");
        string url = args[args.Length - 1];
        File.AppendAllText(Environment.GetEnvironmentVariable("LAZY_TEST_CALLS"), url + "\n");
        if (!url.StartsWith("https://github.com/Lettuce222/lazygtd/releases", StringComparison.Ordinal)) return 40;
        foreach (string arg in args) {
            if (arg.IndexOf("Authorization", StringComparison.OrdinalIgnoreCase) >= 0) return 41;
        }
        if (output < 0 || output + 1 >= args.Length) return 31;
        string name = new Uri(url).Segments[new Uri(url).Segments.Length - 1];
        string path = Path.Combine(Environment.GetEnvironmentVariable("LAZY_TEST_FILES"), name);
        if (!File.Exists(path)) return 22;
        File.Copy(path, args[output + 1], true);
        return 0;
    }
}
"@
    $tag = 'v0.1.0-preview.10'
    $version = $tag.Substring(1)
    $platform = switch ($env:PROCESSOR_ARCHITECTURE) {
        ARM64 { 'windows-arm64' }
        AMD64 { 'windows-x86_64' }
        default { throw 'run test under native PowerShell on x64 or ARM64' }
    }
    $asset = "lazygtd-$tag-$platform.zip"
    $archive = Join-Path $files $asset
    Add-Type -OutputAssembly (Join-Path $build 'lazygtd.exe') -OutputType ConsoleApplication -TypeDefinition @"
using System;
public static class FakeRelease {
    public static int Main(string[] args) {
        if (args.Length != 1 || args[0] != "--version") return 2;
        Console.WriteLine("lazygtd $version");
        return 0;
    }
}
"@
    [IO.File]::WriteAllText((Join-Path $build 'LICENSE'), 'Synthetic fixture')
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::CreateFromDirectory($build, $archive)
    $sha = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    $sums = Join-Path $files 'SHA256SUMS'
    [IO.File]::WriteAllText($sums, "$sha  $asset`n")
    $writeFeed = {
        param([string[]] $Tags, [string] $Header = '<?xml version="1.0" encoding="UTF-8"?>')
        $entries = foreach ($name in $Tags) {
            "<entry><id>tag:github.com,2008:Repository/1/$name</id>" +
            "<link rel=`"alternate`" type=`"text/html`" href=`"https://github.com/Lettuce222/lazygtd/releases/tag/$name`"/>" +
            "<title>lazygtd $name</title></entry>"
        }
        [IO.File]::WriteAllText((Join-Path $files 'releases.atom'),
            $Header + '<feed xmlns="http://www.w3.org/2005/Atom">' +
            '<link type="text/html" rel="alternate" href="https://github.com/Lettuce222/lazygtd/releases"/>' +
            ($entries -join '') + '</feed>')
    }
    # Feed order follows update time; the highest version must still win.
    & $writeFeed @('v0.1.0-preview.9', $tag, 'v0.0.9', 'latest', 'v9.0.0-rc.1')
    $env:LOCALAPPDATA = Join-Path $work 'local-app-data'
    $env:LAZY_TEST_FILES = $files
    $env:LAZY_TEST_CALLS = Join-Path $work 'calls'
    $env:PATH = "$work;$env:PATH"
    Copy-Item -LiteralPath (Join-Path $repo 'tools\install-lazygtd.ps1') -Destination $work
    $script = Join-Path $work 'install-lazygtd.ps1'
    $exe = Join-Path $env:LOCALAPPDATA 'Programs\lazygtd\lazygtd.exe'
    $expectFailure = {
        param([string] $Pattern)
        try {
            & $script
            throw "unexpected success; expected $Pattern"
        } catch {
            if ($_.Exception.Message -notmatch $Pattern) { throw }
        }
    }

    if ((& $script) -notmatch '^lazygtd: installed ') { throw 'expected first install' }
    if ((& $exe --version) -cne "lazygtd $version") { throw 'unexpected installed binary version' }
    if ((& $script) -notmatch '^lazygtd: .+ already verified ') { throw 'expected repeat install to be idempotent' }
    $original = (Get-FileHash -LiteralPath $exe).Hash
    $pristine = [IO.File]::ReadAllBytes($archive)
    [IO.File]::AppendAllText($archive, 'tampered')
    & $expectFailure 'checksum mismatch'
    [IO.File]::WriteAllBytes($archive, $pristine)
    $urls = @(Get-Content -LiteralPath $env:LAZY_TEST_CALLS)
    $prefix = "https://github.com/Lettuce222/lazygtd/releases/download/$tag"
    $feed = 'https://github.com/Lettuce222/lazygtd/releases.atom'
    $expected = @($feed,"$prefix/SHA256SUMS","$prefix/$asset",$feed,"$prefix/SHA256SUMS","$prefix/$asset",$feed,"$prefix/SHA256SUMS","$prefix/$asset")
    if (($urls -join '|') -cne ($expected -join '|')) { throw 'unexpected download URLs' }

    # A final release outranks its previews, and an incomplete latest release never falls back.
    & $writeFeed @('v0.1.0-preview.11', 'v0.1.0', $tag)
    & $expectFailure 'no unique valid entry for lazygtd-v0\.1\.0-windows'
    # Unreadable feeds and DTDs stop before any release download.
    [IO.File]::Delete($env:LAZY_TEST_CALLS)
    & $writeFeed @($tag) '<!DOCTYPE feed [<!ENTITY x "y">]>'
    & $expectFailure 'could not find the latest published release'
    foreach ($body in @('not xml', '<rss/>', '<feed xmlns="http://www.w3.org/2005/Atom"/>')) {
        [IO.File]::WriteAllText((Join-Path $files 'releases.atom'), $body)
        & $expectFailure 'could not find the latest published release'
    }
    [IO.File]::Delete((Join-Path $files 'releases.atom'))
    & $expectFailure 'release feed unavailable'
    if ((@(Get-Content -LiteralPath $env:LAZY_TEST_CALLS) | Sort-Object -Unique) -cne $feed) { throw 'feed failure downloaded a release file' }
    if ((Get-FileHash -LiteralPath $exe).Hash -cne $original) { throw 'existing binary changed' }
    Write-Output 'Native Windows install + repeated install + feed selection + tampering checks passed.'
} finally {
    foreach ($name in $oldEnv.Keys) { [Environment]::SetEnvironmentVariable($name, $oldEnv[$name], 'Process') }
    $resolved = [IO.Path]::GetFullPath($work)
    if ([IO.Directory]::Exists($resolved) -and [IO.Path]::GetDirectoryName($resolved) -ceq $parent) {
        [IO.Directory]::Delete($resolved, $true)
    }
}
