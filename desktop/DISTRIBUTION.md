# Windows 分发与自动更新（简版）

本文给你一套最短可执行流程：本地打包、发布、让用户自动更新。

## 1. 本地打包（仅测试安装包）

在仓库根目录执行：

```bash
pip install -r requirements.txt pyinstaller
npm install --prefix desktop/frontend
npm install --prefix desktop
npm --prefix desktop run dist:win
```

产物目录：

- `desktop/release/ai-novel-desktop-<version>-x64.exe` 安装包
- `desktop/release/win-unpacked/` 便携目录

说明：

- 默认启用后端瘦身打包（排除重型可选依赖）。
- 如需关闭瘦身（全量依赖收集），先设置：
  - `set AI_NOVEL_BACKEND_LEAN=0`

## 2. 配置自动更新发布（一次性）

GitHub 仓库 `Settings -> Secrets and variables -> Actions` 添加：

- `WIN_CSC_LINK`（可选，代码签名证书）
- `WIN_CSC_KEY_PASSWORD`（可选，证书密码）

说明：

- 不配签名也能发布，但 Windows 会有“未知发布者”提示。

## 3. 正式发布（会生成更新清单）

1. 更新版本号：`desktop/package.json` 的 `version`
2. 提交代码并推送
3. 打标签并推送（必须以 `desktop-v` 开头）：

```bash
git tag desktop-v0.1.1
git push origin desktop-v0.1.1
```

4. GitHub Actions 里的 `windows-desktop-release` 会自动运行并发布 Release 资产

### 一键发布脚本（推荐）

仓库根目录可直接运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\release-desktop.ps1
```

默认行为：

- 要求工作区干净（避免误发）
- 自动将 `desktop/package.json` 从当前版本升级一个 patch（例如 `0.1.1 -> 0.1.2`）
- 自动提交、推送 `main`
- 自动创建并推送 `desktop-v<version>` tag，触发 GitHub Actions 发布

可选参数：

```powershell
# 升 minor / major
powershell -ExecutionPolicy Bypass -File .\scripts\release-desktop.ps1 -Bump minor
powershell -ExecutionPolicy Bypass -File .\scripts\release-desktop.ps1 -Bump major

# 指定版本号
powershell -ExecutionPolicy Bypass -File .\scripts\release-desktop.ps1 -Version 0.2.0
```

发布成功后，Release 中应看到：

- 安装包 `.exe`
- 差分包 `.blockmap`
- 更新清单 `latest.yml`

## 4. 客户端自动更新机制

- 已安装版本启动时会自动检查更新（`electron-updater`）
- 发现新版本后自动下载
- 下载完成后提示“重启并更新”

## 5. 回滚（发布有问题时）

1. 在 GitHub Release 删除有问题版本
2. 重新发布一个更高版本号（例如 `0.1.2`）
