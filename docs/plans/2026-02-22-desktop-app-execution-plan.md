# AI-Novel Desktop 执行方案（Electron + React + FastAPI）

## 目标

在 Windows 上落地本地桌面应用，支持多书项目隔离、任务队列、生成控制与低压力创作体验。

## 已落地（本次实现）

1. 本地控制层（FastAPI）
   - `desktop/backend/api/main.py`
   - 项目管理：创建、列表、激活、配置读写
   - 任务管理：提交、查询、重试、取消（queued）
2. 每书独立工作区
   - 默认目录：`%APPDATA%/AI-Novel-V2/projects/<slug>/`
   - 独立 `config.yaml`、`novel_state.db`、`lightrag_data/`、`chapters/`
3. 引擎接入
   - 任务类型：`init_project/write_chapter/batch_write/reprocess`
   - 复用现有 `core.pipeline`
4. 桌面壳和前端骨架
   - Electron 主进程自动拉起后端
   - React 暖纸感工作台 UI（书架 + 概览 + 任务面板）
5. 成本中心（第一版）
   - LLM 调用埋点：model、token、latency、estimated cost
   - 项目级聚合接口：summary / events
   - 前端展示：近30天预计成本 + 最近调用明细
6. 模型配置中心（第一版）
   - 统一模型中心结构（providers/roles/runtime/pricing）
   - 后端 API：`GET/PUT /api/v1/projects/{id}/model-center`
   - 前端面板支持自定义 API key、base_url、模型与关键参数
7. 一致性中心（第一版）
   - 阶段 2.5 结果自动落库（按项目/章节沉淀 issue）
   - 后端 API：summary / issues / issue 状态更新
   - 前端面板支持筛选与状态流转（open/resolved/ignored）
8. 一致性中心（增强）
   - issue 去重（同章同描述重复问题自动合并并重新置为 open）
   - issue 定位跳转（返回章节文件路径 + 场景行号提示）
   - 一键修复任务（open error 章节批量排队 reprocess，自动跳过已在队列/运行中的章节）
   - 章节号筛选 + 问题级单章重处理入口
   - reprocess 成功后自动将该章 `open` 问题标记为 `resolved`
9. 任务中断增强
   - running 任务软取消（cooperative cancel）
   - batch_write 任务暂停/继续
10. 版本快照
   - 快照 API：创建/列表/恢复/差异对比
   - 快照标签与检索（标题/备注/路径/标签关键词 + 标签筛选）
   - 快照收藏与章节时间线筛选
   - 写作任务成功后自动快照
   - 快照恢复可选自动排队 reprocess
11. 手动改稿重处理
   - 桌面端支持手动输入章节号提交 `reprocess`，用于正文修改后重建状态与索引
12. 发布链路（Windows）
   - PyInstaller 打包后端为 `ai-novel-backend.exe`
   - Electron Builder 生成 NSIS 安装包
   - GitHub Actions 自动构建并上传发布产物
   - 代码签名环境变量接入（`CSC_LINK` / `CSC_KEY_PASSWORD`）
   - 自动更新通道（`electron-updater` + GitHub Release / `latest.yml`）

## 下一阶段（建议顺序）

1. 版本快照增强
   - 快照时间线视图与收藏
2. 发布链路
   - 安装包签名、自动更新通道

## 技术约束

- 平台：Windows-only（首版）
- 架构：Electron + React + FastAPI
- 数据隔离：每书独立工作区，不共享生成状态
