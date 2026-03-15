// ============================================================
// LLM CHAT PANEL — PRISM v0.1 Next-Level AI Assistant
// 4 Deep AI Profiles with system awareness, premium animations,
// streaming text, thinking indicators, rich markdown rendering
// ============================================================

import React, { useState, useRef, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X, Send, Sparkles, Bot, User, Trash2,
  Lightbulb, FileText, Shield, BarChart3,
  Briefcase, Target, BookOpen, GraduationCap,
  Zap, Check, Database, AlertCircle, Settings2,
  ChevronDown, Cpu, Activity, Brain, Radar,
  TrendingUp, Award, Clock, Globe, Eye,
  MessageSquare, Search, Layers, Hash
} from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';
import { useLLMChat } from '@/hooks/useHooks';
import { hapticFeedback } from '@/utils/helpers';

// ===== NEXT-LEVEL AI PROFILES — Deep System Awareness =====
const AI_PROFILES = [
  {
    id: 'generalist',
    name: 'PRISM Advisor',
    shortName: 'Advisor',
    icon: Brain,
    color: '#7c3aed',
    gradient: 'linear-gradient(135deg, #7c3aed 0%, #a855f7 50%, #c084fc 100%)',
    glowColor: 'rgba(124,58,237,0.15)',
    description: 'Your personal AI career strategist — scans all 20 PRISM agents, the live job database, your CV, and market signals to deliver precise, actionable career intelligence.',
    tagline: 'PRISM Multi-Agent Intelligence',
    capabilities: [
      'Cross-agent job matching (A-03/A-04/A-08 data)',
      'Ghost detection insights (A-05)',
      'PPO score explanation (A-08)',
      'Blue Ocean opportunity alerts (A-07)',
      'Market momentum analysis (A-01)',
      'Application priority ranking',
    ],
    systemContext: `You are PRISM Advisor — the central AI intelligence of the PRISM system (Precision Recruitment Intelligence & Scoring Machine). You have awareness of:
- 20 autonomous agents running 24/7 finding internships
- PPO scoring engine with 11 variables (company tier, applicant count, stipend, duration, CIRS score, sector momentum, intent signals, historic callback, recency, semantic CV match)
- Blue Ocean detection (high prestige + low competition)
- Ghost job forensics (5-signal detection)
- 12 portal sources: Internshala, Naukri, LinkedIn, IIMjobs, Glassdoor, Greenhouse, Lever, Workday, Wellfound, Indeed, Telegram, Twitter/X
- User's uploaded CV and profile data

You provide strategic career advice backed by real data from the system. Be specific, cite data points, and give actionable steps. Respond in a professional but warm tone. For Indian MBA students at AMU.`,
    aiProviders: ['Groq LLaMA 70B', 'Cerebras Fallback'],
  },
  {
    id: 'resume_builder',
    name: 'Elite Resume Lab',
    shortName: 'Resume',
    icon: FileText,
    color: '#0891b2',
    gradient: 'linear-gradient(135deg, #0891b2 0%, #22d3ee 50%, #67e8f9 100%)',
    glowColor: 'rgba(8,145,178,0.15)',
    description: 'Harvard Business School format expert. Analyzes your CV against ATS requirements, JD keywords, and STAR methodology. Generates tailored cover letters, LinkedIn content, and SOPs.',
    tagline: 'HBS/ISB/IIM Format Expert',
    capabilities: [
      'STAR-format bullet point rewriting',
      'ATS keyword injection from live JDs',
      'HBS/ISB resume format templates',
      'Cover letter for any listing in DB',
      'LinkedIn headline & summary optimizer',
      'SOP drafting with quantified achievements',
    ],
    systemContext: `You are Elite Resume Lab — the CV intelligence engine of the PRISM system. You are an expert in:
- Harvard Business School resume format
- ISB/IIM/XLRI placement document standards
- ATS (Applicant Tracking System) optimization
- STAR format (Situation-Task-Action-Result) with quantified metrics
- Keyword density analysis against live job descriptions
- Cover letter generation tailored to specific companies and roles
- LinkedIn profile optimization for MBA internship seekers

When the user asks about their CV:
1. Reference their uploaded CV content (available in the conversation context)
2. Compare keywords against real job listings from our database
3. Provide SPECIFIC rewrites, not vague suggestions
4. Always quantify: "Increased sales by X%" not "Improved sales"
5. Format responses with clear sections and bullet points`,
    aiProviders: ['Groq LLaMA 70B', 'OpenRouter Gemini 1M'],
  },
  {
    id: 'ats_checker',
    name: 'ATS War Room',
    shortName: 'ATS',
    icon: Target,
    color: '#059669',
    gradient: 'linear-gradient(135deg, #059669 0%, #34d399 50%, #6ee7b7 100%)',
    glowColor: 'rgba(5,150,105,0.15)',
    description: 'Reverse-engineers ATS algorithms used by Greenhouse, Lever, and Workday. Scores your CV against specific JDs with keyword gap analysis and section-by-section optimization.',
    tagline: 'Reverse-Engineer ATS Algorithms',
    capabilities: [
      'ATS score out of 100 (6 sub-scores)',
      'Keyword gap heat map vs top JDs',
      'Section-by-section format audit',
      'Greenhouse/Lever/Workday specific tips',
      'Resume parser simulation',
      'Optimal keyword density calculator',
    ],
    systemContext: `You are ATS War Room — the Applicant Tracking System specialist in the PRISM system. You have deep knowledge of:
- How Greenhouse ATS parses resumes (JSON API format, section detection)
- How Lever ATS scores candidates (keyword matching, experience weighting)
- How Workday ATS filters applications (form fields, resume parsing)
- Common ATS rejection reasons: wrong file format, missing sections, keyword mismatch, non-standard headers

When analyzing a CV:
1. Give a SCORE out of 100 with sub-scores: Keywords (30%), Format (20%), Sections (15%), Experience Relevance (15%), Skills Match (10%), Education (10%)
2. List MISSING critical keywords from the job listings in the database
3. Flag ATS-BREAKING issues: tables, images, fancy fonts, non-standard section names
4. Provide a BEFORE → AFTER rewrite for the weakest sections
5. Compare against the specific ATS platform the target company uses`,
    aiProviders: ['OpenRouter Gemini 1M', 'Groq LLaMA 70B'],
  },
  {
    id: 'career_counselor',
    name: 'MBA Strategy Desk',
    shortName: 'Strategy',
    icon: Briefcase,
    color: '#dc2626',
    gradient: 'linear-gradient(135deg, #dc2626 0%, #f87171 50%, #fca5a5 100%)',
    glowColor: 'rgba(220,38,38,0.15)',
    description: 'India-specific MBA career strategist. Knows AMU/IIM/ISB placement patterns, sector momentum, stipend benchmarks, PPO conversion strategies, and real-time hiring trends from PRISM data.',
    tagline: 'India MBA Placement Specialist',
    capabilities: [
      'AMU/IIM/ISB placement pattern analysis',
      'Sector momentum tracking (PRISM A-01 data)',
      'Stipend benchmark by role & company tier',
      'PPO conversion strategy (week-by-week)',
      'Interview preparation for target company',
      'Career path mapping (short + long term)',
    ],
    systemContext: `You are MBA Strategy Desk — the career counselor in the PRISM system, specialized in Indian MBA internship placements. You know:
- AMU MBA 2025 batch specifics and placement expectations
- IIM/ISB/XLRI/MDI/FMS placement data and benchmarks
- Sector momentum: which industries are actively hiring MBA interns in India (2026)
- Stipend benchmarks by company tier: Elite (McKinsey/Goldman ₹1-2L/mo), Strong MNC (Big 4/TCS ₹50-80k), Indian Unicorn (Zepto/CRED ₹40-60k)
- PPO (Pre-Placement Offer) conversion strategies
- Interview prep for consulting case studies, finance technicals, product management frameworks

When advising:
1. Reference real companies and stipend ranges from the PRISM database
2. Use sector momentum data from A-01 (Intent Scanner) and A-07 (Enricher)
3. Be specific about Indian context: placement season timelines, summer intern windows, PPO processes
4. Give week-by-week action plans, not abstract advice
5. Factor in the user's CV strengths and target companies`,
    aiProviders: ['Groq LLaMA 70B', 'Cerebras Fast'],
  },
];

