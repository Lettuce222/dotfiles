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
        if (output < 0 || output + 1 >= args.Length) return 31;
        string url = args[args.Length - 1];
        File.AppendAllText(Environment.GetEnvironmentVariable("LAZY_TEST_CALLS"), url + "\n");
        string name = new Uri(url).Segments[new Uri(url).Segments.Length - 1];
        string path = Path.Combine(Environment.GetEnvironmentVariable("LAZY_TEST_FILES"), name);
        if (!File.Exists(path)) return 22;
        File.Copy(path, args[output + 1], true);
        return 0;
    }
}
"@
    $tag = ((Get-Content -LiteralPath (Join-Path $repo 'tools\lazygtd-release.lock') -TotalCount 1) -split ' ')[0]
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
    $digest = (Get-FileHash -LiteralPath $sums -Algorithm SHA256).Hash.ToLowerInvariant()
    $lock = Join-Path $work 'lazygtd-release.lock'
    [IO.File]::WriteAllText($lock, "$tag $digest`n")
    $env:LOCALAPPDATA = Join-Path $work 'local-app-data'
    $env:LAZY_TEST_FILES = $files
    $env:LAZY_TEST_CALLS = Join-Path $work 'calls'
    $env:PATH = "$work;$env:PATH"
    Copy-Item -LiteralPath (Join-Path $repo 'tools\install-lazygtd.ps1') -Destination $work
    $script = Join-Path $work 'install-lazygtd.ps1'
    $exe = Join-Path $env:LOCALAPPDATA 'Programs\lazygtd\lazygtd.exe'

    if ((& $script) -notmatch '^lazygtd: installed ') { throw 'expected first install' }
    if ((& $exe --version) -cne "lazygtd $version") { throw 'unexpected installed binary version' }
    if ((& $script) -notmatch '^lazygtd: .+ already verified ') { throw 'expected repeat install to be idempotent' }
    $original = (Get-FileHash -LiteralPath $exe).Hash
    [IO.File]::AppendAllText($sums, "# changed`n")
    try {
        & $script
        throw 'unexpected success with modified manifest'
    } catch {
        if ($_.Exception.Message -notmatch 'does not match the pinned release') { throw }
    }
    if ((Get-FileHash -LiteralPath $exe).Hash -cne $original) { throw 'existing binary changed' }
    $urls = @(Get-Content -LiteralPath $env:LAZY_TEST_CALLS)
    $prefix = "https://github.com/Lettuce222/lazygtd/releases/download/$tag"
    $expected = @("$prefix/SHA256SUMS","$prefix/$asset","$prefix/SHA256SUMS","$prefix/$asset","$prefix/SHA256SUMS")
    if (($urls -join '|') -cne ($expected -join '|')) { throw 'unexpected download URLs' }
    Write-Output 'Native Windows install + repeated install + manifest tampering checks passed.'
} finally {
    foreach ($name in $oldEnv.Keys) { [Environment]::SetEnvironmentVariable($name, $oldEnv[$name], 'Process') }
    $resolved = [IO.Path]::GetFullPath($work)
    if ([IO.Directory]::Exists($resolved) -and [IO.Path]::GetDirectoryName($resolved) -ceq $parent) {
        [IO.Directory]::Delete($resolved, $true)
    }
}
