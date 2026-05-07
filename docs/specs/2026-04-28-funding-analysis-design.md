# Funding Analysis Engine - 设计文档

**日期：** 2026-04-28
**目标：** 从 809 条 funding 数据中提取全部有价值信息，分层输出报告 + 数据入库

---

## 数据格式

```csv
source,title,funding_amount,valuation,category,investors,url,first_seen_at
fundbat,Jump ($105M / -),$105M,-,Artificial Intelligence  Fintech  +1,,https://fundbat.com/company/jump,2026-04-24T21:45:46.204788+00:00
```

**字段说明：**
- `title`: 格式 `"Company ($Amount / $Valuation)"`
- `category`: 多标签，用双空格分隔，可能含 `+1`, `+2` 等噪声标签
- `investors`: 极少有数据（18/809）
- `first_seen_at`: ISO 时间戳

---

## 模块架构

```
~/Projects/TrendRadar/analyzer/funding/
├── __init__.py
├── category_heatmap.py    # 类别热力图
├── big_rounds.py          # 大额融资
├── competitor_watch.py    # 竞品监控
├── emerging_trends.py     # 新兴趋势
├── pricing_anchor.py      # 估值锚点
├── trend_comparison.py    # 趋势对比
└── anomaly_detection.py   # 异常检测

~/Projects/TrendRadar/analyzer/funding_digest.py  # 汇总报告
~/Projects/TrendRadar/storage/funding_db.py       # Supabase 写入
~/Projects/TrendRadar/funding-analysis/            # 报告输出目录
```

---

## 各模块设计

### 1. category_heatmap.py

**输入：** funding.csv
**处理：**
- 解析 category 字段（双空格分隔），过滤噪声标签
- 聚合计数 + 融资金额加权排序
- 热度得分 = 公司数 × 0.6 + 融资总额权重 × 0.4

**输出：**
```json
{
  "heatmap": [
    {"category": "Artificial Intelligence", "count": 298, "total_funding_m": 45000, "heat_score": 87.2}
  ],
  "generated_at": "2026-04-28T02:00:00Z"
}
```

### 2. big_rounds.py

**输入：** funding.csv，threshold_m 参数（默认 50）
**处理：**
- 解析金额字符串（"$105M" → 105, "$4.5B" → 4500）
- 按金额降序，过滤 >= threshold 的公司

**输出：**
```json
{
  "big_rounds": [
    {"company": "GrubMarket", "amount_m": 858, "valuation_b": 4.5, "categories": ["E-Commerce", "AI"], "url": "..."}
  ],
  "threshold_m": 50,
  "total": 23
}
```

### 3. competitor_watch.py

**输入：** funding.csv + keywords 列表
**处理：**
- 匹配 category 字段中的关键词（不区分大小写）
- 按融资金额排序

**输出：**
```json
{
  "matches": [
    {"company": "...", "amount_m": 105, "categories": ["AI", "Fintech"], "url": "..."}
  ],
  "keywords": ["AI", "SaaS"],
  "total_matches": 45
}
```

### 4. emerging_trends.py

**输入：** funding.csv + 时间窗口参数
**处理：**
- 基于 first_seen_at 计算时间窗口
- 统计每个 category 在两个窗口的频率
- 计算增长率

**输出：**
```json
{
  "emerging": [
    {"category": "AI Agents", "this_week": 12, "baseline": 3, "growth_rate": 3.0}
  ]
}
```

### 5. pricing_anchor.py

**输入：** funding.csv
**处理：**
- 按 category 聚合 valuation 数据
- 计算 min/max/avg/median/p25/p75

**输出：**
```json
{
  "anchors": {
    "Artificial Intelligence": {"count": 120, "min_m": 5, "max_m": 4500, "median_m": 45, "p25_m": 15, "p75_m": 120}
  }
}
```

### 6. trend_comparison.py

**输入：** 两个时间点的 heatmap 数据
**处理：**
- 对比两个时间点的 category 热度
- 计算升温/降温幅度

**输出：**
```json
{
  "warming": [{"category": "AI Agents", "change_pct": 150}],
  "cooling": [{"category": "Crypto", "change_pct": -40}],
  "stable": [...]
}
```

### 7. anomaly_detection.py

**输入：** funding.csv + 历史基线
**处理：**
- 建立每个 category 的正常融资频率
- 检测本周偏离基线超过 2σ 的类别

**输出：**
```json
{
  "anomalies": [
    {"category": "AI Agents", "this_week": 45, "baseline_avg": 8.0, "deviation_sigma": 4.2}
  ]
}
```

### 8. funding_digest.py（汇总）

- 调用所有模块
- 组装 Markdown 报告
- 保存到 ~/Projects/TrendRadar/funding-analysis/YYYY-MM-DD.md

### 9. funding_db.py（数据库写入）

- Supabase funding_events 表（每条融资事件）
- funding_snapshots 表（每日快照，用于趋势对比）
- 去重键：company + amount_m + first_seen_at

---

## 注意事项

1. category 字段分隔符是双空格，不是单空格
2. funding_amount 和 valuation 需要解析字符串为数值
3. Investor 数据缺失严重，competitor_watch 可能大部分时间没有输出
4. first_seen_at 包含时区信息，处理时注意时区转换
5. 不要重启 gateway，不要删除文件，不要发送外部消息
6. 每次修改后验证 Python 语法：python3 -c "import ast; ast.parse(open('file').read())"
