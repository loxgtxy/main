# 同步所有项目文件到 Git
# 在项目目录中运行此脚本

$ErrorActionPreference = "Stop"

Write-Host "=== 同步项目文件到 Git ===" -ForegroundColor Green
Write-Host ""

# 获取项目目录
$projectDir = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($projectDir)) {
    $projectDir = Get-Location
}

Write-Host "项目目录: $projectDir" -ForegroundColor Yellow

# 切换到用户主目录（Git 仓库根目录）
$homeDir = $env:USERPROFILE
Set-Location $homeDir

Write-Host "Git 仓库目录: $homeDir" -ForegroundColor Yellow
Write-Host ""

# 检查 Git 仓库
if (-not (Test-Path ".git")) {
    Write-Host "错误: 未找到 Git 仓库" -ForegroundColor Red
    exit 1
}

# 获取项目相对路径
$relativePath = $projectDir.Replace($homeDir, "").TrimStart("\")
Write-Host "项目相对路径: $relativePath" -ForegroundColor Yellow
Write-Host ""

# 添加项目文件
Write-Host "添加项目文件..." -ForegroundColor Cyan

# 使用 Get-ChildItem 获取文件列表，然后逐个添加
$filesToAdd = @(
    "$relativePath\main\pm_monitor.py",
    "$relativePath\main\README.md",
    "$relativePath\limitless刷交易量.py",
    "$relativePath\openapi.yaml",
    "$relativePath\README.md",
    "$relativePath\.gitignore"
)

$addedFiles = @()
foreach ($file in $filesToAdd) {
    $fullPath = Join-Path $homeDir $file
    if (Test-Path $fullPath) {
        Write-Host "  添加: $file" -ForegroundColor Gray
        git add "$file" 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $addedFiles += $file
        }
    } else {
        Write-Host "  跳过（不存在）: $file" -ForegroundColor Yellow
    }
}

# 添加 main 目录下的所有文件
$mainDir = Join-Path $homeDir "$relativePath\main"
if (Test-Path $mainDir) {
    Write-Host "  添加 main 目录..." -ForegroundColor Gray
    Get-ChildItem -Path $mainDir -Recurse -File | ForEach-Object {
        $relativeFile = $_.FullName.Replace($homeDir, "").TrimStart("\")
        git add "$relativeFile" 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $addedFiles += $relativeFile
        }
    }
}

Write-Host ""
Write-Host "已添加 $($addedFiles.Count) 个文件" -ForegroundColor Green
Write-Host ""

# 显示状态
Write-Host "=== 暂存区状态 ===" -ForegroundColor Cyan
git status --short | Select-String $relativePath.Replace("\", "\\") | Select-Object -First 20

Write-Host ""
$commit = Read-Host "是否提交并推送? (y/n)"
if ($commit -eq "y" -or $commit -eq "Y") {
    $message = Read-Host "请输入提交信息 (直接回车使用默认)"
    if ([string]::IsNullOrWhiteSpace($message)) {
        $message = "Sync project files"
    }
    
    Write-Host ""
    Write-Host "提交更改..." -ForegroundColor Cyan
    git commit -m $message
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "推送到远程仓库..." -ForegroundColor Cyan
        git push origin main
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host ""
            Write-Host "=== 同步完成! ===" -ForegroundColor Green
        } else {
            Write-Host ""
            Write-Host "推送失败" -ForegroundColor Red
        }
    } else {
        Write-Host ""
        Write-Host "提交失败或没有需要提交的更改" -ForegroundColor Yellow
    }
} else {
    Write-Host ""
    Write-Host "已跳过提交，你可以稍后手动提交" -ForegroundColor Yellow
}

