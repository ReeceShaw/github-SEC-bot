#!/usr/bin/env python3
"""
GitHub 热门项目推送机器人
每天 8:00 / 18:00 自动获取 AI、红队、渗透测试领域最新热门项目
通过 PushPlus 推送到微信（含 AI 中文摘要 + 运行日志）
"""

import os
import time
import requests
from datetime import datetime, timedelta
from html import escape

# ========== 配置 ==========
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_URL = "https://www.pushplus.plus/send"
GITHUB_TOKEN = os.environ.get("GH_TOKEN", "")  # 注意：用 GH_TOKEN，不是 GITHUB_TOKEN
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"

# 搜索主题配置
TOPICS = [
    {
        "name": "🔓 渗透测试",
        "query": "pentest OR exploit OR vulnerability",
    },
    {
        "name": "🔴 红队工具",
        "query": "redteam OR c2 OR lateral-movement",
    },
    {
        "name": "🤖 AI / 人工智能",
        "query": "LLM OR transformer OR RAG",
    },
]

MAX_PER_TOPIC = 5        # 每个主题最多推送项目数
LOOKBACK_DAYS = 7        # 搜索最近 N 天的项目
API_DELAY = 3            # 每次 API 请求间隔（秒），防止触发限速

# ========== GitHub 搜索 ==========

def search_github(query, per_page=5):
    """通过 GitHub Search API 搜索项目"""
    since_date = (datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    full_query = f"{query} created:>{since_date}"

    url = "https://api.github.com/search/repositories"
    params = {
        "q": full_query,
        "sort": "stars",
        "order": "desc",
        "per_page": per_page,
    }
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "github-topic-bot",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json().get("items", [])
    except requests.RequestException as e:
        print(f"⚠️ 搜索失败 [{query[:30]}...]: {e}")
        return []


# ========== AI 摘要 ==========

def generate_summary(project):
    """调用 DeepSeek API 为项目生成一句话中文摘要"""
    if not DEEPSEEK_API_KEY:
        return ""

    name = project.get("full_name", "")
    desc = project.get("description", "") or "无描述"
    lang = project.get("language", "") or "未知"
    topics = ", ".join(project.get("topics", [])[:5]) or "无标签"

    prompt = (
        f"你是一个网络安全和AI领域的技术专家。请根据以下 GitHub 项目信息，"
        f"用一句简洁的中文（30字以内）概括这个项目的核心用途和亮点，"
        f"帮助安全研究人员快速判断是否值得关注。\n\n"
        f"项目名：{name}\n"
        f"描述：{desc}\n"
        f"语言：{lang}\n"
        f"标签：{topics}\n\n"
        f"请直接输出摘要，不要加引号或前缀。"
    )

    try:
        resp = requests.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            },
            json={
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": "你是安全与AI领域的技术分析师，擅长用一句话精准概括开源项目价值。",
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 100,
                "stream": False,
            },
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        summary = result["choices"][0]["message"]["content"].strip()
        return summary
    except Exception as e:
        print(f"   ⚠️ AI 摘要生成失败: {e}")
        return ""


# ========== 格式化 ==========

def format_projects(projects):
    """将项目列表格式化为 HTML（含 AI 摘要）"""
    if not projects:
        return "<p>本周暂无新项目</p>"

    html = ""
    for p in projects:
        name = escape(p.get("full_name", "Unknown"))
        link = p.get("html_url", "#")
        desc = escape(p.get("description", "") or "暂无描述")
        lang = escape(p.get("language", "") or "未知")
        stars = p.get("stargazers_count", 0)
        forks = p.get("forks_count", 0)
        created = p.get("created_at", "")[:10]

        print(f"   🤖 正在为 {name} 生成 AI 摘要...")
        ai_summary = generate_summary(p)
        summary_html = ""
        if ai_summary:
            summary_html = (
                f'<p style="color:#d73a49;font-weight:bold;">'
                f'💡 AI 解读：{escape(ai_summary)}</p>'
            )

        topics = p.get("topics", [])
        tags_html = ""
        if topics:
            tags = " ".join(
                f'<span style="background:#e1e4e8;padding:2px 6px;'
                f'border-radius:3px;font-size:12px;margin-right:4px;">'
                f'{escape(t)}</span>'
                for t in topics[:5]
            )
            tags_html = f"<p>🏷️ {tags}</p>"

        html += f"""
        <h3>⭐ {stars} | <a href="{link}">{name}</a></h3>
        {summary_html}
        <p>📝 {desc}</p>
        <p>💻 {lang} &nbsp;|&nbsp; 🍴 Forks: {forks} &nbsp;|&nbsp; 📅 创建于: {created}</p>
        {tags_html}
        <hr/>
        """

    return html


