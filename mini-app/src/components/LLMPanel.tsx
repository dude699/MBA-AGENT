// ============================================================
// LLM CHAT PANEL — Ultra Premium AI Assistant with Profiles
// Professional text streaming, typing indicators, markdown rendering
// ============================================================

import React, { useState, useRef, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X, Send, Sparkles, Bot, User, Trash2,
  Lightbulb, FileText, Shield, BarChart3,
  Briefcase, Target, BookOpen, GraduationCap,
  Zap, Check, Database, AlertCircle, Settings2,
  ChevronDown, Cpu, Activity
} from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';
import { useLLMChat } from '@/hooks/useHooks';
import { hapticFeedback } from '@/utils/helpers';

// ===== AI PROFILES WITH FULL CONFIGURATION =====
const AI_PROFILES = [
  {
    id: 'generalist',
    name: 'Career Advisor',
    shortName: 'Advisor',
    icon: GraduationCap,
    color: '#7c3aed',
    gradient: 'linear-gradient(135deg, #7c3aed 0%, #a855f7 100%)',
    description: 'Student counselor for finding jobs and career guidance',
    tagline: 'Powered by Groq LLaMA',
    capabilities: ['Job matching', 'Career strategy', 'Application priority', 'Ghost detection'],
  },
  {
    id: 'resume_builder',
    name: 'Resume Builder',
    shortName: 'Resume',
    icon: FileText,
    color: '#0891b2',
    gradient: 'linear-gradient(135deg, #0891b2 0%, #22d3ee 100%)',
    description: 'Elite resume & cover letter specialist',
    tagline: 'HBS Format Expert',
    capabilities: ['Cover letters', 'Resume bullets', 'LinkedIn optimization', 'SOP writing'],
  },
  {
    id: 'ats_checker',
    name: 'ATS Analyzer',
    shortName: 'ATS',
    icon: Target,
    color: '#059669',
    gradient: 'linear-gradient(135deg, #059669 0%, #34d399 100%)',
    description: 'Applicant Tracking System optimization engine',
    tagline: 'Score & Optimize',
    capabilities: ['ATS scoring', 'Keyword analysis', 'Format checking', 'Section optimization'],
  },
  {
    id: 'career_counselor',
    name: 'Career Strategist',
    shortName: 'Strategy',
    icon: Briefcase,
    color: '#dc2626',
    gradient: 'linear-gradient(135deg, #dc2626 0%, #f87171 100%)',
    description: 'MBA placement strategy and career planning',
    tagline: 'IIM/ISB Specialist',
    capabilities: ['Career path', 'Stipend benchmark', 'PPO strategy', 'Interview prep'],
  },
];

