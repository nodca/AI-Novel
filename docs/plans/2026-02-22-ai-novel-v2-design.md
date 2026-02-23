# AI-Novel V2 设计文档

## 1. 项目背景

V1（AI_NovelGenerator/chapter_writer.py）的核心痛点：
- **角色遗忘**：已建立的事实、关系、事件在后续章节中丢失。根因是后处理提取漏了的信息无法找回，且分层摘要会丢失细节
- **上下文全量注入**：所有角色状态、关系一股脑塞进 prompt，重要细节被噪音淹没
- **流程割裂**：手动选文件、手动跑程序，细纲与正文矛盾无法提前发现
- **单次生成整章**：2500-3000 字一次性输出，LLM 后期容易漂移忘记约束

## 2. 核心设计思路

**双通道记忆系统**：结构化 DB（精确状态）+ LightRAG（叙事细节检索）互补。DB 告诉 LLM "现在是什么状态"，LightRAG 告诉 LLM "之前具体发生了什么"。即使后处理提取漏了某个细节，原文仍在 LightRAG 中可检索。

**精准检索替代全量注入**：不再把所有信息塞进 prompt。通过上下文规划器分析本章大纲，生成针对性检索查询，只注入真正相关的上下文。

**场景级生成**：将章节拆为 2-4 个场景逐个生成，每个场景有独立的精准上下文，prompt 更短，LLM 注意力更集中。

## 3. 技术栈

```
存储：SQLite + SQLAlchemy（结构化状态）
检索：LightRAG（向量索引 NanoVectorDB + 知识图谱 NetworkX）
LLM：Claude only（Anthropic SDK）
     - Sonnet：细纲预检、场景规划、后处理提取
     - Opus：正文生成
语言：Python
```

## 4. 数据模型

### 4.1 SQLite 表

```
Character
  name, role_type, gender, age, appearance, personality,
  background, location, physical_state, mental_state,
  cultivation_stage, items, abilities,
  speech_style, dialogue_examples,
  voice_samples (JSON数组，动态提取的典型对话),  ← 新增
  is_active

CharacterRelationship
  from_character, to_character, type, intimacy, description

CharacterKnowledge  ← 新增（替代 V1 的 EstablishedFact）
  character       角色名
  fact            事实内容
  source          怎么知道的（witnessed/told/inferred）
  learned_chapter 哪一章知道的
  confidence      确定程度（certain/suspect/guess）

KnowledgeTriple
  subject, predicate, object, subject_type, object_type, chapter_number

Foreshadow
  title, content, hint_text, chapter_planted, chapter_resolved,
  target_resolve_chapter, is_long_term, importance, strength, subtlety,
  related_characters, category, status (planted/resolved)

Summary
  level (chapter/arc/global), scope_start, scope_end, content
```

### 4.2 LightRAG 存储

- 每章全文索引 → 自动构建实体图谱 + 向量索引
- 设定文档索引（世界观、战力体系、库洛牌设定等）
- 检索模式：hybrid（图谱 + 向量混合）

## 5. 生成管线

```
输入：细纲文件路径 + 章节号

━━━ 阶段0: 初始化 ━━━
读取细纲 → 解析当前章节
输出：title, characters, events, opening, middle, ending, foreshadows, word_count

━━━ 阶段1: 细纲预检 + 场景规划（Sonnet，1次调用）━━━
输入：细纲 + 从 LightRAG/DB 检索的相关上下文
职责：
  a) 预检：检测细纲与已有正文/状态的矛盾
     → 输出矛盾列表（如有），用户确认后继续
  b) 场景规划：将章节拆为 2-4 个场景，每个场景输出 Scene Contract（JSON）：
     {
       "scene_number": 1,
       "pov_character": "林远",
       "characters": ["林远", "诺娃"],
       "must_events": ["林远发现跟踪者", "诺娃出现帮忙"],
       "forbidden_facts": ["不能透露克洛伊身份"],
       "required_foreshadows": {"advance": ["诺娃的怀疑"]},
       "tone_target": "紧张→缓和",
       "word_count": 800,
       "retrieval_queries": {
         "narrative": ["林远被跟踪的历史场景"],
         "setting": []
       }
     }

━━━ 阶段2: 逐场景生成（循环，每场景1次 Opus 调用）━━━
For each scene:
  2a. 上下文组装（context_builder）
    - Scene Contract 作为核心指令
    - DB：POV 角色可知的状态和关系（POV 认知沙箱过滤）
    - DB：POV 角色的 CharacterKnowledge（仅 certain/suspect 条目）
    - DB：出场角色 voice_samples（语音指纹）
    - DB：分层摘要（全局 + 弧 + 近章）
    - DB：伏笔上下文（需回收/推进/埋设的伏笔）
    - LightRAG：Scene Contract 中 retrieval_queries 的检索结果
    - bridge_memo（前场景衔接）
    - 风格指南

  2b. Opus 生成该场景正文

  2c. 拼接到章节内容（用 --- 分隔场景）

━━━ 阶段2.5: 一致性校验 + 定点修复 ━━━
对完整章节运行一致性校验：
  确定性规则（零 LLM 成本）：
    - 时间线矛盾检测
    - 角色位置连续性
    - 伏笔状态机合法性
    - Scene Contract 履行检查（must_events 是否完成、forbidden_facts 是否泄露）
  LLM 辅助（Sonnet 1次轻量调用）：
    - 已知/未知事实冲突检测（对比 POV 角色的 CharacterKnowledge）
  → 无 error → 进入阶段3
  → 有 error → 输出"问题位置 + 修复指令" → Opus 定点重写该段落（最多1轮）→ 重新校验

━━━ 阶段3: 后处理（事务化，详见第12节）━━━

3a. 提取（Sonnet，1次调用）→ 输出 JSON → 保存临时文件
3b. 写库（SQLite 单事务）→ 全成功 COMMIT / 失败 ROLLBACK
3c. LightRAG 索引 → 失败不阻断，标记 pending 自动重试
3d. 保存章节文件 + 清理临时文件
```