def build_message(results, stats, total_time):
    """组装完整推送内容（含运行摘要）"""
    today = datetime.now().strftime("%Y-%m-%d %H:%M")

    # --- 头部 ---
    html = f"<h2>📡 GitHub 安全 & AI 项目日报</h2>"
    html += f"<p>📅 {today} &nbsp;|&nbsp; 搜索窗口: 最近 {LOOKBACK_DAYS} 天</p>"

    # --- 运行摘要卡片 ---
    html += '<div style="background:#f6f8fa;padding:12px 16px;border-radius:8px;margin:12px 0;">'
    html += "<h3 style='margin-top:0;'>📊 本次运行摘要</h3>"
    for s in stats:
        emoji = "✅" if s["found"] > 0 else "⚠️"
        html += (
            f"<p style='margin:4px 0;'>{emoji} {s['name']}："
            f"找到 <b>{s['found']}</b> 个项目"
        )
        if s["duration"] > 0:
            html += f" | ⏱️ {s['duration']}s"
        html += "</p>"

    ai_status = "✅ 已生成" if DEEPSEEK_API_KEY else "❌ 未启用"
    html += f"<p style='margin:4px 0;'>🤖 AI 摘要：{ai_status}</p>"
    html += f"<p style='margin:4px 0;'>⏱️ 总耗时：<b>{total_time:.1f}s</b></p>"
    html += "</div>"

    html += "<hr/>"

    # --- 各项目详情 ---
    for topic_name, projects_html in results:
        html += f"<h2>{topic_name}</h2>"
        html += projects_html

    ai_note = "（含 AI 中文摘要）" if DEEPSEEK_API_KEY else ""
    html += f"<p><em>由 GitHub Actions 自动推送{ai_note} · 数据来自 GitHub Search API</em></p>"

    return html


# ========== 推送 ==========

def send_to_wechat(title, content):
    """通过 PushPlus 推送到微信"""
    if not PUSHPLUS_TOKEN:
        print("❌ PushPlus Token 未配置，跳过推送")
        return False

    data = {
        "token": PUSHPLUS_TOKEN,
        "title": title,
        "content": content,
        "template": "html",
    }
    try:
        resp = requests.post(PUSHPLUS_URL, json=data, timeout=30)
        result = resp.json()
        if result.get("code") == 200:
            print(f"✅ 推送成功！流水号：{result.get('data')}")
            return True
        else:
            print(f"❌ 推送失败：{result}")
            return False
    except Exception as e:
        print(f"❌ 推送异常：{e}")
        return False


# ========== 主流程 ==========

if __name__ == "__main__":
    overall_start = time.time()

    print("=" * 50)
    print("🚀 GitHub 热门项目推送任务启动")
    print(f"时间窗口: 最近 {LOOKBACK_DAYS} 天")
    print(f"AI 摘要: {'已启用 (' + DEEPSEEK_MODEL + ')' if DEEPSEEK_API_KEY else '未配置，跳过'}")
    print(f"推送目标: {'PushPlus 微信' if PUSHPLUS_TOKEN else '未配置'}")
    print("=" * 50)

    results = []
    stats = []

    for topic in TOPICS:
        topic_start = time.time()
        print(f"\n🔍 搜索: {topic['name']}")
        projects = search_github(topic["query"], per_page=MAX_PER_TOPIC)
        print(f"   找到 {len(projects)} 个项目")

        duration = round(time.time() - topic_start, 1)

        stats.append({
            "name": topic["name"],
            "found": len(projects),
            "duration": duration,
        })

        projects_html = format_projects(projects)
        results.append((topic["name"], projects_html))

        time.sleep(API_DELAY)  # API 限速保护

    total_time = time.time() - overall_start

    # 构建并推送消息
    title = f"安全&AI项目日报 ({datetime.now().strftime('%m-%d %H:%M')})"
    content = build_message(results, stats, total_time)

    send_to_wechat(title, content)

    print(f"\n⏱️ 总耗时: {total_time:.1f}s")
    print("🎉 全部完成！")
