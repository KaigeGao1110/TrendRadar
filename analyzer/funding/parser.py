"""
Funding Analysis Engine - 共享解析工具

金额解析："$105M" → 105.0, "$4.5B" → 4500.0, "-" → 0.0
类别解析：双空格分隔，过滤噪声标签（+1, +2 等）
标题解析："Jump ($105M / -)" → company="Jump", amount=105.0
"""

import re
from typing import Optional


# 噪声标签模式：+1, +2, +3 等
NOISE_LABEL_RE = re.compile(r"^\+\d+$")


def parse_amount(amount_str: str) -> float:
    """
    解析金额字符串为百万美元数值。

    Examples:
        "$105M" → 105.0
        "$4.5B" → 4500.0
        "$1.2M" → 1.2
        "-" → 0.0
        "" → 0.0
    """
    if not amount_str or amount_str.strip() == "-":
        return 0.0

    amount_str = amount_str.strip().replace(",", "")

    match = re.match(r"\$?([\d.]+)\s*([MBK]?)", amount_str, re.IGNORECASE)
    if not match:
        return 0.0

    try:
        value = float(match.group(1))
    except ValueError:
        return 0.0
    unit = match.group(2).upper()

    if unit == "B":
        return value * 1000.0  # billions → millions
    elif unit == "K":
        return value / 1000.0  # thousands → millions
    elif unit == "M":
        return value
    else:
        return value  # assume millions if no unit


def parse_valuation(val_str: str) -> float:
    """解析估值字符串，返回百万美元。跳过 ticker 符号（NASDAQ/NYSE等）。"""
    if not val_str or val_str.strip() == "-":
        return 0.0
    
    val_str = val_str.strip()
    
    # Skip ticker symbols like "NASDAQ: MNTS", "NYSE: BOX"
    if re.match(r"^(NASDAQ|NYSE|LSE|TSX):", val_str, re.IGNORECASE):
        return 0.0
    
    return parse_amount(val_str)


def parse_categories(category_str: str) -> list[str]:
    """
    解析 category 字段（双空格分隔），过滤噪声标签。

    Examples:
        "Artificial Intelligence  Fintech  +1" → ["Artificial Intelligence", "Fintech"]
        "Climate Tech  SaaS" → ["Climate Tech", "SaaS"]
    """
    if not category_str or category_str.strip() == "-":
        return []

    parts = category_str.split("  ")  # 双空格分隔
    categories = []
    for part in parts:
        part = part.strip()
        if part and not NOISE_LABEL_RE.match(part):
            categories.append(part)

    return categories


def parse_title(title: str) -> dict:
    """
    解析标题字符串。

    Examples:
        "Jump ($105M / -)" → {"company": "Jump", "amount_m": 105.0, "valuation_m": 0.0}
        "GrubMarket ($858M / $4.5B)" → {"company": "GrubMarket", "amount_m": 858.0, "valuation_m": 4500.0}
    """
    if not title:
        return {"company": "", "amount_m": 0.0, "valuation_m": 0.0}

    match = re.match(r"^(.+?)\s*\(([^)]*)\)\s*$", title)
    if not match:
        return {"company": title.strip(), "amount_m": 0.0, "valuation_m": 0.0}

    company = match.group(1).strip()
    amounts_str = match.group(2)

    # Parse "amount / valuation" format
    parts = amounts_str.split("/")
    amount_m = parse_amount(parts[0].strip()) if len(parts) >= 1 else 0.0
    valuation_m = parse_amount(parts[1].strip()) if len(parts) >= 2 else 0.0

    return {
        "company": company,
        "amount_m": amount_m,
        "valuation_m": valuation_m,
    }


def load_funding_csv(csv_path: str) -> list[dict]:
    """
    加载 funding.csv 并解析所有行。

    Returns:
        List of dicts with keys:
            source, title, funding_amount, valuation, category, investors, url, first_seen_at,
            company, amount_m, valuation_m, categories (list)
    """
    import csv
    from datetime import datetime, timezone

    records = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            parsed_title = parse_title(row.get("title", ""))
            record = {
                "source": row.get("source", ""),
                "title": row.get("title", ""),
                "funding_amount": row.get("funding_amount", ""),
                "valuation": row.get("valuation", ""),
                "category": row.get("category", ""),
                "investors": row.get("investors", ""),
                "url": row.get("url", ""),
                "first_seen_at": row.get("first_seen_at", ""),
                "company": parsed_title["company"],
                "amount_m": parse_amount(row.get("funding_amount", "")),
                "valuation_m": parse_valuation(row.get("valuation", "")),
                "categories": parse_categories(row.get("category", "")),
            }

            # Parse timestamp
            if record["first_seen_at"]:
                try:
                    record["first_seen_at_dt"] = datetime.fromisoformat(
                        record["first_seen_at"]
                    )
                except (ValueError, TypeError):
                    record["first_seen_at_dt"] = None
            else:
                record["first_seen_at_dt"] = None

            records.append(record)

    return records