### API 调用量

每章 5-9 次调用：
- Sonnet × 1：预检 + 场景规划（输出 Scene Contract JSON）
- Opus × 2-4：逐场景生成
- Sonnet × 1：一致性校验（POV 认知冲突检测，其余为零成本规则）
- Opus × 0-1：定点修复（仅在校验发现 error 时触发，最多1轮）
- Sonnet × 1：后处理提取
- LightRAG 索引时额外 Sonnet × 1-2：实体关系抽取

## 6. 上下文组装策略

核心原则：**只注入本场景相关的信息，不全量拉取。**

### 6.1 Token 预算与分级裁剪

每个场景设固定输入预算：`max_input_tokens_per_scene = 12000`（可配置）。

按优先级分三层装填，超预算时从 Nice 层开始裁剪：

```
Must（不可裁剪）：
  - 场景大纲（事件、约束、禁止内容）
  - 出场角色当前状态
  - 风格指南（核心部分）
  - 前场景衔接（bridge_memo）
  - 世界观常驻摘要

Important（优先保留，预算不足时压缩）：
  - CharacterKnowledge（认知边界）
  - 角色关系
  - 伏笔指令
  - 分层摘要（全局 + 弧）

Nice（可裁剪）：
  - LightRAG 检索片段（叙事 + 设定）
  - voice_samples
  - 额外知识三元组
```

### 6.2 上下文压缩规则

- **前场景衔接**：不注入前场景全文，改为 bridge_memo（150-300 字）：
  ```
  bridge_memo:
    last_scene_ending: "林远目送队伍离开，转身走进小巷"
    unresolved_tension: "诺娃临走时的眼神暗示她注意到了什么"
    next_scene_setup: "林远需要独自面对暗巷中的跟踪者"
  ```
- **LightRAG 片段**：不硬限长度，保持完整片段。数量由 Token 预算控制——超预算时按 Nice 层整条裁剪，而非截断
- **voice_samples**：最近 2 条 + 最典型 1-2 条，共 3-4 条

### 6.3 prompt 结构（每个场景）

```
1. 系统角色设定（固定，简短）
2. 风格指南（固定，截取核心部分）
3. 世界观常驻摘要（300-500字，每场景都有）
4. Scene Contract（JSON，本场景的硬约束）
5. POV 角色卡（含 voice_samples 3-4条）
6. 其他出场角色卡（仅 POV 可观察到的外在信息）
7. POV 角色的当前状态（位置、物品、伤势等）
8. POV 角色可知的关系（仅与本场景出场角色相关的）
9. POV 认知沙箱（仅 POV 角色的 CharacterKnowledge，certain/suspect 条目）
10. LightRAG 检索结果（叙事片段，POV 可知范围内）
11. LightRAG 检索结果（设定片段，按需，可为空）
12. 分层摘要（全局摘要 + 当前弧摘要）
13. 伏笔指令（本场景需要埋设/推进/回收的伏笔）
14. bridge_memo（前场景衔接，150-300字）
15. 写作约束（出场角色限制、禁止内容等）
```

