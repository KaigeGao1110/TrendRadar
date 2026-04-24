# FundBat 数据源调研报告

**调研时间：** 2026-04-24
**结论：** 可行性 **中**（接入方式为 Web Scraping，非 API）

---

## 数据源基本信息

| 项目 | 内容 |
|------|------|
| **官网** | https://fundbat.com/ |
| **GitHub** | ❌ 任务描述中的 `github.com/FundBat` 不存在（404），无独立 GitHub 组织 |
| **数据规模** | 791 家公司 |
| **更新频率** | 每周更新（Weekly updates，网站 meta 确认） |
| **费用** | 完全免费，无需注册 |
| **认证方式** | 无需 API Key |

---

## 数据格式

**无 API，无下载文件。接入方式为 Web Scraping。**

- ❌ 无 REST/GraphQL API
- ❌ 无 CSV/JSON 下载
- ❌ 无 `__NEXT_DATA__` JSON 注入（纯 CSR，非 SSR）
- ✅ 网站公开可爬取（HTML + JavaScript 渲染）
- ✅ 有 Sitemap（`/sitemap-0.xml`），列出了所有公司/投资人/创始人页面 URL

### 关键页面结构

```
https://fundbat.com/companies          # 公司列表
https://fundbat.com/company/{slug}      # 单个公司详情页
https://fundbat.com/investors           # 投资人列表
https://fundbat.com/investor/{slug}    # 单个投资人详情页
https://fundbat.com/categories          # 行业分类
https://fundbat.com/trending-projects   # 趋势项目（GitHub trending 集成）
https://fundbat.com/blog                # 每日融资 Roundup 博客
```

---

## 覆盖字段（从公司详情页可见）

| 字段 | 示例（Harvey） | 可用性 |
|------|--------------|--------|
| 公司名 | Harvey | ✅ |
| 总融资额 | $1.2B | ✅ |
| 融资轮次 | Series C | ✅ |
| 投资人 | a16z, Kleiner Perkins | ✅ |
| 行业分类 | Artificial Intelligence | ✅ |
| 公司状态 | Active / Acquired / IPO | ✅ |
| 总部所在地 | United States | ✅ |
| 最近融资日期 | 从 Round 信息推断 | ✅ |
| 创始人 | 从 `/founder/` 页面获取 | ✅ |

从首页可见数据：
- 公司名 + 总融资额（醒目展示）
- 行业 + 地区
- 公司状态（IPO / Active / Acquired）

---

## 与 TrendRadar 需求匹配度

TrendRadar 的 `vc_funding.py` 目前通过爬取 TechCrunch 页面提取：
- `company`, `amount`, `round`, `investors[]`, `date`, `sector`, `source_url`

**FundBat 可以提供：**
- ✅ 公司名（标准化 slug 格式）
- ✅ 融资金额（总融资）
- ✅ 融资轮次（Seed / Series A / B / C 等）
- ✅ 投资人列表
- ✅ 行业分类（sector）
- ✅ 公司状态（用于过滤活跃公司）

**FundBat 无法提供：**
- ❌ 单次融资的具体日期（仅有 round 类型，无精确日期字段）
- ❌ 每次融资的独立金额（只有公司总融资额）
- ❌ 公司描述 / 产品信息

---

## 接入可行性评估

### 可行性：**中**

**原因：**
1. 数据质量好——791 家高质量科技公司，a16z、Sequoia 等顶级投资机构投的
2. 完全免费，无需配额限制
3. 无 API，需依赖 Web Scraping，维护成本较高
4. 纯 CSR 渲染，爬取需要模拟浏览器（Selenium/Playwright），或解析 JavaScript 加载后的 DOM

### 接入方案

#### 方案 A：Scraping（推荐，用 Playwright）

```python
# sources/fundbat.py
import httpx
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

FUNDBAT_COMPANIES_URL = "https://fundbat.com/companies"

def fetch_fundbat_companies() -> list[dict]:
    """抓取 FundBat 公司列表，带 Playwright 渲染"""
    companies = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(FUNDBAT_COMPANIES_URL, wait_until="networkidle", timeout=30000)
        
        # 等待页面加载完成，滚动触发懒加载
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)
        
        content = page.content()
        browser.close()
    
    soup = BeautifulSoup(content, "html.parser")
    # 解析公司卡片...
    return companies
```

#### 方案 B：Sitemap 遍历 + 单页爬取

```python
import httpx
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET

def fetch_fundbat_sitemap() -> list[str]:
    """获取所有公司 slug"""
    resp = httpx.get("https://fundbat.com/sitemap-0.xml", timeout=15)
    root = ET.fromstring(resp.text)
    namespaces = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    return [loc.text for loc in root.findall('.//ns:loc', namespaces) 
            if '/company/' in loc.text]

def fetch_company_details(slug: str) -> dict:
    """抓取单个公司详情"""
    url = f"https://fundbat.com/company/{slug}"
    resp = httpx.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(resp.text, "html.parser")
    # 解析公司详情...
    return {}
```

#### 方案 C：缓存 + 批量更新

由于 FundBat 更新频率为每周，建议：
- 首次全量爬取 791 家公司
- 每周增量更新（通过 sitemap 顺序或时间戳判断新增）
- 本地 SQLite/Supabase 缓存

```python
FUNDBAT_CACHE_TTL = 7 * 24 * 3600  # 7 天（与 API-STRATEGY.md 一致）
```

---

## 与现有数据源对比

| 维度 | FundBat | Crunchbase (RapidAPI) | Crustdata |
|------|---------|----------------------|-----------|
| 费用 | 免费 | $（20 req/month） | 中等配额 |
| 数量 | 791 家 | 数百万 | 数百万 |
| 数据精度 | 高（精选公司） | 高 | 高 |
| 接入方式 | Web Scraping | API | API |
| 维护成本 | 高（Scraping） | 低 | 低 |
| 更新频率 | 每周 | 不定期 | 不定期 |

FundBat 适合作为 **Crunchbase 的精选免费替代品**，用于覆盖高质量创业公司的融资数据。

---

## 行动建议

1. **短期（立即可做）：** 用 Playwright 写一个 `fundbat.py` source，抓取 791 家公司基础数据（公司名、总融资额、轮次、投资人），存入 Supabase
2. **中期：** 实现 Sitemap 增量更新，每周跑一次 cron
3. **长期：** 如果 FundBat 推出 API（目前没有），切换到 API 获取，降低维护成本
4. **监控风险：** FundBat 如改版，Scraping 代码需要同步更新，需要告警机制

---

*调研结论：FundBat 是高质量免费融资数据源，数据格式完全可用，但无 API 接口，需通过 Web Scraping 接入，维护成本中等。建议作为 Tier 2 数据源，与 Crustdata 互补使用。*