// ===== PROFILE-SPECIFIC QUICK PROMPTS =====
const PROFILE_PROMPTS: Record<string, Array<{ icon: React.ReactNode; label: string; prompt: string }>> = {
  generalist: [
    { icon: <Lightbulb className="w-3.5 h-3.5" />, label: 'Analyze my CV', prompt: 'Based on my uploaded CV and profile, what are my top 3 strengths and which job roles in the database would be the best fit?' },
    { icon: <BarChart3 className="w-3.5 h-3.5" />, label: 'Top matches', prompt: 'Compare the top 5 internships from the database that best match my skills and background. Rank them by fit score.' },
    { icon: <Target className="w-3.5 h-3.5" />, label: 'Apply strategy', prompt: 'Create a prioritized application strategy for me. Which listings should I apply to first and why? Consider my profile strengths.' },
    { icon: <Shield className="w-3.5 h-3.5" />, label: 'Red flags', prompt: 'Identify any risky or ghost postings from the current listings. Which should I avoid and why?' },
  ],
  resume_builder: [
    { icon: <FileText className="w-3.5 h-3.5" />, label: 'Review my CV', prompt: 'Analyze my uploaded CV in detail. List specific improvements: weak verbs, missing quantification, formatting issues, and ATS problems.' },
    { icon: <Zap className="w-3.5 h-3.5" />, label: 'Cover letter', prompt: 'Write a tailored cover letter for the highest paying internship in the database. Use my CV skills and experience as the basis.' },
    { icon: <Target className="w-3.5 h-3.5" />, label: 'Resume bullets', prompt: 'Based on my CV, rewrite my top 5 experience bullet points using STAR format with quantified metrics. Make them ATS-optimized.' },
    { icon: <BookOpen className="w-3.5 h-3.5" />, label: 'LinkedIn optimize', prompt: 'Based on my CV and the job listings, suggest an optimized LinkedIn headline, summary, and top skills section.' },
  ],
  ats_checker: [
    { icon: <Target className="w-3.5 h-3.5" />, label: 'ATS score my CV', prompt: 'Run a full ATS analysis on my CV. Give me keyword match score, format score, section score, and overall ATS score out of 100.' },
    { icon: <Shield className="w-3.5 h-3.5" />, label: 'Missing keywords', prompt: 'Compare my CV keywords against the top 10 job listings in the database. List all missing critical keywords I should add.' },
    { icon: <BarChart3 className="w-3.5 h-3.5" />, label: 'Format check', prompt: 'Check my CV for ATS-breaking issues: wrong fonts, images, tables, headers, and section labels. Give me a pass/fail for each.' },
    { icon: <FileText className="w-3.5 h-3.5" />, label: 'Optimize for role', prompt: 'Pick the best matching job from the database for my profile and show me exactly how to optimize my CV for that specific role.' },
  ],
  career_counselor: [
    { icon: <Briefcase className="w-3.5 h-3.5" />, label: 'Career path', prompt: 'Based on my CV, experience, and skills, recommend the top 3 career paths I should target. Include short-term and long-term strategy.' },
    { icon: <BarChart3 className="w-3.5 h-3.5" />, label: 'Stipend benchmark', prompt: 'Based on my profile and the current job listings, what stipend range should I expect? How does my profile compare to typical candidates?' },
    { icon: <GraduationCap className="w-3.5 h-3.5" />, label: 'PPO strategy', prompt: 'Create a week-by-week PPO conversion strategy for me. What should I do during my internship to maximize my chances of getting a full-time offer?' },
    { icon: <Target className="w-3.5 h-3.5" />, label: 'Interview prep', prompt: 'Based on the top matching jobs for my profile, help me prepare for interviews. What questions will I face and how should I answer them?' },
  ],
};