POV 认知沙箱规则：
- 只注入 POV 角色 confidence=certain 或 suspect 的知识
- 其他角色的秘密信息不进 prompt（而非进了再标注"不能用"）
- suspect 级别的知识标注为"角色隐约感觉/怀疑"，引导 LLM 用暗示而非明示

## 7. 角色语音指纹

### 初始化
从设定文档和风格指南中提取初始 speech_style 和 dialogue_examples。

### 动态更新
后处理阶段从生成的正文中提取典型对话，追加到 voice_samples：

```json
{
  "voice_samples": [
    {"chapter": 10, "text": "哇！这个魔法阵超厉害的！", "context": "莉娅看到古代遗迹"},
    {"chapter": 15, "text": "等等等等，你们先别动，让我算算……", "context": "莉娅分析敌人弱点"}
  ]
}
```

注入 prompt 时取最近 2 条 + 最典型 1-2 条，共 3-4 条样本。

## 8. LightRAG 使用策略

### 索引内容
- 每章全文（后处理完成后索引）
- 设定文档（项目初始化时一次性索引：世界观、战力体系、库洛牌设定等）

### 世界设定的两层处理

**常驻层：世界观摘要**
- 项目初始化时，用 Sonnet 从设定文档提炼 300-500 字精简摘要
- 包含：魔法体系基本规则、等级划分概要、世界基本设定
- 存入 Summary 表（level='world'），每个场景作为 Must 层注入
- 只需生成一次

**按需层：具体设定细节（走 LightRAG 检索）**
- 设定文档全文索引到 LightRAG
- 场景规划器根据大纲判断是否需要检索具体设定
- 例：大纲提到"使用风牌"→ 检索风牌能力详情；日常对话场景 → 不检索设定

### 场景规划器的检索查询输出

```
每个场景的 retrieval_queries:
  narrative: ["林远和诺娃上次关于身份的对话"]     ← 叙事检索
  setting: ["风牌能力详细设定", "D级战力指标"]     ← 设定检索（可为空）
```

### 检索时机
- 阶段1（预检）：用细纲关键实体和事件做检索，获取相关历史
- 阶段2（生成）：用场景规划器输出的 retrieval_queries 做精准检索

### 检索模式
默认使用 hybrid 模式（图谱 + 向量混合），兼顾实体关系追踪和语义相似度。

## 9. 项目结构

```
AI-Novel V2/
├── config.yaml              # 配置（API key、模型、路径）
├── main.py                  # CLI 入口
├── core/
│   ├── pipeline.py          # 主管线（串联各阶段）
│   ├── outline_parser.py    # 细纲解析
│   ├── precheck.py          # 阶段1：细纲预检 + 场景规划
│   ├── writer.py            # 阶段2：逐场景生成
│   ├── postprocess.py       # 阶段3：后处理提取
│   ├── consistency.py       # 一致性校验器
│   └── context_builder.py   # 上下文组装（DB + LightRAG → prompt）
├── db/
│   ├── database.py          # SQLite + SQLAlchemy
│   ├── models.py            # ORM 模型
│   └── queries.py           # 查询封装
├── rag/
│   ├── lightrag_manager.py  # LightRAG 初始化、索引、检索
│   └── indexer.py           # 章节/设定文档索引
├── llm/
│   └── claude_client.py     # Anthropic SDK（Opus/Sonnet）
└── utils/
    └── text.py              # 文本处理工具
```

## 10. 配置文件格式

```yaml
# config.yaml
anthropic:
  api_key: "sk-..."
  writing_model: "claude-opus-4-20250514"
  analysis_model: "claude-sonnet-4-20250514"

novel:
  novel_dir: "C:/Users/Administrator/Desktop/魔卡异世界小说"
  outline_dir: "C:/Users/Administrator/Desktop/魔卡异世界小说/章节细纲"
  setting_file: "docs/plans/2026-02-08-库洛牌异世界冒险-设定文档.md"
  style_guide_file: "docs/style/写作风格指南.md"

database:
  url: "sqlite:///novel_state.db"

lightrag:
  working_dir: "./lightrag_data"
  embedding_model: "text-embedding-3-small"  # 或其他支持的嵌入模型

generation:
  scenes_per_chapter: 3        # 默认场景数（实际由规划器决定）
  summary_arc_interval: 10     # 每N章触发弧摘要
  voice_samples_limit: 10     # 每角色保留最近N条语音样本
```

## 11. 一致性校验器

### 触发时机
阶段2.5：所有场景生成完毕后、后处理提取前运行。

### 校验项

