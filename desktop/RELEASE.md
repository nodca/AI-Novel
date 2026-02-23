# 桌面版发布指南（Windows）

快速分发说明见：`desktop/DISTRIBUTION.md`

## 本地构建

1. 安装 Python 依赖（在仓库根目录）：
   - `pip install -r requirements.txt pyinstaller`
2. 构建安装包：
   - `cd desktop`
   - `npm install`
   - `npm run dist:win`
3. 产物目录：
   - `desktop/release/`

### 后端打包瘦身（推荐）

`desktop/scripts/build_backend.py` 默认启用精简模式，会排除体积较大的可选依赖
（如 `torch/tensorflow/sklearn/cv2/transformers/pandas/scipy/sympy/...`），可明显降低包体和构建耗时。

- 关闭精简模式（全量收集依赖）：
  - `set AI_NOVEL_BACKEND_LEAN=0`
- 追加自定义排除模块：
  - `set AI_NOVEL_BACKEND_EXCLUDE_MODULES=module_a,module_b`

## 代码签名（Windows）

`electron-builder` 使用以下标准环境变量进行签名：

- `CSC_LINK`：`.p12/.pfx` 证书的 Base64 或 URL
- `CSC_KEY_PASSWORD`：证书密码

如果未配置签名信息，安装包仍可生成，但会是未签名状态。

## 自动更新通道

- 运行时更新器：`electron-updater`（读取 GitHub Releases）
- 发布命令：
  - `npm run dist:win:publish`
- 发布所需环境变量：
  - `GH_TOKEN`
  - `GH_OWNER`
  - `GH_REPO`
- 发布产物应包含：
  - 安装包 `.exe`
  - `.blockmap`
  - `latest.yml`（自动更新清单）

默认更新通道为 `stable`。  
设置 `AI_NOVEL_UPDATE_CHANNEL=beta` 可接收预发布版本。

## GitHub Actions 构建

- 工作流：`.github/workflows/windows-desktop-release.yml`
- 触发方式：
  - 手动触发：`workflow_dispatch`
  - Tag 触发：`desktop-v*`（例如 `desktop-v0.2.0`）
- 构建产物会自动上传。
- Tag 构建会执行发布模式，并将产物推送到 GitHub Release。
- 可选签名密钥（仓库 Secrets）：
  - `WIN_CSC_LINK`
  - `WIN_CSC_KEY_PASSWORD`

## 说明

- 发布包会包含内置后端可执行文件：
  - `backend/ai-novel-backend.exe`（由 `PyInstaller` 构建）
- 打包模式下 Electron 启动内置后端；开发模式下回退到 Python 脚本启动后端。