// ===== PROFILE-SPECIFIC QUICK PROMPTS — Smarter & More Specific =====
const PROFILE_PROMPTS: Record<string, Array<{ icon: React.ReactNode; label: string; prompt: string }>> = {
  generalist: [
    { icon: <Radar className="w-3.5 h-3.5" />, label: 'My top matches', prompt: 'Based on my uploaded CV and profile, analyze the current job database and give me my top 5 matches. For each, explain WHY it matches (skills overlap, company tier, PPO score) and prioritize by application urgency.' },
    { icon: <Eye className="w-3.5 h-3.5" />, label: 'Blue Ocean scan', prompt: 'Run a Blue Ocean scan on the current database. Find listings with high company prestige (Tier 1-2) but low applicant count (<50). These are my golden opportunities — rank them by PPO score and tell me which to apply to TODAY.' },
    { icon: <TrendingUp className="w-3.5 h-3.5" />, label: 'Application strategy', prompt: 'Create a 7-day application battle plan for me. Prioritize by: 1) Blue Ocean opportunities first, 2) High PPO score listings, 3) Listings with upcoming deadlines. Include specific company names and roles from the database.' },
    { icon: <Shield className="w-3.5 h-3.5" />, label: 'Ghost alert', prompt: 'Analyze the current listings for ghost job signals. Which ones have high ghost scores (>50)? What red flags do they show? Which should I absolutely avoid? Give me a clean list of SAFE, high-quality listings.' },
  ],
  resume_builder: [
    { icon: <FileText className="w-3.5 h-3.5" />, label: 'Full CV audit', prompt: 'Run a complete audit on my uploaded CV. Score it in 6 areas: Impact Verbs, Quantification, ATS Keywords, Format/Layout, Section Structure, and Relevance to MBA roles. Give specific BEFORE → AFTER rewrites for the 3 weakest bullets.' },
    { icon: <Zap className="w-3.5 h-3.5" />, label: 'Cover letter', prompt: 'Write a killer cover letter for the highest-paying internship in the database that matches my profile. Use my CV achievements as the foundation. Make it compelling, specific, and under 300 words. Include company-specific research.' },
    { icon: <Target className="w-3.5 h-3.5" />, label: 'STAR rewrites', prompt: 'Take my top 5 experience bullet points from my CV and rewrite each one using perfect STAR format. Each must have: specific Situation, clear Task, detailed Action, and QUANTIFIED Result (%, ₹, #). Make them ATS-optimized.' },
    { icon: <Globe className="w-3.5 h-3.5" />, label: 'LinkedIn makeover', prompt: 'Based on my CV and the job listings I should target, give me: 1) An optimized LinkedIn headline (120 chars), 2) A compelling About section (2000 chars), 3) Top 15 skills to list, 4) A Featured section strategy. Make it recruiter-magnetic.' },
  ],
  ats_checker: [
    { icon: <Target className="w-3.5 h-3.5" />, label: 'Full ATS score', prompt: 'Run a comprehensive ATS analysis on my CV. Score me out of 100 with breakdowns: Keywords (30%), Format (20%), Sections (15%), Experience Relevance (15%), Skills Match (10%), Education (10%). List every missing critical keyword from the top 10 matching jobs.' },
    { icon: <Layers className="w-3.5 h-3.5" />, label: 'Keyword gaps', prompt: 'Extract the top 30 most important keywords from the 10 best matching jobs in the database. Cross-reference with my CV. Show me a keyword gap analysis: ✅ Keywords I have, ❌ Critical keywords I\'m missing, ⚠️ Keywords I should add. Priority order.' },
    { icon: <Search className="w-3.5 h-3.5" />, label: 'Format audit', prompt: 'Check my CV for every possible ATS-breaking issue: 1) Are there tables/columns? 2) Non-standard section headers? 3) Parsing-unfriendly elements? 4) Missing date formats? 5) Correct file structure? Give me a PASS/FAIL for each check with fix instructions.' },
    { icon: <Hash className="w-3.5 h-3.5" />, label: 'Optimize for role', prompt: 'Pick the #1 best matching job from the database for my profile. Show me EXACTLY how to optimize my CV for that specific role: which keywords to add where, which bullets to rewrite, which skills to highlight. Give me a before → after transformation.' },
  ],
  career_counselor: [
    { icon: <Award className="w-3.5 h-3.5" />, label: 'Career roadmap', prompt: 'Based on my CV, skills, and the current market data from PRISM, create a comprehensive career roadmap: 1) Best-fit roles (short-term), 2) Career trajectory (3-5 year), 3) Skills to develop, 4) Target companies in the database, 5) Salary/stipend expectations by tier.' },
    { icon: <BarChart3 className="w-3.5 h-3.5" />, label: 'Stipend intel', prompt: 'Using the current PRISM database and market data: 1) What stipend range should I expect given my profile? 2) How does AMU MBA compare to IIM/ISB for internship stipends? 3) Which sectors pay the most? 4) What can I negotiate? Give specific numbers from the data.' },
    { icon: <Clock className="w-3.5 h-3.5" />, label: 'PPO playbook', prompt: 'Create a detailed week-by-week PPO conversion strategy. Week 1: First impressions. Week 2-3: Demonstrating value. Week 4-8: Building relationships and delivering results. Include specific tactics, communication templates, and common pitfalls for Indian MBA internships.' },
    { icon: <MessageSquare className="w-3.5 h-3.5" />, label: 'Interview prep', prompt: 'Based on the top 3 matching jobs for my profile in the database, prepare me for interviews: 1) Likely questions for each role type, 2) Framework answers (STAR/case study), 3) Company-specific research points, 4) Questions I should ask, 5) Red flags to watch for.' },
  ],
};

