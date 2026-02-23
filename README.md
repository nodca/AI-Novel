# AI-Novel V2 使用文档

## 环境准备

```bash
pip install -r requirements.txt
```

## 配置

编辑 `config.yaml`：

- `anthropic` — API密钥、模型、base_url
- `novel.novel_dir` — 小说根目录（含 `chapters/` 子目录）
- `novel.outline_dir` — 细纲目录
- `novel.setting_file` — 设定文档路径（用于生成世界观摘要）
- `novel.style_guide_file` — 写作风格指南路径
- `novel.setting_docs` — 需索引到LightRAG的设定文档列表
- `lightrag.embedding` — 嵌入模型配置（SiliconFlow）
- `lightrag.rerank` — 重排序模型配置

## 使用流程

### 1. 初始化项目

首次使用或迁移后执行一次：

```bash
python main.py init
```

功能：
- 创建SQLite数据库
- 索引设定文档到LightRAG
- 生成世界观摘要

### 2. 从V1迁移（可选）

```bash
python migrate_v1.py config.yaml "postgresql://user:pass@localhost:5432/novel_generator" "C:/path/to/chapters"
```

迁移内容：角色、关系、伏笔、摘要 → SQLite，章节正文 → LightRAG索引。

### 3. 生成单章

```bash
python main.py write <细纲文件> <章节号>
```

加 `--yes` 跳过矛盾确认（warning自动跳过，error级别也不暂停）：
```bash
python main.py write <细纲文件> <章节号> --yes
```

示例：
```bash
python main.py write "C:/魔卡异世界小说/章节细纲/第56章细纲.md" 56
```

### 4. 批量生成

```bash
python main.py batch <细纲文件> <起始章> <结束章>
```

示例：
```bash
python main.py batch "C:/魔卡异世界小说/章节细纲/第二卷细纲.md" 56 60
```

### 5. 手动修改后重处理

修改正文后，重新提取状态写入DB并重新索引LightRAG：

```bash
python main.py reprocess <章节号>
```

示例：
```bash
python main.py reprocess 56
```

## 细纲格式

细纲文件为Markdown，每章以 `##` 开头：

```markdown
## 第56章：章节标题

**出场人物：** 林远、莉娅、艾伦

**核心事件：**
1. 事件一
2. 事件二

**开头：** 开头描述
**中间：** 中间描述
**结尾：** 结尾描述
**伏笔：** 伏笔描述

**字数：** 2500-3000字
```

## 生成流程

```
Stage 0  解析细纲
   ↓
Stage 1  预检（矛盾检测）+ 场景规划（生成Scene Contract）  [Sonnet]
   ↓
Stage 2  逐场景生成正文  [Opus]
   ↓
Stage 2.5  一致性校验 + 定向修复  [Sonnet]
   ↓
Stage 3  后处理：提取状态→写DB→索引LightRAG→保存文件
```

- 预检发现矛盾时会暂停，等待确认
- 一致性校验失败会尝试自动修复一次，仍失败则暂停确认
- 生成的章节保存在 `novel_dir/chapters/` 下

## 目录结构

```
AI-Novel V2/
├── config.yaml          # 配置
├── main.py              # CLI入口
├── novel_state.db       # SQLite数据库（自动创建）
├── lightrag_data/       # LightRAG数据（自动创建）
├── core/                # 核心逻辑
│   ├── pipeline.py      # 主流程
│   ├── outline_parser.py
│   ├── precheck.py      # 预检+场景规划
│   ├── context_builder.py # 上下文组装（POV沙箱、Token预算）
│   ├── writer.py        # 场景生成
│   ├── consistency.py   # 一致性校验
│   └── postprocess.py   # 后处理
├── db/                  # 数据库
├── rag/                 # LightRAG
├── llm/                 # Claude客户端
└── utils/               # 工具函数
```

## 桌面版（进行中）

已新增 `desktop/` 目录，包含：
- Electron 桌面壳
- React 前端工作台（暖纸感、低压力）
- FastAPI 本地服务（多书工作区 + 任务队列）

详见：`desktop/README.md`
