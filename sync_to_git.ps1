# Git 同步脚本 - 将本地文件同步到 Git 仓库
# 使用方法: .\sync_to_git.ps1

Write-Host "=== Git 文件同步脚本 ===" -ForegroundColor Green
Write-Host ""

# 检查是否在正确的目录
if (-not (Test-Path "main")) {
    Write-Host "错误: 未找到 main 目录，请确保在项目根目录执行此脚本" -ForegroundColor Red
    exit 1
}

# 检查 Git 仓库
if (-not (Test-Path ".git")) {
    Write-Host "正在初始化 Git 仓库..." -ForegroundColor Yellow
    git init
    git remote add origin git@github.com:loxgtxy/main.git 2>
}

# 检查远程仓库配置
Write-Host "检查远程仓库配置..." -ForegroundColor Yellow
git remote -v

Write-Host ""
Write-Host "步骤 1: 添加文件到暂存区" -ForegroundColor Cyan
Write-Host "----------------------------" -ForegroundColor Cyan

# 添加项目文件
git add .gitignore
git add main/
git add README.md
git add *.ps1

Write-Host "已添加项目文件" -ForegroundColor Green

# 显示状态
Write-Host ""
Write-Host "当前暂存区状态:" -ForegroundColor Yellow
git status --short

Write-Host ""
Write-Host "步骤 2: 提交更改" -ForegroundColor Cyan
Write-Host "----------------------------" -ForegroundColor Cyan

# 获取提交信息
 = Read-Host "请输入提交信息 (直接回车使用默认: 'Update local files')"
if ([string]::IsNullOrWhiteSpace()) {
     = "Update local files"
}

# 提交
git commit -m 

if ( -eq 0) {
    Write-Host "提交成功!" -ForegroundColor Green
} else {
    Write-Host "提交失败或没有需要提交的更改" -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "步骤 3: 推送到远程仓库" -ForegroundColor Cyan
Write-Host "----------------------------" -ForegroundColor Cyan

# 获取当前分支
 = git branch --show-current
if ([string]::IsNullOrWhiteSpace()) {
     = "master"
}

Write-Host "当前分支: " -ForegroundColor Yellow

# 询问是否推送
 = Read-Host "是否推送到远程仓库? (y/n)"
if ( -eq "y" -or  -eq "Y") {
    Write-Host "正在推送到 origin/ ..." -ForegroundColor Yellow
    git push -u origin 
    
    if ( -eq 0) {
        Write-Host ""
        Write-Host "=== 同步完成! ===" -ForegroundColor Green
    } else {
        Write-Host ""
        Write-Host "推送失败，请检查网络连接或权限" -ForegroundColor Red
    }
} else {
    Write-Host "已跳过推送，你可以稍后使用 'git push' 手动推送" -ForegroundColor Yellow
}

Write-Host ""