// ===== MARKDOWN RENDERER =====
function renderFormattedText(text: string): React.ReactNode {
  if (!text) return null;

  let cleaned = text
    .replace(/^#{1,6}\s*/gm, '')
    .replace(/\*\*\*(.+?)\*\*\*/g, '<bi>$1</bi>')
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/\*(.+?)\*/g, '<i>$1</i>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .trim();

  const blocks = cleaned.split('\n\n').filter(Boolean);

  return (
    <div className="chat-markdown space-y-2">
      {blocks.map((block, blockIdx) => {
        const lines = block.split('\n').filter(Boolean);
        const isListBlock = lines.every(l => /^(\s*[-*]\s|^\s*\d+[.)]\s)/.test(l));

        if (isListBlock) {
          return (
            <ul key={blockIdx} className="space-y-1 ml-1">
              {lines.map((line, lineIdx) => (
                <li key={lineIdx} className="flex items-start gap-2 text-xs leading-relaxed">
                  <span className="w-1 h-1 rounded-full bg-current opacity-50 mt-1.5 flex-shrink-0" />
                  <span dangerouslySetInnerHTML={{ __html: line.replace(/^\s*[-*]\s*/, '').replace(/^\s*\d+[.)]\s*/, '') }} />
                </li>
              ))}
            </ul>
          );
        }

        return (
          <p key={blockIdx} className="text-xs leading-relaxed">
            {lines.map((line, lineIdx) => (
              <React.Fragment key={lineIdx}>
                {lineIdx > 0 && <br />}
                <span dangerouslySetInnerHTML={{ __html: line }} />
              </React.Fragment>
            ))}
          </p>
        );
      })}
    </div>
  );
}

