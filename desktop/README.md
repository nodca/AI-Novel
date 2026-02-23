# AI-Novel Desktop (Electron + React + FastAPI)

这个目录是桌面版第一阶段实现，采用：

- Electron（桌面壳）
- React + Vite（前端 UI）
- FastAPI（本地控制层）
- 现有 `core.pipeline` 作为生成引擎

## 目录结构

```text
desktop/
├─ electron/     # Electron 主进程与 preload
├─ frontend/     # React 前端
└─ backend/      # FastAPI 本地服务
```

## 后端 API 快速启动

```bash
python -m desktop.backend.run_backend
```

服务地址：`http://127.0.0.1:8008`

## 前端开发

```bash
cd desktop/frontend
npm install
npm run dev
```

## Electron 开发

```bash
cd desktop
npm install
npm run dev
```

> `npm run dev` 默认假设前端 dev server 在 `http://127.0.0.1:5173`。  
> Electron 会自动拉起本地 FastAPI 后端。

## Windows 发布打包

发布链路使用 `PyInstaller + electron-builder`：

```bash
pip install -r requirements.txt pyinstaller
cd desktop
npm install
npm run dist:win
```

产物默认输出到：`desktop/release/`

默认会启用后端瘦身打包（排除重型可选 ML 模块）以降低体积与构建时长。  
如需关闭可在打包前设置：`AI_NOVEL_BACKEND_LEAN=0`

更详细发布说明见：`desktop/RELEASE.md`
对外分发与自动更新简版流程见：`desktop/DISTRIBUTION.md`

签名与自动更新：

- 签名使用 `CSC_LINK` / `CSC_KEY_PASSWORD`
- 自动更新发布使用 `dist:win:publish`（GitHub Release + `latest.yml`）

## 现阶段已完成

- 每本书独立工作区（`%APPDATA%/AI-Novel-V2/projects/<slug>`）
- 项目管理 API（创建/列表/激活/配置更新）
- 任务队列 API（提交/列表/状态查询/重试/queued 取消 + running 软取消 + batch 暂停/继续）
- 任务执行接入现有引擎（`init/write/batch/reprocess`）
- 成本中心基础能力（LLM 调用 token/时延/费用估算采集 + 汇总接口）
- 模型配置中心（动态 Provider 配置池 + 角色绑定 + API key 默认掩码显示）
- 一致性中心（自动记录阶段 2.5 问题 + 去重 + 定位跳转 + 类型统计 + 单章/批量 open-error reprocess + 章节号筛选 + reprocess 成功后自动 resolved 联动）
- 版本快照中心（章节快照创建/恢复 + 快照差异预览 + 标签管理 + 关键词/标签检索 + 收藏与章节时间线，恢复后可直接排队 reprocess）
- 手动改稿重处理入口（桌面端可直接提交 `reprocess` 任务）
- 暖纸感、低压力工作台 UI 骨架
- 发布链路（Windows）：后端可打包为内置 exe，Electron 安装包通过 `electron-builder` 生成，支持签名与自动更新发布通道
