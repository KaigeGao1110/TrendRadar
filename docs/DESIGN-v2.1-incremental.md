# TrendRadar 2.0 → 2.1 Incremental Design

**Date:** 2026-04-25
**Status:** Draft — Pending CEO Approval
**Based on:** PRD v2.0 (2026-04-22) + Brainstorming Session (2026-04-25)

---

## 1. What Changed and Why

PRD v2.0 的 Phase 1（数据管道 + 基础设施）已全部完成并验证通过。Phase 2 的设计经过 brainstorming 后有重大调整。

**核心认知变化：** 痛点 > 技术 > 融资。融资数据丰富但只有统计意义，痛点数据稀缺但直接指导行动。

### 决策矩阵

| # | 决策点 | 选择 | 理由 |
|---|--------|------|------|
| 1 | 事件关联粒度 | 完全语义关联（embedding） | 跨源关联需要理解语义，关键词匹配不够 |
| 2 | 评分时机 | 分层评分（痛点先行） | 痛点是中心，其他源做验证 |
| 3 | 痛点验证 | 四维交叉验证 | 数量+质量+跨源+数据，缺一不可 |
| 4 | 痛点丢弃阈值 | confidence < 50 丢弃 | 中等门槛，需要一定验证 |
| 5 | 评分权重 | pain 55% + tech 30% + timing 15% | 痛点决定方向，技术决定成本，融资只验证时机 |
| 6 | 搜索策略 | 前期广泛收集，后期数据驱动 | 先积累痛点数据，再根据数据选择领域 |
| 7 | Embedding模型 | doubao-embedding-vision | 多模态（文本+图片），Ark plan 已有 |
| 8 | Embedding存储 | Supabase pgvector | 已有Supabase实例，支持向量搜索 |
| 9 | Cron调度 | 7:00爬取 → 8:00分析 | 分步执行，失败不互相影响 |
| 10 | 输出方式 | Obsidian Markdown + 反馈模板 | 比Telegram更适合深度阅读和打分 |
| 11 | 反馈方式 | 1-10分在Obsidian里填写 | 简单直接，下次读取时自动学习 |

---

## 2. Three-Layer Signal Architecture

```
┌─────────────────────────────────────────────────────┐
│         Layer 1: Pain Signals (痛点信号)             │
│         权重: 55%                                    │
│                                                     │
│  Twitter ("I wish there was...")  → 直接用户需求     │
│  Reddit (r/startups, r/SaaS)     → 用户抱怨和讨论    │
│  HN Comments                     → 技术社区痛点      │
│  ProductHunt Deep                → 产品反馈          │
│                                                     │
│  → 输出: pain_score (0-100) + confidence (0-100)     │
│  → 决定"做什么"                                      │
├─────────────────────────────────────────────────────┤
│       Layer 2: Tech Feasibility (技术可行性)          │
│       权重: 30%                                      │
│                                                     │
│  GitHub Trending   → 有没有开源实现？复刻难度？       │
│  HN Comments       → 技术讨论，实现方案              │
│  ProductHunt Deep  → 竞品技术栈                      │
│                                                     │
│  → 输出: tech_score (0-100)                          │
│  → 决定"怎么做"                                      │
├─────────────────────────────────────────────────────┤
│        Layer 3: Market Validation (市场验证)          │
│        权重: 15%                                     │
│                                                     │
│  FundBat (791条)   → 融资规模/轮次                   │
│  VC Funding        → 投资动向                        │
│  NewsAPI           → 行业新闻                        │
│  RSS Newsletters   → 深度分析                        │
│  YC                → 加速器投资                      │
│  Google Trends     → 搜索热度                        │
│                                                     │
│  → 输出: timing_score (0-100)                        │
│  → 决定"现在做不做"                                   │
└─────────────────────────────────────────────────────┘
```

---

## 3. Pain Verification Engine (痛点验证引擎)

一条痛点信号进入后，经过4层验证，输出 confidence (0-100)。

### Layer 1: Volume Check (数量验证)

同一痛点被多人提到才可信。

- 语义聚类：embedding 余弦相似度 > 0.45
- 1人提到 = 30分基础分
- 3-5人 = +20分
- 6-10人 = +30分
- 10人以上 = +40分

### Layer 2: Signal Strength (质量验证)

信号本身的"分量"。

- Twitter: favorites × 0.1 + retweets × 0.5 + replies × 0.3
- Reddit: upvotes + comments
- 发帖者影响力: followers 权重

阈值：
- 总互动 < 5 = 弱信号 (×0.5)
- 5-50 = 中等信号 (×1.0)
- 50-500 = 强信号 (×1.5)
- 500+ = 病毒级信号 (×2.0)

### Layer 3: Cross-Source (跨源验证)

痛点在几个不同平台上被讨论。

- 只在Twitter = ×0.7
- Twitter + Reddit = ×1.0
- 3个源以上 = ×1.3
- 含 HN/ProductHunt = ×1.5（技术社区验证 = 更强信号）

