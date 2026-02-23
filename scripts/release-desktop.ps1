param(
  [ValidateSet("patch", "minor", "major")]
  [string]$Bump = "patch",
  [string]$Version,
  [string]$Remote = "origin",
  [string]$Branch = "main",
  [string]$TagPrefix = "desktop-v"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Exec {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Command
  )
  Write-Host ">> $Command" -ForegroundColor DarkCyan
  Invoke-Expression $Command
}

function Parse-Version {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Raw
  )
  if ($Raw -notmatch '^(?<major>\d+)\.(?<minor>\d+)\.(?<patch>\d+)$') {
    throw "Unsupported version format: $Raw . Expected: x.y.z"
  }
  return @{
    Major = [int]$Matches.major
    Minor = [int]$Matches.minor
    Patch = [int]$Matches.patch
  }
}

function Next-Version {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Current,
    [Parameter(Mandatory = $true)]
    [string]$Level
  )
  $parts = Parse-Version -Raw $Current
  if ($Level -eq "major") {
    return "{0}.0.0" -f ($parts.Major + 1)
  }
  if ($Level -eq "minor") {
    return "{0}.{1}.0" -f $parts.Major, ($parts.Minor + 1)
  }
  return "{0}.{1}.{2}" -f $parts.Major, $parts.Minor, ($parts.Patch + 1)
}

if (-not (Test-Path ".git")) {
  throw "Current directory is not a git repository."
}
if (-not (Test-Path "desktop/package.json")) {
  throw "desktop/package.json not found. Please run this from repository root."
}

$dirty = git status --porcelain
if ($dirty) {
  throw "Working tree is not clean. Commit or stash changes before running release."
}

$currentBranch = git rev-parse --abbrev-ref HEAD
if ($currentBranch -ne $Branch) {
  throw "Current branch is '$currentBranch'. Please switch to '$Branch' first."
}

$pkg = Get-Content "desktop/package.json" -Raw | ConvertFrom-Json
$currentVersion = [string]$pkg.version
if ([string]::IsNullOrWhiteSpace($currentVersion)) {
  throw "desktop/package.json version is empty."
}

$targetVersion = if ([string]::IsNullOrWhiteSpace($Version)) {
  Next-Version -Current $currentVersion -Level $Bump
} else {
  Parse-Version -Raw $Version | Out-Null
  $Version
}

if ($targetVersion -eq $currentVersion) {
  throw "Target version equals current version ($currentVersion)."
}

$tagName = "$TagPrefix$targetVersion"

$localTag = git tag --list $tagName
if ($localTag) {
  throw "Local tag already exists: $tagName"
}

$remoteTag = git ls-remote --tags $Remote $tagName
if ($remoteTag) {
  throw "Remote tag already exists: $tagName"
}

Exec "npm --prefix desktop version $targetVersion --no-git-tag-version"
Exec "git add desktop/package.json desktop/package-lock.json"
Exec "git commit -m ""chore(release): bump desktop to $targetVersion"""
Exec "git push $Remote $Branch"
Exec "git tag $tagName"
Exec "git push $Remote $tagName"

$remoteUrl = git remote get-url $Remote
$repoPath = ""
if ($remoteUrl -match 'github\.com[:/](?<repo>[^/]+/[^/.]+)(?:\.git)?$') {
  $repoPath = $Matches.repo
}

Write-Host ""
Write-Host "Release triggered successfully." -ForegroundColor Green
Write-Host "Version: $targetVersion"
Write-Host "Tag: $tagName"
if ($repoPath) {
  Write-Host "Actions: https://github.com/$repoPath/actions"
  Write-Host "Releases: https://github.com/$repoPath/releases"
}