```
1. Scene Contract 履行检查（确定性，零 LLM 成本）
   - must_events：检查每个必须事件是否在正文中体现
   - forbidden_facts：检查禁止内容是否泄露
   - characters：只对命名角色（DB 中已注册的 Character）强校验
     合同外的命名角色出现 → error
     匿名背景角色（路人、店员、群体称谓等）→ 放行，不报错

2. 时间线校验（确定性）
   - 从 Summary + KnowledgeTriple 构建事件时间线
   - 检查本章事件是否与已有时间线矛盾

3. 角色位置校验（确定性）
   - 对比本章角色出现的位置 vs Character.location
   - 检查是否有角色"瞬移"（无转场描写）

4. POV 认知冲突检测（Sonnet 1次轻量调用）
   - 对比正文 vs POV 角色的 CharacterKnowledge
   - certain 级别：允许直接使用，遗忘关键 certain 事实 → warning
   - suspect 级别：允许暗示性表达（"总觉得哪里不对"），禁止确定性断言（"他就是克洛伊"）→ 断言则 error
   - guess 级别：仅允许模糊直觉，不允许具体指向 → 具体指向则 warning
   - 未在 CharacterKnowledge 中的信息：POV 角色不应知道 → 使用则 error

5. 伏笔状态机校验（确定性）
   - planted → 只能转为 resolved（不能重复 plant）
   - resolved → 不能再次 resolve
   - 检查是否意外回收了不该回收的伏笔
   - 严重逾期伏笔（超过 target_resolve_chapter 10章以上）警告
```

### 输出

```python
ConsistencyReport:
  chapter: int
  issues: [
    {
      "type": "contract|timeline|location|knowledge|foreshadow",
      "severity": "error|warning",
      "description": "具体问题描述",
      "location": "问题所在段落/场景编号",
      "fix_instruction": "修复指令（error级别时提供）"
    }
  ]
  passed: bool  # 无 error 级别问题则为 True
```

### 定点修复流程
- error 级别 → 将 `location` + `fix_instruction` 发给 Opus，只重写问题段落
- 最多 1 轮修复，修复后重新校验
- 仍未通过 → 提示用户介入（重写/忽略）
- warning 级别 → 记录日志，不阻断

## 12. 事务与回滚机制

### 问题
V1 的后处理是一个大 try/except，部分写入失败会导致 DB 状态不一致（比如角色状态更新了但伏笔没更新）。LightRAG 索引和 DB 写入之间也没有原子性保证。

### 设计

整个阶段3（后处理）采用事务 + 补偿重试（Saga 风格）：

```
阶段3 详细流程（唯一权威定义）：

3a. 提取（Sonnet 调用）
    → 输出 JSON 结构化数据
    → 保存到临时文件 chapters/.pending/ch{N}_extract.json

3b. 写库（SQLite 事务）
    → BEGIN TRANSACTION
    → 更新 Character、CharacterRelationship、CharacterKnowledge、
      KnowledgeTriple、Foreshadow、Summary
    → 全部成功 → COMMIT
    → 任一失败 → ROLLBACK，报错，用户可重试

3c. LightRAG 索引
    → 将全文索引到 LightRAG
    → 失败 → 不影响 DB（DB 已提交），记录失败标记
    → 下次启动时自动重试未索引的章节

3d. 保存章节文件
    → 写入 chapters/ 目录
    → 清理 chapters/.pending/ 临时文件
```

注：一致性校验在阶段2.5执行（生成后、后处理前），不在此流程内。

### 关键保证

```
1. DB 原子性：所有 DB 更新在一个 SQLite 事务内，要么全成功要么全回滚
2. LightRAG 最终一致：索引失败不阻断流程，通过 pending 标记实现重试
3. 幂等性：重试同一章节不会产生重复数据（按 chapter_number 做 upsert）
4. 临时文件兜底：extract.json 保存提取结果，即使写库失败也不需要重新调 LLM
```

### 未索引章节自动重试

```python
# 启动时检查
pending_chapters = 找到所有有 DB 记录但未索引到 LightRAG 的章节
for chapter in pending_chapters:
    读取章节文件 → 索引到 LightRAG → 清除 pending 标记
```

## 13. V1 → V2 迁移

V2 需要支持从 V1 已有数据迁移：
- V1 PostgreSQL 中的 Character/Relationship/Foreshadow/Summary → 导入 SQLite
- V1 已生成的 55 章正文 → 批量索引到 LightRAG
- V1 EstablishedFact → 转换为 CharacterKnowledge（source 默认 "migrated"）
