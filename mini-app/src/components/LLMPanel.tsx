// ============================================================
// LLM CHAT PANEL — Ultra Premium AI Assistant with Profiles
// ============================================================

import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X, Send, Sparkles, Loader2, Bot, User, Trash2,
  MessageSquare, Lightbulb, FileText, Shield, BarChart3,
  ChevronDown, Briefcase, Target, BookOpen, GraduationCap,
  Zap, Check
} from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';
import { useLLMChat } from '@/hooks/useHooks';
import { hapticFeedback } from '@/utils/helpers';

// ===== AI PROFILES =====
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
  },
];

// ===== PROFILE-SPECIFIC QUICK PROMPTS =====
const PROFILE_PROMPTS: Record<string, Array<{ icon: React.ReactNode; label: string; prompt: string }>> = {
  generalist: [
    { icon: <Lightbulb className="w-3.5 h-3.5" />, label: 'Best strategy?', prompt: 'What is the best internship application strategy based on current job listings in the database?' },
    { icon: <BarChart3 className="w-3.5 h-3.5" />, label: 'Compare top 5', prompt: 'Compare the top 5 highest paying internships from the database and recommend the best ROI option.' },
    { icon: <Target className="w-3.5 h-3.5" />, label: 'Profile match', prompt: 'Based on the available listings, which internships would be best for a first-year MBA student with engineering background?' },
    { icon: <Shield className="w-3.5 h-3.5" />, label: 'Red flags?', prompt: 'Identify any potentially risky or ghost postings from the current listings in the database.' },
  ],
  resume_builder: [
    { icon: <FileText className="w-3.5 h-3.5" />, label: 'Cover letter', prompt: 'Write a professional cover letter for the highest paying internship in the current listings.' },
    { icon: <Zap className="w-3.5 h-3.5" />, label: 'Resume bullets', prompt: 'Help me write 5 strong STAR-format resume bullets for an MBA student with 2 years in IT consulting.' },
    { icon: <Target className="w-3.5 h-3.5" />, label: 'LinkedIn headline', prompt: 'Suggest 5 LinkedIn headlines optimized for MBA internship recruitment in finance and consulting.' },
    { icon: <BookOpen className="w-3.5 h-3.5" />, label: 'SOP template', prompt: 'Provide a Statement of Purpose template for MBA summer internship applications.' },
  ],
  ats_checker: [
    { icon: <Target className="w-3.5 h-3.5" />, label: 'ATS score', prompt: 'What are the most critical ATS keywords for MBA internship roles in consulting and finance?' },
    { icon: <Shield className="w-3.5 h-3.5" />, label: 'Format check', prompt: 'What resume format issues commonly cause ATS rejection? Give me a checklist.' },
    { icon: <BarChart3 className="w-3.5 h-3.5" />, label: 'Keyword gaps', prompt: 'Based on the job listings in the database, what are the top 20 keywords I should include in my resume?' },
    { icon: <FileText className="w-3.5 h-3.5" />, label: 'Section order', prompt: 'What is the optimal section order for an MBA internship resume to maximize ATS score?' },
  ],
  career_counselor: [
    { icon: <Briefcase className="w-3.5 h-3.5" />, label: 'Career path', prompt: 'I am a first-year MBA student with 3 years in IT. Should I target consulting, product management, or analytics internships?' },
    { icon: <BarChart3 className="w-3.5 h-3.5" />, label: 'Stipend benchmark', prompt: 'What is the current stipend benchmark for MBA summer internships across different sectors and company tiers?' },
    { icon: <GraduationCap className="w-3.5 h-3.5" />, label: 'PPO strategy', prompt: 'What are the best strategies to convert a summer internship into a PPO offer? Give me a week-by-week plan.' },
    { icon: <Target className="w-3.5 h-3.5" />, label: 'Interview prep', prompt: 'Help me prepare for MBA internship interviews. What questions do top companies ask and how should I structure my answers?' },
  ],
};