### Layer 4: Market Proof (数据验证)

有没有人已经在为解决这个痛点付费/投资。

- FundBat有相关融资 = +15分
- YC投了相关公司 = +10分
- GitHub有相关项目且 star > 1000 = +10分
- ProductHunt有类似产品且 votes > 100 = +5分

### 最终置信度

```
confidence = min(100, (volume_score × quality_multiplier × cross_source_multiplier) + market_bonus)
```

- confidence < 50: 丢弃
- 50-69: 标记"待验证"
- 70-100: 标记"高置信"

---

## 4. Scoring Pipeline (评分管道)

### 分层评分流程

```
7:00 AM CT — Phase 1: 爬取所有源
  │
  ├── Layer 1 痛点源: Twitter + Reddit + HN Comments + PH Deep
  ├── Layer 2 技术源: GitHub Trending + HN Comments
  └── Layer 3 验证源: FundBat + VC Funding + NewsAPI + RSS + YC + Google Trends
  │
  ▼ 所有数据写入 S3 + DynamoDB
  │
8:00 AM CT — Phase 2: 分析
  │
  ├── Step 1: 对所有新事件生成 embedding (doubao-embedding-vision)
  │   → 存入 Supabase pgvector
  │
  ├── Step 2: 语义聚类
  │   → 余弦相似度 > 0.45 的事件归为同一 "opportunity cluster"
  │
  ├── Step 3: 以痛点为中心做关联
  │   → 每个 cluster 以 pain_signal 为中心
  │   → 关联 Layer 2/3 的验证信号
  │
  ├── Step 4: 痛点验证
  │   → 4层验证引擎计算 confidence
  │   → confidence < 50 丢弃
  │
  ├── Step 5: 综合评分
  │   → pain_score × 55% + tech_score × 30% + timing_score × 15%
  │   → total_score ≥ 70 标记 actionable
  │
  └── Step 6: 写入 Obsidian
      → TrendRadar/YYYY-MM-DD.md
      → 每个 cluster 一个条目，附带打分模板
```

### 评分公式

```
total_score = pain_score × 0.55 + tech_score × 0.30 + timing_score × 0.15
```

| 维度 | 来源 | 模型 |
|------|------|------|
| pain_score | Layer 1 信号 + 验证置信度 | gemma4:31b + 置信度调整 |
| tech_score | Layer 2 信号 | gemma4:31b |
| timing_score | Layer 3 信号 | gemma4:31b |

---

## 5. Data Flow (数据流)

### New/Modified Tables

#### Supabase: `pain_signals` (新表)

```sql
CREATE TABLE pain_signals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pain_text       TEXT NOT NULL,                    -- 原始痛点文本
    source          VARCHAR(50) NOT NULL,             -- twitter_pain / reddit / hackernews
    source_id       VARCHAR(255),                     -- 原始推文/帖子ID
    source_url      TEXT,
    embedding       vector(2048),                     -- doubao-embedding-vision
    confidence      SMALLINT DEFAULT 0 CHECK (confidence BETWEEN 0 AND 100),
    volume_score    SMALLINT DEFAULT 0,
    quality_score   REAL DEFAULT 0,
    cross_source_count SMALLINT DEFAULT 0,
    market_bonus    SMALLINT DEFAULT 0,
    cluster_id      UUID REFERENCES opportunity_clusters(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_pain_signals_confidence ON pain_signals(confidence DESC);
CREATE INDEX idx_pain_signals_embedding ON pain_signals USING ivfflat (embedding vector_cosine_ops);
```

#### Supabase: `opportunity_clusters` (新表)

```sql
CREATE TABLE opportunity_clusters (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,                    -- AI生成的机会标题
    description     TEXT,
    pain_score      SMALLINT CHECK (pain_score BETWEEN 0 AND 100),
    tech_score      SMALLINT CHECK (tech_score BETWEEN 0 AND 100),
    timing_score    SMALLINT CHECK (timing_score BETWEEN 0 AND 100),
    total_score     SMALLINT CHECK (total_score BETWEEN 0 AND 100),
    confidence      SMALLINT CHECK (confidence BETWEEN 0 AND 100),
    is_actionable   BOOLEAN DEFAULT false,
    user_rating     SMALLINT CHECK (user_rating BETWEEN 1 AND 10),  -- 用户反馈
    reasoning       TEXT,
    related_events  JSONB DEFAULT '[]',               -- [{source, event_id, relevance}]
    embedding       vector(2048),                     -- cluster 中心向量
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_clusters_score ON opportunity_clusters(total_score DESC) WHERE is_actionable = true;
CREATE INDEX idx_clusters_embedding ON opportunity_clusters USING ivfflat (embedding vector_cosine_ops);
```

#### DynamoDB: 无变更

