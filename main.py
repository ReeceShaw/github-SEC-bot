#!/usr/bin/env python3
"""GitHub 特定主题热门项目 + AI 中文摘要 → 微信推送"""

import os
import time
import requests
from datetime import datetime, timedelta
from html import escape

# ========== 配置 ==========
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_URL = "https://www.pushplus.plus/send"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

# DeepSeek API 配置
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"

# 自定义主题：名称 + 搜索关键词
TOPICS = [
    {
        "name": "🔓 渗透测试",
        "query": "penetration-testing OR pentest OR "
                 "exploit OR vulnerability OR "
                 "web-security OR CTF OR "
                 "payload OR reverse-shell OR "
                 "privilege-escalation",
    },
    {
        "name": "🔴 红队工具",
        "query": "red-team OR redteaming OR "
                 "c2-framework OR command-and-control OR "
                 "beacon OR adversary-simulation OR "
                 "initial-access OR lateral-movement",
    },
    {
        "name": "🤖 AI / 人工智能",
        "query": "LLM OR large-language-model OR "
                 "GPT OR transformer OR "
                 "AI-agent OR RAG OR "
                 "fine-tuning OR diffusion-model",
    },
]

MAX_PER_TOPIC = 5
LOOKBACK_DAYS = 7


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
                    {"role": "system", "content": "你是安全与AI领域的技术分析师，擅长用一句话精准概括开源项目价值。"},
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

        # 生成 AI 中文摘要
        print(f"   🤖 正在为 {name} 生成 AI 摘要...")
        ai_summary = generate_summary(p)
        summary_html = ""
        if ai_summary:
            summary_html = (
                f'<p style="color:#d73a49;font-weight:bold;">'
                f'💡 AI 解读：{escape(ai_summary)}</p>'
            )

        # 标签
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


def build_message(results):
    """组装完整推送内容"""
    today = datetime.now().strftime("%Y-%m-%d")
    html = f"<h2>📡 GitHub 安全 & AI 项目周报</h2>"
    html += f"<p>📅 {today} &nbsp;|&nbsp; 搜索窗口: 最近 {LOOKBACK_DAYS} 天</p><hr/>"

    for topic_name, projects_html in results:
        html += f"<h2>{topic_name}</h2>"
        html += projects_html

    ai_note = "（含 AI 中文摘要）" if DEEPSEEK_API_KEY else ""
    html += f"<p><em>由 GitHub Actions 自动推送{ai_note} · 数据来自 GitHub Search API</em></p>"
    return html


# ========== 推送 ==========

def send_to_wechat(title, content):
    """通过 PushPlus 推送到微信"""
    data = {
        "token": PUSHPLUS_TOKEN,
        "title": title,
        "content": content,
        "template": "html",
    }
    resp = requests.post(PUSHPLUS_URL, json=data, timeout=30)
    result = resp.json()
    if result.get("code") == 200:
        print(f"✅ 推送成功！流水号：{result.get('data')}")
    else:
        print(f"❌ 推送失败：{result}")


# ========== 主流程 ==========

if __name__ == "__main__":
    print("=" * 50)
    print("开始搜索 GitHub 特定主题项目...")
    print(f"时间窗口: 最近 {LOOKBACK_DAYS} 天")
    print(f"AI 摘要: {'已启用 (' + DEEPSEEK_MODEL + ')' if DEEPSEEK_API_KEY else '未配置，跳过'}")
    print("=" * 50)

    results = []
    for topic in TOPICS:
        print(f"\n🔍 搜索: {topic['name']}")
        projects = search_github(topic["query"], per_page=MAX_PER_TOPIC)
        print(f"   找到 {len(projects)} 个项目")
        projects_html = format_projects(projects)
        results.append((topic["name"], projects_html))

        # GitHub API 限速保护
        time.sleep(6)

    title = f"安全&AI项目周报 ({datetime.now().strftime('%Y-%m-%d')})"
    content = build_message(results)

    send_to_wechat(title, content)
    print("\n🎉 全部完成！")
