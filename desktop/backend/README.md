# Desktop Backend

本目录是 AI-Novel 桌面版本地控制层（FastAPI）。

## 功能

- 多书工作区管理（每本书独立目录）
- 任务队列（`init_project/write_chapter/batch_write/reprocess`）
- 复用现有 `core.pipeline` 生成引擎
- 模型配置中心（Anthropic + RAG 通道统一配置 API）

## 启动

```bash
python -m desktop.backend.run_backend
```

默认监听：`http://127.0.0.1:8008`

## 数据目录

- 默认：`%APPDATA%/AI-Novel-V2`
- 可通过环境变量覆盖：`AI_NOVEL_APP_HOME`

主要内容：
- `app_state.db`：项目和任务元数据
- `projects/<slug>/`：每本书独立工作区
