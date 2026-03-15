"""
============================================================
PRISM v0.1 — AGENT REGISTRY (20 Agents)
============================================================
Precision Recruitment Intelligence & Scoring Machine
All 20 autonomous agents with lazy imports.

Agent Manifest:
    A-01: Intel Scanner (Hiring Intent Radar)
    A-02: Dark Channel Listener (Telegram/Reddit/X)
    A-03: Primary Scraper (Internshala/Naukri/IIMjobs)
    A-04: ATS Crawler (Greenhouse/Lever/Workday)
    A-05: Ghost Detector (5-Signal Forensic Analyzer)
    A-06: Dedup Engine (6-Layer Duplicate Elimination)
    A-07: Intelligence Enricher (CIRS + Blue Ocean)
    A-08: PPO Optimizer (11-Variable Ranking)
    A-09: Network Mapper (Alumni/HR Discovery)
    A-10: ATS Simulator (1M Context Resume Scanner)
    A-11: Outcome Learner (PPO Weight Retrainer)
    A-12: Telegram Reporter (Command Center)
    A-13: Auto Applier (Portal Submission Engine)
    A-14: Multi-Model Router (AI Traffic Controller)  [PRISM NEW]
    A-15: Email Auto-Applier (Brevo Outreach)         [PRISM NEW]
    A-16: Telegram Group Monitor (Telethon Listener)   [PRISM NEW]
    A-17: Adaptive Scheduler (Dynamic Schedule)        [PRISM NEW]
    A-18: CV Intelligence Enhancer (ATS Tailoring)     [PRISM NEW]
    A-19: Outcome Amplifier (Follow-up Tracker)        [PRISM NEW]
    A-20: Deep Company Intel (Groq Compound Research)  [PRISM NEW]
============================================================
"""

# PRISM v0.1: 20-Agent Registry
AGENT_MANIFEST = {
    'A-01': {'name': 'Intel Scanner', 'module': 'agents.a01_intent_scanner'},
    'A-02': {'name': 'Dark Channel Listener', 'module': 'agents.a02_dark_channel'},
    'A-03': {'name': 'Primary Scraper', 'module': 'agents.a03_primary_scraper'},
    'A-04': {'name': 'ATS Crawler', 'module': 'agents.a04_ats_crawler'},
    'A-05': {'name': 'Ghost Detector', 'module': 'agents.a05_ghost_detector'},
    'A-06': {'name': 'Dedup Engine', 'module': 'agents.a06_dedup_engine'},
    'A-07': {'name': 'Intelligence Enricher', 'module': 'agents.a07_intelligence_enricher'},
    'A-08': {'name': 'PPO Optimizer', 'module': 'agents.a08_ppo_optimizer'},
    'A-09': {'name': 'Network Mapper', 'module': 'agents.a09_network_mapper'},
    'A-10': {'name': 'ATS Simulator', 'module': 'agents.a10_ats_simulator'},
    'A-11': {'name': 'Outcome Learner', 'module': 'agents.a11_outcome_learner'},
    'A-12': {'name': 'Telegram Reporter', 'module': 'agents.a12_telegram_reporter'},
    'A-13': {'name': 'Auto Applier', 'module': 'agents.a13_auto_apply'},
    'A-14': {'name': 'Multi-Model Router', 'module': 'agents.a14_multi_model_router'},
    'A-15': {'name': 'Email Auto-Applier', 'module': 'agents.a15_email_applier'},
    'A-16': {'name': 'Telegram Group Monitor', 'module': 'agents.a16_tg_listener'},
    'A-17': {'name': 'Adaptive Scheduler', 'module': 'agents.a17_scheduler'},
    'A-18': {'name': 'CV Intelligence Enhancer', 'module': 'agents.a18_cv_enhancer'},
    'A-19': {'name': 'Outcome Amplifier', 'module': 'agents.a19_outcome_amplifier'},
    'A-20': {'name': 'Deep Company Intel', 'module': 'agents.a20_company_intel'},
}

TOTAL_AGENTS = len(AGENT_MANIFEST)
PRISM_VERSION = "0.1"