沿用现有 trendradar-events 表结构，新增字段：
- `cluster_id`: 关联到 Supabase opportunity_clusters
- `embedding_generated`: boolean，标记是否已生成embedding

---

## 6. Obsidian Output Format

### 每日报告模板

文件路径: `Obsidian Vault/TrendRadar/YYYY-MM-DD.md`

```markdown
# 🎯 TrendRadar 每日信号 — YYYY-MM-DD

## 📊 今日概览
- 新增事件: X 条
- 痛点信号: X 条 (X 条高置信)
- 可行机会: X 条 (score ≥ 70)

---

## 🔥 高价值机会 (score ≥ 70)

### 1. [82分] 法律文档自动摘要/核查
**置信度:** 92/100
**来源:** Twitter(3) + Reddit(1) + HN(1) + FundBat(1)

| 维度 | 分数 | 说明 |
|------|------|------|
| 痛点 | 85 | "I wish there was a tool to auto-summarize legal briefs" — 4人提到 |
| 技术 | 78 | GitHub上有3个相关项目，最大star=2.1k |
| 时机 | 80 | Avantos刚拿$35M融资，市场验证中 |

**AI Reasoning:** 法律文档处理是paralegal最大痛点之一，LLM可直接处理...

**相关信号:**
- 🐦 @user1: "I wish there was..." (62 likes)
- 🔗 GitHub: legal-brief-summarizer (2.1k stars)
- 💰 Avantos ($35M / AI + Fintech)

**你的评分:** __/10
**备注:** ___________

---

### 2. [76分] ...

---

## 🟡 待验证 (confidence 50-69)

### 3. [65分] ...
**置信度:** 55/100 (仅Twitter 1人提到，无跨源验证)
**你的评分:** __/10

---

## 📈 今日统计
| 指标 | 值 |
|------|-----|
| 总事件 | X |
| 痛点信号 | X |
| 高置信痛点 | X |
| 可行机会 | X |
| Layer 1 数据量 | X |
| Layer 2 数据量 | X |
| Layer 3 数据量 | X |
```

### 反馈读取

下次分析运行时：
1. 读取 `TrendRadar/YYYY-MM-DD.md`
2. 解析 `你的评分: X/10` 字段
3. 记录到 Supabase `opportunity_clusters.user_rating`
4. 基于评分数据调整权重（累计10条以上反馈后启动）

---

## 7. Cron Schedule

| 时间 (CT) | 任务 | 说明 |
|-----------|------|------|
| 07:00 | `fetch_all` | 爬取所有15个源，写入S3+DynamoDB |
| 08:00 | `analyze_all` | Embedding → 聚类 → 验证 → 评分 → 写Obsidian |

两个任务独立，fetch失败不影响前一天的数据推送。

---

## 8. New Dependencies

| 包 | 用途 |
|----|------|
| `pgvector` (Supabase extension) | 向量存储和相似度搜索 |
| `beautifulsoup4` | GitHub Trending HTML解析 |
| `pytrends` | Google Trends (已安装) |
| `numpy` | 余弦相似度计算 |

---

## 9. API Quota Budget

| API | 月额度 | 日消耗 | 策略 |
|-----|--------|--------|------|
| twitter-api45 (搜索) | 1,000 | ~15次 | 15个搜索词 × 1次/天 |
| x-twitter-api1 (深度) | 300,000 | ~10次 | 对高价值推文抓评论线程 |
| doubao-embedding-vision | Ark plan | ~200次/天 | 每个新事件生成embedding |
| Crunchbase (RapidAPI) | 20 | ≤1次/天 | 仅对 score≥70 做最终验证 |
| NewsAPI | 免费 | 1次/天 | 拉取最新新闻 |
| FundBat | 免费 | 1次/天 | 爬取融资数据 |

---

## 10. Future Optimization Roadmap

| 优先级 | 优化 | 触发条件 |
|--------|------|---------|
| 🔴 P0 | 用户反馈闭环 | 累计10条以上评分后启动 |
| 🔴 P0 | 时间衰减 | 立即实现：3天前的信号权重 ×0.7，7天前 ×0.3 |
| 🟡 P1 | 回测验证 | 积累3-6个月数据后 |
| 🟡 P1 | 动态搜索词 | 积累50+条验证痛点后 |
| 🟢 P2 | 行业差异化权重 | 按行业积累足够数据后 |
| 🟢 P2 | 情绪分析 | 评估NLP情绪模型后 |

---

## 11. What's Preserved from PRD v2.0

以下完全保留，不做任何修改：

- ✅ 三层存储架构（S3 → DynamoDB → Supabase）
- ✅ CDK基础设施定义
- ✅ 已有的7个数据源（yc, hackernews, producthunt, vc_funding, newsapi, rss, fundbat）
- ✅ DynamoDB事件去重逻辑
- ✅ S3 raw快照存储
- ✅ DLQ死信队列
- ✅ Supabase索引