// ===== STREAMING TEXT =====
function StreamingText({ text, isComplete }: { text: string; isComplete: boolean }) {
  const [displayedLength, setDisplayedLength] = useState(0);
  const fullLength = text.length;

  useEffect(() => {
    if (isComplete) {
      setDisplayedLength(fullLength);
      return;
    }

    const speed = 6;
    const interval = setInterval(() => {
      setDisplayedLength(prev => {
        if (prev >= fullLength) {
          clearInterval(interval);
          return fullLength;
        }
        const jump = Math.min(4, fullLength - prev);
        return prev + jump;
      });
    }, speed);

    return () => clearInterval(interval);
  }, [text, isComplete, fullLength]);

  const displayedText = text.slice(0, displayedLength);
  const isStreaming = displayedLength < fullLength;

  return (
    <div className="relative">
      {renderFormattedText(displayedText)}
      {isStreaming && (
        <span className="inline-block w-0.5 h-3.5 bg-current opacity-70 ml-0.5 animate-blink align-middle" />
      )}
    </div>
  );
}

// ===== THINKING INDICATOR — Premium =====
function ThinkingIndicator({ profileColor, profileName }: { profileColor: string; profileName: string }) {
  const [dots, setDots] = useState(1);
  const [thinkingPhase, setThinkingPhase] = useState(0);

  const phases = [
    'Connecting to PRISM agents',
    'Scanning job database',
    'Analyzing your profile',
    'Generating intelligence',
  ];

  useEffect(() => {
    const dotInterval = setInterval(() => setDots(d => d >= 3 ? 1 : d + 1), 500);
    const phaseInterval = setInterval(() => setThinkingPhase(p => (p + 1) % phases.length), 2000);
    return () => { clearInterval(dotInterval); clearInterval(phaseInterval); };
  }, []);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex items-start gap-2.5"
    >
      <div
        className="flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center"
        style={{ background: `linear-gradient(135deg, ${profileColor} 0%, ${profileColor}aa 100%)` }}
      >
        <Bot className="w-3.5 h-3.5 text-white" />
      </div>
      <div className="chat-bubble-ai">
        <div className="flex flex-col gap-2">
          <div className="thinking-dots">
            <span className="thinking-dot" style={{ animationDelay: '0ms', backgroundColor: profileColor }} />
            <span className="thinking-dot" style={{ animationDelay: '150ms', backgroundColor: profileColor }} />
            <span className="thinking-dot" style={{ animationDelay: '300ms', backgroundColor: profileColor }} />
          </div>
          <div className="flex items-center gap-1.5">
            <Activity className="w-3 h-3 animate-pulse" style={{ color: profileColor }} />
            <span className="text-[10px] text-primary-400 font-medium">
              {phases[thinkingPhase]}{'.'.repeat(dots)}
            </span>
          </div>
        </div>
      </div>
    </motion.div>
  );
}

