# -*- coding: utf-8 -*-
<#
.SYNOPSIS
  本地版本库：每个 release / beta 一个「双击就能跑」的目录，并留一条记录。

.DESCRIPTION
  根目录默认仓库上两级目录下的 `versions\`（仓外，绝不进发布快照），可用
  环境变量 `WF_VERSIONS_ROOT` 覆盖。布局：

    versions\
      releases\v1.0.5\        解压好的完整包（双击 MFAAvalonia.exe 就跑）
      betas\beta-<date>-<sha>\ 基于当前 main 的本地构建
      current\                junction -> 当前要用的版本
      _versions.json          每版一条记录
      _zips\                  add-release -KeepZip 时保留的原始 zip

.EXAMPLE
  pwsh tools/versions.ps1 list
  pwsh tools/versions.ps1 add-release v1.0.5 -KeepZip
  pwsh tools/versions.ps1 add-beta
  pwsh tools/versions.ps1 use v1.0.4
  pwsh tools/versions.ps1 prune -Keep 5            # 只列
  pwsh tools/versions.ps1 prune -Keep 5 -Force     # 真删（只删 release）
#>
param(
    [Parameter(Position = 0)][string]$Command = "list",
    [Parameter(Position = 1)][string]$Arg,
    [switch]$KeepZip,
    [int]$Keep = 5,
    [string]$Label,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VersionRoot = if ($env:WF_VERSIONS_ROOT) { $env:WF_VERSIONS_ROOT } else {
    Join-Path (Split-Path (Split-Path $RepoRoot -Parent) -Parent) "versions"
}
$GitHubRepo = if ($env:WF_GITHUB_REPO) { $env:WF_GITHUB_REPO } else { "ImaiAkira/wf-auto" }
$ManifestPath = Join-Path $VersionRoot "_versions.json"

function Initialize-Root {
    foreach ($d in @($VersionRoot, (Join-Path $VersionRoot "releases"), (Join-Path $VersionRoot "betas"), (Join-Path $VersionRoot "_zips"))) {
        if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
    }
}

function Read-Manifest {
    if (-not (Test-Path $ManifestPath)) { return [pscustomobject]@{ versions = @() } }
    $raw = Get-Content $ManifestPath -Raw -Encoding UTF8
    if (-not $raw.Trim()) { return [pscustomobject]@{ versions = @() } }
    try { return ($raw | ConvertFrom-Json) } catch { return [pscustomobject]@{ versions = @() } }
}

function Write-Manifest($manifest) {
    $json = $manifest | ConvertTo-Json -Depth 6
    Set-Content -Path $ManifestPath -Value $json -Encoding UTF8
}

function Get-SizeMb([string]$path) {
    if (-not (Test-Path $path)) { return 0 }
    $bytes = (Get-ChildItem $path -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
    if (-not $bytes) { return 0 }
    return [math]::Round($bytes / 1MB, 1)
}

function Upsert-Record($record) {
    $m = Read-Manifest
    $list = @()
    foreach ($v in @($m.versions)) { if ($v -and $v.id -ne $record.id) { $list += $v } }
    $list += [pscustomobject]$record
    Write-Manifest ([pscustomobject]@{ versions = $list })
}

function Find-VersionDir([string]$id) {
    foreach ($sub in @("releases", "betas")) {
        $p = Join-Path (Join-Path $VersionRoot $sub) $id
        if (Test-Path $p) { return $p }
    }
    return $null
}

function Set-CurrentJunction([string]$targetDir) {
    $link = Join-Path $VersionRoot "current"
    if (Test-Path $link) {
        # junction 用 rmdir 删（Remove-Item 在部分版本上会递归删内容）
        cmd /c rmdir "$link" | Out-Null
    }
    New-Item -ItemType Junction -Path $link -Target $targetDir | Out-Null
}

function Invoke-Robocopy([string]$src, [string]$dst, [string[]]$excludeDirs = @()) {
    $args = @($src, $dst, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP")
    if ($excludeDirs.Count -gt 0) { $args += "/XD"; $args += $excludeDirs }
    & robocopy @args | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy 失败（exit $LASTEXITCODE）：$src -> $dst" }
}

# ---------------------------------------------------------------- commands
function Cmd-List {
    Initialize-Root
    $m = Read-Manifest
    $rows = @()
    foreach ($v in @($m.versions)) {
        if (-not $v) { continue }
        $dir = Join-Path $VersionRoot $v.dir
        $exists = Test-Path $dir
        $rows += [pscustomobject]@{
            id      = $v.id
            type    = $v.type
            commit  = $v.commit
            date    = $v.date
            size_mb = $v.size_mb
            dir     = $(if ($exists) { "OK" } else { "缺失!" })
            notes   = $v.notes
        }
    }
    if ($rows.Count -eq 0) { Write-Host "本地版本库为空：$VersionRoot"; return }
    $rows | Sort-Object date -Descending | Format-Table -AutoSize | Out-String -Width 200 | Write-Host
    $cur = Join-Path $VersionRoot "current"
    if (Test-Path $cur) {
        $t = (Get-Item $cur).Target
        if ($t) { Write-Host ("current -> " + ($t -join ",")) }
    }
    Write-Host ("库根目录：" + $VersionRoot)
}

function Cmd-AddRelease {
    if (-not $Arg) { throw "用法：add-release <tag>，例如 add-release v1.0.5" }
    $tag = $Arg
    if ($tag -notmatch '^v') { $tag = "v$tag" }
    Initialize-Root
    $target = Join-Path (Join-Path $VersionRoot "releases") $tag
    if (Test-Path $target) { throw "已存在：$target（先手动删掉再重加）" }

    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("wf-ver-" + $tag)
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null

    Write-Host "下载 $tag 的 release 资产……"
    gh release download $tag --repo $GitHubRepo --pattern "wf-auto-win-x86_64-*.zip" --dir $tmp --clobber
    if ($LASTEXITCODE -ne 0) { throw "gh release download 失败" }
    $zip = Get-ChildItem $tmp -Filter *.zip | Select-Object -First 1
    if (-not $zip) { throw "没下到 zip" }
    $sha = (Get-FileHash $zip.FullName -Algorithm SHA256).Hash

    Write-Host ("解压 -> " + $target)
    Expand-Archive -Path $zip.FullName -DestinationPath $target -Force
    # 有的 zip 带一层顶层目录：只有一个子目录且没有文件时拍平
    $topFiles = @(Get-ChildItem $target -File)
    $topDirs = @(Get-ChildItem $target -Directory)
    if ($topFiles.Count -eq 0 -and $topDirs.Count -eq 1) {
        $inner = $topDirs[0].FullName
        foreach ($item in Get-ChildItem $inner) { Move-Item $item.FullName $target -Force }
        Remove-Item $inner -Recurse -Force
    }

    $commit = ""
    $remoteLine = (git -C $RepoRoot ls-remote origin ("refs/tags/" + $tag) 2>$null)
    if ($remoteLine) { $commit = ($remoteLine -split "\s+")[0].Substring(0, 7) }

    $zipNote = "未保留 zip"
    if ($KeepZip) {
        $zipDir = Join-Path $VersionRoot "_zips"
        Copy-Item $zip.FullName (Join-Path $zipDir $zip.Name) -Force
        $zipNote = "zip 已存 _zips\" + $zip.Name
    }

    $rec = [ordered]@{
        id         = $tag
        type       = "release"
        dir        = "releases\$tag"
        commit     = $commit
        date       = (Get-Date -Format "yyyy-MM-dd")
        created    = (Get-Date -Format "o")
        size_mb    = (Get-SizeMb $target)
        zip_sha256 = $sha
        source     = "gh release download $tag"
        notes      = ("GitHub Release " + $tag + "；" + $zipNote)
    }
    Upsert-Record $rec
    Remove-Item $tmp -Recurse -Force
    Write-Host ("已加入 " + $tag + "（" + $rec.size_mb + " MB，commit " + $commit + "）")
}

function Cmd-AddBeta {
    Initialize-Root
    $sha = (git -C $RepoRoot rev-parse --short HEAD)
    $date = Get-Date -Format "yyyyMMdd"
    $id = if ($Label) { "beta-$Label" } else { "beta-$date-$sha" }
    $target = Join-Path (Join-Path $VersionRoot "betas") $id
    if (Test-Path $target) {
        # ★同一个 feature 只留最新一份★：带 Label 的 beta 是可重建的临时产物，
        #   重跑就替换，不堆版本（运维口径：「同一个 feature 给我最新的就好」）。
        Write-Host "替换同名 beta：$target"
        Remove-Item $target -Recurse -Force
    }

    $shell = Join-Path $RepoRoot "install"
    if (-not (Test-Path (Join-Path $shell "MFAAvalonia.exe"))) {
        throw "找不到壳：$shell\MFAAvalonia.exe（先跑一次 CI 包或本地 install）"
    }

    Write-Host "复制壳（install\ 排除 debug/logs/temp/backup）-> $target"
    Invoke-Robocopy $shell $target @("debug", "logs", "temp", "backup")

    Write-Host "覆盖产品文件：assets/resource -> resource"
    Invoke-Robocopy (Join-Path $RepoRoot "assets\resource") (Join-Path $target "resource")
    Write-Host "覆盖产品文件：assets/interface.json -> interface.json"
    Copy-Item (Join-Path $RepoRoot "assets\interface.json") (Join-Path $target "interface.json") -Force
    Write-Host "覆盖产品文件：agent/*.py -> agent/"
    Invoke-Robocopy (Join-Path $RepoRoot "agent") (Join-Path $target "agent") @("__pycache__")

    $ver = ""
    try {
        $raw = Get-Content (Join-Path $target "interface.json") -Raw -Encoding UTF8
        if ($raw -match '"version"\s*:\s*"([^"]+)"') { $ver = $Matches[1] }
    } catch { }

    $rec = [ordered]@{
        id         = $id
        type       = "beta"
        dir        = "betas\$id"
        commit     = $sha
        date       = (Get-Date -Format "yyyy-MM-dd")
        created    = (Get-Date -Format "o")
        size_mb    = (Get-SizeMb $target)
        zip_sha256 = ""
        source     = "install/ 壳 + 当前 main 覆盖"
        notes      = ("基于 main@" + $sha + "；interface.json 版本 " + $ver)
    }
    Upsert-Record $rec
    Write-Host ("已加入 " + $id + "（" + $rec.size_mb + " MB）")
}

function Cmd-Use {
    if (-not $Arg) { throw "用法：use <id>，例如 use v1.0.5 / use beta-20261021-8086d61" }
    $dir = Find-VersionDir $Arg
    if (-not $dir) { throw "找不到版本：$Arg（先 list 看有哪些）" }
    Set-CurrentJunction $dir
    Write-Host ("current -> " + $dir)
    Write-Host ("跑：" + (Join-Path $VersionRoot "current\MFAAvalonia.exe"))
}

function Cmd-Prune {
    Initialize-Root
    $m = Read-Manifest
    $releases = @(@($m.versions) | Where-Object { $_ -and $_.type -eq "release" } | Sort-Object date -Descending)
    if ($releases.Count -le $Keep) {
        Write-Host ("release 共 " + $releases.Count + " 个，无需清理（-Keep " + $Keep + "）")
        return
    }
    $drop = $releases[$Keep..($releases.Count - 1)]
    Write-Host ("将删除 " + $drop.Count + " 个旧 release（保留最近 " + $Keep + " 个；beta 一律保留）：")
    foreach ($v in $drop) { Write-Host ("  - " + $v.id + "  (" + $v.date + ")") }
    if (-not $Force) {
        Write-Host "只是预演。确认要删就加 -Force。"
        return
    }
    foreach ($v in $drop) {
        $dir = Join-Path $VersionRoot $v.dir
        if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }
        Write-Host ("已删除 " + $v.id)
    }
    $keepIds = @($releases[0..($Keep - 1)] | ForEach-Object { $_.id })
    $rest = @(@($m.versions) | Where-Object { $_ -and ($_.type -ne "release" -or $keepIds -contains $_.id) })
    Write-Manifest ([pscustomobject]@{ versions = $rest })
}

switch ($Command.ToLower()) {
    "list" { Cmd-List }
    "add-release" { Cmd-AddRelease }
    "add-beta" { Cmd-AddBeta }
    "use" { Cmd-Use }
    "prune" { Cmd-Prune }
    default {
        Write-Host "用法：versions.ps1 <list|add-release <tag>|add-beta|use <id>|prune> [-KeepZip] [-Keep N] [-Force]"
        exit 2
    }
}
