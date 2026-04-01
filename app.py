import streamlit as st
import sqlite3
import json
import pandas as pd
import plotly.express as px
import google.generativeai as genai
import asyncio
import os
import re
import subprocess
import sys
from datetime import datetime

# ──────────────────────────────────────────────────────────────
# 🛠️ SYSTEM BOOTSTRAP: Playwright Bypass
# ──────────────────────────────────────────────────────────────
def bootstrap_environment():
    """Manually installs Chromium to bypass Streamlit Cloud apt-get errors."""
    if os.environ.get("STREAMLIT_RUNTIME_ENV") == "cloud":
        marker_file = "/home/appuser/.playwright_installed"
        if not os.path.exists(marker_file):
            with st.spinner("Initializing Environment (This happens only once)..."):
                try:
                    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
                    with open(marker_file, "w") as f: f.write("done")
                except Exception as e:
                    st.error(f"Boot Error: {e}")

bootstrap_environment()

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

# ──────────────────────────────────────────────────────────────
# 🎨 UI & THEME
# ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="PFAS RegWatch | O&G Intel", page_icon="⚗️", layout="wide")

THEME_CSS = """
<style>
    .stApp { background-color: #05090f; color: #f0f6ff; }
    [data-testid="stMetricValue"] { color: #00d4ff !important; font-family: 'monospace'; }
    .stTabs [data-baseweb="tab-list"] { background-color: #0d1528; border-bottom: 1px solid #1e293b; }
    .main-header { color: #ffaa00; font-weight: bold; border-left: 4px solid #ffaa00; padding-left: 15px; }
</style>
"""

# ──────────────────────────────────────────────────────────────
# 🗄️ DATABASE
# ──────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect("pfas_intel_v2.db", check_same_thread=False)
    conn.execute('''CREATE TABLE IF NOT EXISTS regulations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, country TEXT, state TEXT, 
        title TEXT, summary TEXT, type TEXT, status TEXT, score INTEGER, 
        source_url TEXT, verified INTEGER DEFAULT 0, audit_notes TEXT)''')
    conn.commit()
    return conn

db_conn = init_db()

# ──────────────────────────────────────────────────────────────
# 🤖 AGENTIC LOGIC (GEMINI)
# ──────────────────────────────────────────────────────────────
def get_gemini(is_pro=False):
    api_key = st.secrets.get("GEMINI_API_KEY") or st.sidebar.text_input("Gemini API Key", type="password")
    if not api_key: return None
    genai.configure(api_key=api_key)
    return genai.GenerativeModel('gemini-1.5-pro' if is_pro else 'gemini-1.5-flash')

async def run_scrape(url):
    async with AsyncWebCrawler(config=BrowserConfig(headless=True)) as crawler:
        result = await crawler.arun(url=url, config=CrawlerRunConfig(cache_mode=CacheMode.BYPASS))
        return result.markdown if result.success else None

def extract_intel(content):
    model = get_gemini()
    if not model: return []
    prompt = f"""Identify PFAS regulations for Oil & Gas (AFFF, Produced Water, Fracking). 
    Return a JSON list: [{{"country": "...", "state": "...", "title": "...", "summary": "...", "type": "...", "status": "...", "score": 0-100}}]
    Text: {content[:10000]}"""
    try:
        res = model.generate_content(prompt)
        match = re.search(r'\[.*\]', res.text, re.DOTALL)
        return json.loads(match.group()) if match else []
    except: return []

# ──────────────────────────────────────────────────────────────
# 🚀 APP INTERFACE
# ──────────────────────────────────────────────────────────────
def main():
    st.markdown(THEME_CSS, unsafe_allow_html=True)
    st.sidebar.title("⚗️ PFAS O&G Portal")
    page = st.sidebar.radio("Navigation", ["Dashboard", "Scraper Agent", "Q&A Assistant", "Audit Agent", "Database"])

    if page == "Dashboard":
        st.markdown('<h1 class="main-header">PFAS O&G Regulatory Impact</h1>', unsafe_allow_html=True)
        df = pd.read_sql("SELECT * FROM regulations", db_conn)
        if not df.empty:
            c1, c2 = st.columns([2, 1])
            with c1:
                fig = px.choropleth(df, locations="state", locationmode="USA-states", color="score", scope="usa", color_continuous_scale="Reds", title="Regional Risk Score")
                fig.update_layout(geo=dict(bgcolor='rgba(0,0,0,0)'), paper_bgcolor='rgba(0,0,0,0)', font_color="white")
                st.plotly_chart(fig, use_container_width=True)
            with c2:
                st.metric("Total Records", len(df))
                st.write("### Impact Distribution")
                st.bar_chart(df['status'].value_counts())
        else:
            st.info("System Ready. Please run the Scraper Agent to populate data.")

    elif page == "Scraper Agent":
        st.title("🕷️ Agent 1: Intelligence Scraper")
        target = st.text_input("Enter Gov/EPA URL", placeholder="https://www.epa.gov/pfas...")
        if st.button("Start Extraction"):
            with st.status("Gathering Intelligence...") as s:
                raw = asyncio.run(run_scrape(target))
                if raw:
                    data = extract_intel(raw)
                    for i in data:
                        db_conn.execute("INSERT INTO regulations (country,state,title,summary,type,status,score,source_url) VALUES (?,?,?,?,?,?,?,?)",
                                       (i.get('country'), i.get('state'), i.get('title'), i.get('summary'), i.get('type'), i.get('status'), i.get('score'), target))
                    db_conn.commit()
                    s.update(label=f"Captured {len(data)} regulations!", state="complete")
                    st.success("Database populated successfully.")

    elif page == "Q&A Assistant":
        st.title("💬 Q&A Assistant")
        query = st.text_input("Ask about PFAS O&G compliance...")
        if query:
            model = get_gemini()
            df = pd.read_sql("SELECT * FROM regulations", db_conn)
            context = df.to_string()
            response = model.generate_content(f"Answer this query based on the data: {query}\n\nData Context: {context}")
            st.markdown(response.text)

    elif page == "Audit Agent":
        st.title("🔍 Agent 2: Verification Auditor")
        df = pd.read_sql("SELECT * FROM regulations WHERE verified = 0", db_conn)
        if not df.empty:
            choice = st.selectbox("Record to Audit", df['title'])
            if st.button("Run Compliance Audit"):
                model = get_gemini(is_pro=True)
                report = model.generate_content(f"Verify accuracy for this record: {choice}").text
                st.markdown(report)
                if st.button("Mark Verified"):
                    db_conn.execute("UPDATE regulations SET verified=1 WHERE title=?", (choice,))
                    db_conn.commit()
                    st.rerun()
        else: st.success("All records verified.")

    elif page == "Database":
        st.title("🗄️ Metadata Management")
        df = pd.read_sql("SELECT * FROM regulations", db_conn)
        st.data_editor(df, use_container_width=True)

if __name__ == "__main__":
    main()