// ===== CONFIGURATION PANEL — Enhanced =====
function ConfigPanel({ profile, onClose }: { profile: typeof AI_PROFILES[0]; onClose: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: -8, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -8, scale: 0.98 }}
      transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
      className="mx-4 mb-2 p-3.5 bg-white rounded-xl"
      style={{
        border: '1px solid rgba(229,231,235,0.7)',
        boxShadow: '0 4px 24px rgba(0,0,0,0.06), 0 1px 3px rgba(0,0,0,0.03)',
      }}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div
            className="w-6 h-6 rounded-lg flex items-center justify-center"
            style={{ background: profile.color + '12' }}
          >
            <Settings2 className="w-3 h-3" style={{ color: profile.color }} />
          </div>
          <span className="text-[11px] font-bold text-primary-800">{profile.name}</span>
        </div>
        <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-primary-50 transition-colors">
          <X className="w-3.5 h-3.5 text-primary-400" />
        </button>
      </div>

      {/* AI Provider Info */}
      <div className="flex items-center gap-3 mb-3 p-2.5 rounded-lg" style={{ background: '#f8f9fa' }}>
        {profile.aiProviders.map((provider, i) => (
          <div key={i} className="flex items-center gap-1.5">
            <Cpu className="w-3 h-3" style={{ color: i === 0 ? profile.color : '#9ca3af' }} />
            <span className="text-[10px] font-medium" style={{ color: i === 0 ? '#374151' : '#9ca3af' }}>
              {i === 0 ? 'Primary' : 'Fallback'}: {provider}
            </span>
          </div>
        ))}
      </div>

      {/* Capabilities — scrollable */}
      <div className="space-y-1.5 mb-3">
        <span className="text-[9px] font-bold uppercase tracking-wider text-primary-400">Capabilities</span>
        <div className="flex flex-wrap gap-1.5">
          {profile.capabilities.map((cap, i) => (
            <span key={i} className="text-[9px] font-semibold px-2 py-0.5 rounded-md"
              style={{ background: profile.color + '08', color: profile.color, border: `1px solid ${profile.color}15` }}>
              {cap}
            </span>
          ))}
        </div>
      </div>

      {/* Connection Status */}
      <div className="flex items-center gap-2 p-2 rounded-lg" style={{ background: '#ecfdf5' }}>
        <Database className="w-3.5 h-3.5 text-emerald-500" />
        <span className="text-[10px] font-medium text-emerald-700">Connected to Supabase + 20 PRISM Agents</span>
        <span className="ml-auto w-2 h-2 bg-emerald-400 rounded-full" style={{ boxShadow: '0 0 6px rgba(52,211,153,0.5)' }} />
      </div>
    </motion.div>
  );
}

