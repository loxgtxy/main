# Git 同步指南 - 将本地文件同步到 Git

## 问题说明

当前 Git 仓库在用户主目录，需要切换到项目目录进行同步。

## 快速同步步骤

### 方法 1: 使用同步脚本（推荐）

1. **打开 PowerShell 并切换到项目目录**：
   `powershell
   cd "C:\Users\12694\Desktop\新建文件夹 (2)\learn"
   `

2. **运行同步脚本**：
   `powershell
   .\sync_to_git.ps1
   `

3. 按照提示输入提交信息并确认推送

### 方法 2: 手动同步（详细步骤）

#### 步骤 1: 进入项目目录
`powershell
cd "C:\Users\12694\Desktop\新建文件夹 (2)\learn"
`

#### 步骤 2: 检查 Git 状态
`powershell
# 如果项目目录中没有 .git，需要初始化
git init

# 如果还没有配置远程仓库
git remote add origin git@github.com:loxgtxy/main.git
`

#### 步骤 3: 添加文件到暂存区
`powershell
# 添加所有项目文件
git add .gitignore
git add main/
git add README.md
git add *.ps1

# 或者一次性添加所有已跟踪和未跟踪的文件（需要小心）
git add -A
`

#### 步骤 4: 查看将要提交的文件
`powershell
git status
`

#### 步骤 5: 提交更改
`powershell
git commit -m "Update local files"
`

#### 步骤 6: 推送到远程仓库
`powershell
# 首次推送需要设置上游分支
git push -u origin master

# 或者如果你的主分支是 main
git push -u origin main

# 后续推送可以直接使用
git push
`

## 常用 Git 命令

### 查看状态和差异
`powershell
# 查看工作区状态
git status

# 查看暂存区的更改
git diff --cached

# 查看工作区的更改
git diff
`

### 分支操作
`powershell
# 查看所有分支
git branch -a

# 切换到远程分支
git checkout -b main origin/main

# 创建新分支
git checkout -b new-branch
`

### 拉取远程更新
`powershell
# 获取远程更新（不合并）
git fetch origin

# 拉取并合并
git pull origin main
`

## 注意事项

1. **首次推送前**，确保远程仓库已经存在或者你有推送权限
2. **提交前**，使用 git status 检查要提交的文件
3. **推送前**，建议先 git fetch 拉取远程最新更改，避免冲突
4. **如果遇到冲突**，需要先解决冲突再推送：
   `powershell
   git pull origin main  # 拉取最新更改
   # 解决冲突后
   git add .
   git commit -m "Resolve conflicts"
   git push
   `

## 解决 Git 仓库在错误目录的问题

如果 Git 仓库在用户主目录而不是项目目录，可以：

### 选项 1: 在项目目录重新初始化（推荐）
`powershell
cd "C:\Users\12694\Desktop\新建文件夹 (2)\learn"
git init
git remote add origin git@github.com:loxgtxy/main.git
`

### 选项 2: 移动 .git 目录
`powershell
# 从用户主目录移动 .git 到项目目录（不推荐，可能有问题）
`

## 故障排除

### 问题: Permission denied
- 检查文件权限
- 确保以管理员身份运行（如果需要）

### 问题: 推送被拒绝
- 检查是否有推送权限
- 先拉取远程更改：git pull --rebase origin main

### 问题: 网络连接问题
- 使用 SSH 代替 HTTPS（已配置）
- 检查网络连接