// ===== MARKDOWN RENDERER (no extra # symbols) =====
function renderFormattedText(text: string): React.ReactNode {
  if (!text) return null;

  // Clean up common AI formatting artifacts
  let cleaned = text
    .replace(/^#{1,6}\s*/gm, '') // Remove all heading markers
    .replace(/\*\*\*(.+?)\*\*\*/g, '<bi>$1</bi>') // Bold-italic placeholder
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>') // Bold placeholder
    .replace(/\*(.+?)\*/g, '<i>$1</i>') // Italic placeholder
    .replace(/`([^`]+)`/g, '<code>$1</code>') // Inline code
    .trim();

  // Split into paragraphs/sections
  const blocks = cleaned.split('\n\n').filter(Boolean);

  return (
    <div className="chat-markdown space-y-2">
      {blocks.map((block, blockIdx) => {
        // Check for list blocks (lines starting with - or * or numbered)
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

        // Regular paragraph with inline formatting
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

// ===== TEXT STREAMING EFFECT =====
function StreamingText({ text, isComplete }: { text: string; isComplete: boolean }) {
  const [displayedLength, setDisplayedLength] = useState(0);
  const fullLength = text.length;

  useEffect(() => {
    if (isComplete) {
      setDisplayedLength(fullLength);
      return;
    }

    // Simulate streaming: reveal characters progressively
    const speed = 8; // ms per character - fast, professional feel
    const interval = setInterval(() => {
      setDisplayedLength(prev => {
        if (prev >= fullLength) {
          clearInterval(interval);
          return fullLength;
        }
        // Reveal in chunks for smoother feel
        const jump = Math.min(3, fullLength - prev);
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

// ===== THINKING INDICATOR =====
function ThinkingIndicator({ profileColor, profileName }: { profileColor: string; profileName: string }) {
  const [dots, setDots] = useState(1);
  const [thinkingPhase, setThinkingPhase] = useState(0);

  const phases = [
    'Analyzing your query',
    'Searching job database',
    'Generating response',
  ];

  useEffect(() => {
    const dotInterval = setInterval(() => setDots(d => d >= 3 ? 1 : d + 1), 500);
    const phaseInterval = setInterval(() => setThinkingPhase(p => (p + 1) % phases.length), 2200);
    return () => { clearInterval(dotInterval); clearInterval(phaseInterval); };
  }, []);

  return (
    <div className="flex items-start gap-2.5">
      <div
        className="flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center"
        style={{ background: `linear-gradient(135deg, ${profileColor} 0%, ${profileColor}aa 100%)` }}
      >
        <Bot className="w-3.5 h-3.5 text-white" />
      </div>
      <div className="chat-bubble-ai">
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-2">
            <div className="thinking-dots">
              <span className="thinking-dot" style={{ animationDelay: '0ms', backgroundColor: profileColor }} />
              <span className="thinking-dot" style={{ animationDelay: '200ms', backgroundColor: profileColor }} />
              <span className="thinking-dot" style={{ animationDelay: '400ms', backgroundColor: profileColor }} />
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            <Activity className="w-3 h-3 animate-pulse" style={{ color: profileColor }} />
            <span className="text-[10px] text-primary-400 font-medium">
              {phases[thinkingPhase]}{'.'.repeat(dots)}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ===== CONFIGURATION PANEL =====
function ConfigPanel({ profile, onClose }: { profile: typeof AI_PROFILES[0]; onClose: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="mx-4 mb-2 p-3 bg-white rounded-xl border border-primary-100"
      style={{ boxShadow: '0 4px 20px rgba(0,0,0,0.06)' }}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Settings2 className="w-3.5 h-3.5" style={{ color: profile.color }} />
          <span className="text-[11px] font-bold text-primary-800">{profile.name} Configuration</span>
        </div>
        <button onClick={onClose} className="p-1 rounded-md hover:bg-primary-50">
          <X className="w-3 h-3 text-primary-400" />
        </button>
      </div>

      {/* Provider Info */}
      <div className="flex items-center gap-4 mb-2 p-2 bg-primary-50/50 rounded-lg">
        <div className="flex items-center gap-1.5">
          <Cpu className="w-3 h-3 text-primary-500" />
          <span className="text-[10px] font-medium text-primary-600">Primary: Groq LLaMA</span>
        </div>
        <div className="flex items-center gap-1.5">
          <Cpu className="w-3 h-3 text-primary-400" />
          <span className="text-[10px] font-medium text-primary-400">Fallback: Cerebras</span>
        </div>
      </div>

      {/* Capabilities */}
      <div className="flex flex-wrap gap-1.5 mb-2">
        {profile.capabilities.map((cap, i) => (
          <span key={i} className="text-[9px] font-semibold px-2 py-0.5 rounded-md"
            style={{ background: profile.color + '12', color: profile.color }}>
            {cap}
          </span>
        ))}
      </div>

      {/* Connection Status */}
      <div className="flex items-center gap-1.5 p-1.5 bg-emerald-50 rounded-md">
        <Database className="w-3 h-3 text-emerald-500" />
        <span className="text-[10px] font-medium text-emerald-600">Connected to Supabase job database</span>
        <span className="ml-auto w-1.5 h-1.5 bg-emerald-400 rounded-full animate-pulse" />
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

  // Auto-scroll on new messages
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
      }, (llmMessages[llmMessages.length - 1]?.content?.length || 100) * 8 + 500);
      return () => clearTimeout(timer);
    }
  }, [llmMessages]);

  // Mark all user messages as completed immediately
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
    // Reset textarea height
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

  // Auto-resize textarea
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
        className="fixed inset-0 z-[60] bg-black/25 backdrop-blur-sm"
        onClick={() => setLLMPanelOpen(false)}
      >
        <motion.div
          initial={{ y: '100%' }}
          animate={{ y: 0 }}
          exit={{ y: '100%' }}
          transition={{ type: 'spring', damping: 30, stiffness: 300 }}
          className="absolute bottom-0 left-0 right-0 bg-white rounded-t-3xl flex flex-col"
          style={{
            height: '92vh',
            maxHeight: '92vh',
            boxShadow: '0 -8px 40px rgba(0,0,0,0.15)',
          }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* Handle */}
          <div className="flex justify-center pt-3 pb-1 flex-shrink-0">
            <div className="w-10 h-1 bg-primary-200 rounded-full" />
          </div>

          {/* Header with Profile Selector */}
          <div className="px-4 py-2 flex-shrink-0" style={{ borderBottom: '1px solid rgba(0,0,0,0.05)' }}>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2.5">
                <div
                  className="w-9 h-9 rounded-xl flex items-center justify-center"
                  style={{ background: currentProfile.gradient }}
                >
                  <currentProfile.icon className="w-4.5 h-4.5 text-white" />
                </div>
                <div>
                  <h2 className="text-sm font-bold text-primary-900 tracking-tight">{currentProfile.name}</h2>
                  <p className="text-[10px] text-primary-400 font-medium">{currentProfile.tagline}</p>
                </div>
              </div>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => { setShowConfig(!showConfig); hapticFeedback('light'); }}
                  className={`p-2 rounded-xl transition-colors ${showConfig ? 'bg-primary-100' : 'hover:bg-primary-50'}`}
                  title="Configuration"
                >
                  <Settings2 className="w-4 h-4 text-primary-400" />
                </button>
                <button
                  onClick={() => { clearLLMChat(); setCompletedMsgIds(new Set()); hapticFeedback('light'); }}
                  className="p-2 rounded-xl hover:bg-primary-50 transition-colors"
                  title="Clear chat"
                >
                  <Trash2 className="w-4 h-4 text-primary-300" />
                </button>
                <button onClick={() => setLLMPanelOpen(false)} className="p-2 rounded-xl hover:bg-primary-50 transition-colors">
                  <X className="w-5 h-5 text-primary-400" />
                </button>
              </div>
            </div>

            {/* Profile Toggle Chips */}
            <div className="flex gap-1.5 overflow-x-auto scrollbar-none pb-1">
              {AI_PROFILES.map((profile) => {
                const isActive = activeProfile === profile.id;
                const ProfileIcon = profile.icon;
                return (
                  <button
                    key={profile.id}
                    onClick={() => handleProfileChange(profile.id)}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold whitespace-nowrap transition-all duration-200 ${
                      isActive
                        ? 'text-white shadow-sm'
                        : 'text-primary-600 bg-primary-50 hover:bg-primary-100'
                    }`}
                    style={isActive ? { background: profile.gradient } : {}}
                  >
                    <ProfileIcon className="w-3.5 h-3.5" />
                    {profile.shortName}
                    {isActive && <Check className="w-3 h-3 ml-0.5" />}
                  </button>
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
              <div className="text-center py-6">
                <div
                  className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-4"
                  style={{ background: currentProfile.color + '12' }}
                >
                  <currentProfile.icon className="w-8 h-8" style={{ color: currentProfile.color }} />
                </div>
                <h3 className="text-sm font-bold text-primary-800 mb-1 tracking-tight">{currentProfile.name}</h3>
                <p className="text-xs text-primary-400 mb-1.5 max-w-xs mx-auto leading-relaxed">
                  {currentProfile.description}
                </p>
                <div className="flex items-center justify-center gap-1.5 mb-5">
                  {(() => {
                    const cvName = (() => { try { return localStorage.getItem('internhub_cv_name'); } catch { return null; } })();
                    const hasProfile = (() => { try { return !!localStorage.getItem('internhub_user_profile'); } catch { return false; } })();
                    return (
                      <div className="flex flex-col items-center gap-1">
                        <div className="flex items-center gap-1.5">
                          <Database className="w-3 h-3 text-emerald-500" />
                          <span className="text-[10px] font-medium text-emerald-600">Job database connected</span>
                        </div>
                        {cvName ? (
                          <div className="flex items-center gap-1.5">
                            <FileText className="w-3 h-3 text-blue-500" />
                            <span className="text-[10px] font-medium text-blue-600">CV loaded: {cvName}</span>
                          </div>
                        ) : (
                          <div className="flex items-center gap-1.5">
                            <AlertCircle className="w-3 h-3 text-amber-500" />
                            <span className="text-[10px] font-medium text-amber-600">Upload CV in Settings for personalized advice</span>
                          </div>
                        )}
                        {hasProfile && (
                          <div className="flex items-center gap-1.5">
                            <Check className="w-3 h-3 text-emerald-500" />
                            <span className="text-[10px] font-medium text-emerald-600">Profile data available</span>
                          </div>
                        )}
                      </div>
                    );
                  })()}
                </div>

                {/* Quick Prompts Grid */}
                <div className="grid grid-cols-2 gap-2 max-w-sm mx-auto">
                  {currentPrompts.map((qp, idx) => (
                    <button
                      key={idx}
                      onClick={() => handleQuickPrompt(qp.prompt)}
                      className="flex items-center gap-2 p-3 bg-white rounded-xl text-left transition-all duration-200 hover:shadow-sm active:scale-[0.98]"
                      style={{ border: '1px solid rgba(0,0,0,0.06)' }}
                    >
                      <span style={{ color: currentProfile.color }}>{qp.icon}</span>
                      <span className="text-[11px] font-medium text-primary-700 leading-tight">{qp.label}</span>
                    </button>
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
                  transition={{ duration: 0.25 }}
                  className={`flex gap-2.5 ${isUser ? 'flex-row-reverse' : ''}`}
                >
                  {/* Avatar */}
                  <div
                    className="flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center mt-0.5"
                    style={{
                      background: isUser ? 'var(--gradient-accent)' : currentProfile.gradient,
                    }}
                  >
                    {isUser
                      ? <User className="w-3.5 h-3.5 text-white" />
                      : <Bot className="w-3.5 h-3.5 text-white" />
                    }
                  </div>

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

            {/* Professional Thinking Indicator */}
            {isLoading && (
              <ThinkingIndicator
                profileColor={currentProfile.color}
                profileName={currentProfile.shortName}
              />
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Input Area - Properly positioned, no overlaps */}
          <div
            className="flex-shrink-0 px-4 py-3 bg-white"
            style={{
              borderTop: '1px solid rgba(0,0,0,0.06)',
              paddingBottom: 'max(0.75rem, env(safe-area-inset-bottom))',
            }}
          >
            {/* Active Profile Indicator */}
            <div className="flex items-center gap-1.5 mb-2">
              <div className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ backgroundColor: currentProfile.color }} />
              <span className="text-[10px] font-medium text-primary-400">
                <span style={{ color: currentProfile.color }} className="font-bold">{currentProfile.name}</span>
                {' '}&middot; Job database connected
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
                className="flex-1 px-4 py-2.5 bg-primary-50/80 border border-primary-100 rounded-xl text-sm text-primary-900 placeholder-primary-400 focus:outline-none focus:ring-2 focus:ring-primary-900/8 focus:border-primary-200 transition-all resize-none"
                style={{ maxHeight: '100px', minHeight: '40px' }}
              />
              <button
                onClick={handleSend}
                disabled={!input.trim() || isLoading}
                className="flex-shrink-0 p-2.5 rounded-xl transition-all duration-200 active:scale-95"
                style={{
                  background: input.trim() && !isLoading ? currentProfile.gradient : '#f0f2f5',
                  color: input.trim() && !isLoading ? 'white' : '#ced4da',
                  boxShadow: input.trim() && !isLoading ? `0 4px 12px ${currentProfile.color}30` : 'none',
                }}
              >
                <Send className="w-4 h-4" />
              </button>
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