// ===== MAIN LLM PANEL =====
export default function LLMPanel() {
  const { isLLMPanelOpen, setLLMPanelOpen, llmMessages, clearLLMChat } = useAppStore();
  const { sendMessage, isLoading } = useLLMChat();
  const [input, setInput] = useState('');
  const [activeProfile, setActiveProfile] = useState('generalist');
  const [showConfig, setShowConfig] = useState(false);
  const [completedMsgIds, setCompletedMsgIds] = useState<Set<string>>(new Set());
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const currentProfile = AI_PROFILES.find(p => p.id === activeProfile) || AI_PROFILES[0];
  const currentPrompts = PROFILE_PROMPTS[activeProfile] || PROFILE_PROMPTS.generalist;

  // Auto-scroll
  useEffect(() => {
    const timer = setTimeout(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, 100);
    return () => clearTimeout(timer);
  }, [llmMessages, isLoading]);

  // Mark messages as completed after streaming
  useEffect(() => {
    if (llmMessages.length > 0) {
      const timer = setTimeout(() => {
        setCompletedMsgIds(prev => {
          const next = new Set(prev);
          llmMessages.forEach(msg => {
            if (msg.role === 'assistant') {
              next.add(msg.id);
            }
          });
          return next;
        });
      }, (llmMessages[llmMessages.length - 1]?.content?.length || 100) * 6 + 500);
      return () => clearTimeout(timer);
    }
  }, [llmMessages]);

  // Mark user messages as completed immediately
  useEffect(() => {
    setCompletedMsgIds(prev => {
      const next = new Set(prev);
      llmMessages.filter(m => m.role === 'user').forEach(m => next.add(m.id));
      return next;
    });
  }, [llmMessages]);

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed || isLoading) return;
    sendMessage(trimmed, activeProfile);
    setInput('');
    hapticFeedback('light');
    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
    }
  };

  const handleQuickPrompt = (prompt: string) => {
    sendMessage(prompt, activeProfile);
    hapticFeedback('light');
  };

  const handleProfileChange = (profileId: string) => {
    setActiveProfile(profileId);
    setShowConfig(false);
    hapticFeedback('medium');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 100) + 'px';
  };

  if (!isLLMPanelOpen) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.2 }}
        className="fixed inset-0 z-[60] bg-black/30 backdrop-blur-sm"
        onClick={() => setLLMPanelOpen(false)}
      >
        <motion.div
          initial={{ y: '100%' }}
          animate={{ y: 0 }}
          exit={{ y: '100%' }}
          transition={{ type: 'spring', damping: 32, stiffness: 350 }}
          className="absolute bottom-0 left-0 right-0 bg-white rounded-t-3xl flex flex-col"
          style={{
            height: '92vh',
            maxHeight: '92vh',
            boxShadow: '0 -8px 48px rgba(0,0,0,0.12), 0 -2px 8px rgba(0,0,0,0.06)',
          }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* Handle */}
          <div className="flex justify-center pt-3 pb-1 flex-shrink-0">
            <div className="w-10 h-1 rounded-full" style={{ background: '#e5e7eb' }} />
          </div>

          {/* Header */}
          <div className="px-4 py-2 flex-shrink-0" style={{ borderBottom: '1px solid rgba(229,231,235,0.5)' }}>
            <div className="flex items-center justify-between mb-2.5">
              <div className="flex items-center gap-2.5">
                <motion.div
                  className="w-10 h-10 rounded-xl flex items-center justify-center"
                  style={{
                    background: currentProfile.gradient,
                    boxShadow: `0 4px 16px ${currentProfile.color}30`,
                  }}
                  key={currentProfile.id}
                  initial={{ scale: 0.8, rotate: -10 }}
                  animate={{ scale: 1, rotate: 0 }}
                  transition={{ type: 'spring', stiffness: 400, damping: 15 }}
                >
                  <currentProfile.icon className="w-5 h-5 text-white" />
                </motion.div>
                <div>
                  <h2 className="text-sm font-bold text-primary-900 tracking-tight">{currentProfile.name}</h2>
                  <p className="text-[10px] font-medium" style={{ color: currentProfile.color }}>
                    {currentProfile.tagline}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-1">
                <motion.button
                  onClick={() => { setShowConfig(!showConfig); hapticFeedback('light'); }}
                  className={`p-2 rounded-xl transition-colors ${showConfig ? 'bg-primary-100' : 'hover:bg-primary-50'}`}
                  whileTap={{ scale: 0.9 }}
                >
                  <Settings2 className="w-4 h-4 text-primary-400" />
                </motion.button>
                <motion.button
                  onClick={() => { clearLLMChat(); setCompletedMsgIds(new Set()); hapticFeedback('light'); }}
                  className="p-2 rounded-xl hover:bg-primary-50 transition-colors"
                  whileTap={{ scale: 0.9 }}
                >
                  <Trash2 className="w-4 h-4 text-primary-300" />
                </motion.button>
                <motion.button
                  onClick={() => setLLMPanelOpen(false)}
                  className="p-2 rounded-xl hover:bg-primary-50 transition-colors"
                  whileTap={{ scale: 0.9 }}
                >
                  <X className="w-5 h-5 text-primary-400" />
                </motion.button>
              </div>
            </div>

            {/* Profile Toggle Chips — Premium */}
            <div className="flex gap-1.5 overflow-x-auto scrollbar-none pb-1">
              {AI_PROFILES.map((profile) => {
                const isActive = activeProfile === profile.id;
                const ProfileIcon = profile.icon;
                return (
                  <motion.button
                    key={profile.id}
                    onClick={() => handleProfileChange(profile.id)}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold whitespace-nowrap ${
                      isActive
                        ? 'text-white'
                        : 'text-primary-500 hover:text-primary-700'
                    }`}
                    style={{
                      background: isActive ? profile.gradient : '#f3f4f6',
                      boxShadow: isActive ? `0 2px 12px ${profile.color}25` : 'none',
                      border: isActive ? 'none' : '1px solid rgba(229,231,235,0.5)',
                    }}
                    whileTap={{ scale: 0.95 }}
                    layout
                    transition={{ type: 'spring', stiffness: 400, damping: 25 }}
                  >
                    <ProfileIcon className="w-3.5 h-3.5" />
                    {profile.shortName}
                    {isActive && <Check className="w-3 h-3 ml-0.5" />}
                  </motion.button>
                );
              })}
            </div>
          </div>

          {/* Config Panel */}
          <AnimatePresence>
            {showConfig && (
              <ConfigPanel profile={currentProfile} onClose={() => setShowConfig(false)} />
            )}
          </AnimatePresence>

          {/* Messages Area */}
          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4 min-h-0" style={{ background: '#fafbfc' }}>
            {/* Empty State */}
            {llmMessages.length === 0 && !isLoading && (
              <div className="text-center py-4">
                <motion.div
                  className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-4"
                  style={{
                    background: currentProfile.glowColor,
                    boxShadow: `0 0 40px ${currentProfile.color}15`,
                  }}
                  initial={{ scale: 0.8 }}
                  animate={{ scale: 1 }}
                  transition={{ type: 'spring', stiffness: 300, damping: 15 }}
                >
                  <currentProfile.icon className="w-8 h-8" style={{ color: currentProfile.color }} />
                </motion.div>
                <h3 className="text-sm font-bold text-primary-800 mb-1 tracking-tight">{currentProfile.name}</h3>
                <p className="text-[11px] text-primary-400 mb-1.5 max-w-xs mx-auto leading-relaxed">
                  {currentProfile.description}
                </p>
                <div className="flex flex-col items-center gap-1.5 mb-5">
                  {(() => {
                    const cvName = (() => { try { return localStorage.getItem('internhub_cv_name'); } catch { return null; } })();
                    const hasProfile = (() => { try { return !!localStorage.getItem('internhub_user_profile'); } catch { return false; } })();
                    return (
                      <div className="flex flex-col items-center gap-1">
                        <div className="flex items-center gap-1.5">
                          <Database className="w-3 h-3 text-emerald-500" />
                          <span className="text-[10px] font-medium text-emerald-600">PRISM database connected</span>
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" style={{ boxShadow: '0 0 4px rgba(52,211,153,0.5)' }} />
                        </div>
                        {cvName ? (
                          <div className="flex items-center gap-1.5">
                            <FileText className="w-3 h-3 text-blue-500" />
                            <span className="text-[10px] font-medium text-blue-600">CV: {cvName}</span>
                          </div>
                        ) : (
                          <div className="flex items-center gap-1.5">
                            <AlertCircle className="w-3 h-3 text-amber-500" />
                            <span className="text-[10px] font-medium text-amber-600">Upload CV in Settings for personalized AI</span>
                          </div>
                        )}
                        {hasProfile && (
                          <div className="flex items-center gap-1.5">
                            <Check className="w-3 h-3 text-emerald-500" />
                            <span className="text-[10px] font-medium text-emerald-600">Profile data loaded</span>
                          </div>
                        )}
                      </div>
                    );
                  })()}
                </div>

                {/* Quick Prompts Grid */}
                <div className="grid grid-cols-2 gap-2 max-w-sm mx-auto">
                  {currentPrompts.map((qp, idx) => (
                    <motion.button
                      key={idx}
                      onClick={() => handleQuickPrompt(qp.prompt)}
                      className="flex items-center gap-2 p-3 bg-white rounded-xl text-left"
                      style={{
                        border: '1px solid rgba(229,231,235,0.6)',
                        boxShadow: '0 1px 3px rgba(0,0,0,0.02)',
                      }}
                      whileTap={{ scale: 0.97 }}
                      whileHover={{ y: -1, boxShadow: '0 4px 12px rgba(0,0,0,0.05)' }}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: idx * 0.05 + 0.2, duration: 0.3 }}
                    >
                      <span style={{ color: currentProfile.color }}>{qp.icon}</span>
                      <span className="text-[11px] font-medium text-primary-700 leading-tight">{qp.label}</span>
                    </motion.button>
                  ))}
                </div>
              </div>
            )}

            {/* Chat Messages */}
            {llmMessages.map((msg) => {
              const isUser = msg.role === 'user';
              const isAssistant = msg.role === 'assistant';
              const isStreamComplete = completedMsgIds.has(msg.id);

              return (
                <motion.div
                  key={msg.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
                  className={`flex gap-2.5 ${isUser ? 'flex-row-reverse' : ''}`}
                >
                  {/* Avatar */}
                  <motion.div
                    className="flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center mt-0.5"
                    style={{
                      background: isUser ? 'var(--gradient-accent)' : currentProfile.gradient,
                      boxShadow: isUser ? '0 2px 8px rgba(10,10,10,0.2)' : `0 2px 8px ${currentProfile.color}25`,
                    }}
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    transition={{ type: 'spring', stiffness: 500, damping: 15 }}
                  >
                    {isUser
                      ? <User className="w-3.5 h-3.5 text-white" />
                      : <Bot className="w-3.5 h-3.5 text-white" />
                    }
                  </motion.div>

                  {/* Message Bubble */}
                  <div className={`max-w-[82%] ${isUser ? 'text-right' : ''}`}>
                    <div className={isUser ? 'chat-bubble-user' : 'chat-bubble-ai'}>
                      {isUser ? (
                        <div className="text-xs leading-relaxed whitespace-pre-wrap">{msg.content}</div>
                      ) : (
                        <StreamingText text={msg.content} isComplete={isStreamComplete} />
                      )}
                    </div>
                    <p className="text-[9px] text-primary-300 mt-1 px-1 flex items-center gap-1">
                      <span>{new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                      {msg.metadata?.model && (
                        <span className="opacity-60">via {msg.metadata.model}</span>
                      )}
                      {msg.metadata?.profile && isAssistant && (
                        <span className="opacity-50 capitalize">{msg.metadata.profile}</span>
                      )}
                    </p>
                  </div>
                </motion.div>
              );
            })}

            {/* Thinking Indicator */}
            {isLoading && (
              <ThinkingIndicator
                profileColor={currentProfile.color}
                profileName={currentProfile.shortName}
              />
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Input Area */}
          <div
            className="flex-shrink-0 px-4 py-3 bg-white"
            style={{
              borderTop: '1px solid rgba(229,231,235,0.5)',
              paddingBottom: 'max(0.75rem, env(safe-area-inset-bottom))',
            }}
          >
            {/* Active Profile Indicator */}
            <div className="flex items-center gap-1.5 mb-2">
              <div
                className="w-1.5 h-1.5 rounded-full"
                style={{ backgroundColor: currentProfile.color, boxShadow: `0 0 6px ${currentProfile.color}50` }}
              />
              <span className="text-[10px] font-medium text-primary-400">
                <span style={{ color: currentProfile.color }} className="font-bold">{currentProfile.name}</span>
                {' '}&middot; 20 agents connected
              </span>
            </div>

            {/* Chat Input */}
            <div className="flex items-end gap-2">
              <textarea
                ref={inputRef}
                value={input}
                onChange={handleInputChange}
                onKeyDown={handleKeyDown}
                placeholder={`Ask ${currentProfile.shortName} anything...`}
                rows={1}
                className="flex-1 px-4 py-2.5 rounded-xl text-sm text-primary-900 placeholder-primary-400 focus:outline-none transition-all resize-none"
                style={{
                  maxHeight: '100px',
                  minHeight: '40px',
                  background: '#f8f9fa',
                  border: '1px solid rgba(229,231,235,0.6)',
                }}
              />
              <motion.button
                onClick={handleSend}
                disabled={!input.trim() || isLoading}
                className="flex-shrink-0 p-2.5 rounded-xl transition-all duration-200"
                style={{
                  background: input.trim() && !isLoading ? currentProfile.gradient : '#f3f4f6',
                  color: input.trim() && !isLoading ? 'white' : '#d1d5db',
                  boxShadow: input.trim() && !isLoading ? `0 4px 16px ${currentProfile.color}30` : 'none',
                }}
                whileTap={input.trim() && !isLoading ? { scale: 0.9 } : {}}
              >
                <Send className="w-4 h-4" />
              </motion.button>
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