export default function LLMPanel() {
  const { isLLMPanelOpen, setLLMPanelOpen, llmMessages, clearLLMChat } = useAppStore();
  const { sendMessage, isLoading } = useLLMChat();
  const [input, setInput] = useState('');
  const [activeProfile, setActiveProfile] = useState('generalist');
  const [showProfilePicker, setShowProfilePicker] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const currentProfile = AI_PROFILES.find(p => p.id === activeProfile) || AI_PROFILES[0];
  const currentPrompts = PROFILE_PROMPTS[activeProfile] || PROFILE_PROMPTS.generalist;

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [llmMessages]);

  const handleSend = () => {
    if (!input.trim() || isLoading) return;
    sendMessage(input.trim(), activeProfile);
    setInput('');
    hapticFeedback('light');
  };

  const handleQuickPrompt = (prompt: string) => {
    sendMessage(prompt, activeProfile);
    hapticFeedback('light');
  };

  const handleProfileChange = (profileId: string) => {
    setActiveProfile(profileId);
    setShowProfilePicker(false);
    hapticFeedback('medium');
  };

  if (!isLLMPanelOpen) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 bg-black/20 backdrop-blur-sm"
        onClick={() => setLLMPanelOpen(false)}
      >
        <motion.div
          initial={{ y: '100%' }}
          animate={{ y: 0 }}
          exit={{ y: '100%' }}
          transition={{ type: 'spring', damping: 30, stiffness: 300 }}
          className="absolute bottom-0 left-0 right-0 bg-white rounded-t-3xl h-[90vh] flex flex-col"
          style={{ boxShadow: '0 -8px 40px rgba(0,0,0,0.12)' }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* Handle */}
          <div className="flex justify-center pt-3 pb-1">
            <div className="w-10 h-1 bg-primary-200 rounded-full" />
          </div>

          {/* Header with Profile Selector */}
          <div className="px-4 py-2" style={{ borderBottom: '1px solid rgba(0,0,0,0.05)' }}>
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
                  onClick={() => { clearLLMChat(); hapticFeedback('light'); }}
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

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4" style={{ background: '#fafbfc' }}>
            {llmMessages.length === 0 && (
              <div className="text-center py-6">
                <div
                  className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-4"
                  style={{ background: currentProfile.gradient + '15' }}
                >
                  <currentProfile.icon className="w-8 h-8" style={{ color: currentProfile.color }} />
                </div>
                <h3 className="text-sm font-bold text-primary-800 mb-1 tracking-tight">{currentProfile.name}</h3>
                <p className="text-xs text-primary-400 mb-5 max-w-xs mx-auto leading-relaxed">
                  {currentProfile.description}. Connected to your job database for personalized advice.
                </p>

                {/* Quick Prompts */}
                <div className="grid grid-cols-2 gap-2 max-w-sm mx-auto">
                  {currentPrompts.map((qp, idx) => (
                    <button
                      key={idx}
                      onClick={() => handleQuickPrompt(qp.prompt)}
                      className="flex items-center gap-2 p-3 bg-white rounded-xl text-left transition-all duration-200 hover:shadow-sm"
                      style={{ border: '1px solid rgba(0,0,0,0.05)' }}
                    >
                      <span style={{ color: currentProfile.color }}>{qp.icon}</span>
                      <span className="text-[11px] font-medium text-primary-700 leading-tight">{qp.label}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {llmMessages.map((msg) => (
              <motion.div
                key={msg.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className={`flex gap-2.5 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}
              >
                {/* Avatar */}
                <div
                  className="flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center"
                  style={{
                    background: msg.role === 'user'
                      ? 'var(--gradient-accent)'
                      : currentProfile.gradient,
                  }}
                >
                  {msg.role === 'user'
                    ? <User className="w-3.5 h-3.5 text-white" />
                    : <Bot className="w-3.5 h-3.5 text-white" />
                  }
                </div>

                {/* Message Bubble */}
                <div className={`max-w-[82%] ${msg.role === 'user' ? 'text-right' : ''}`}>
                  <div className={msg.role === 'user' ? 'chat-bubble-user' : 'chat-bubble-ai'}>
                    <div className="whitespace-pre-wrap text-xs leading-relaxed">{formatMarkdown(msg.content)}</div>
                  </div>
                  <p className="text-[9px] text-primary-300 mt-1 px-1">
                    {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    {msg.metadata?.model && (
                      <span className="ml-1 opacity-60">via {msg.metadata.model}</span>
                    )}
                  </p>
                </div>
              </motion.div>
            ))}

            {/* Loading indicator */}
            {isLoading && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex items-center gap-2.5"
              >
                <div
                  className="w-7 h-7 rounded-lg flex items-center justify-center"
                  style={{ background: currentProfile.gradient }}
                >
                  <Bot className="w-3.5 h-3.5 text-white" />
                </div>
                <div className="chat-bubble-ai">
                  <div className="flex items-center gap-2">
                    <div className="flex gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-primary-400" style={{ animation: 'typing-dot 1.2s ease-in-out 0s infinite' }} />
                      <span className="w-1.5 h-1.5 rounded-full bg-primary-400" style={{ animation: 'typing-dot 1.2s ease-in-out 0.2s infinite' }} />
                      <span className="w-1.5 h-1.5 rounded-full bg-primary-400" style={{ animation: 'typing-dot 1.2s ease-in-out 0.4s infinite' }} />
                    </div>
                    <span className="text-xs text-primary-400">Analyzing...</span>
                  </div>
                </div>
              </motion.div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Input Area */}
          <div className="px-4 py-3 bg-white" style={{ borderTop: '1px solid rgba(0,0,0,0.05)' }}>
            {/* Active Profile Indicator */}
            <div className="flex items-center gap-1.5 mb-2">
              <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: currentProfile.color }} />
              <span className="text-[10px] font-medium text-primary-400">
                Chatting as <span style={{ color: currentProfile.color }} className="font-bold">{currentProfile.name}</span>
                {' '}&middot; Connected to job database
              </span>
            </div>
            <div className="flex items-center gap-2">
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                placeholder={`Ask ${currentProfile.shortName} anything...`}
                className="flex-1 px-4 py-2.5 bg-primary-50/80 border border-primary-100 rounded-xl text-sm text-primary-900 placeholder-primary-400 focus:outline-none focus:ring-2 focus:ring-primary-900/8 focus:border-primary-200 transition-all"
              />
              <button
                onClick={handleSend}
                disabled={!input.trim() || isLoading}
                className="p-2.5 rounded-xl transition-all duration-200"
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

// ===== MARKDOWN FORMATTER =====
function formatMarkdown(text: string): string {
  return text
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/\*(.*?)\*/g, '$1');
}
