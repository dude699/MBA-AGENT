// ============================================================
// LLM CHAT PANEL — Real-time AI Assistant
// ============================================================

import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X, Send, Sparkles, Loader2, Bot, User, Trash2,
  MessageSquare, Lightbulb, FileText, Shield, BarChart3,
  RefreshCw
} from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';
import { useLLMChat } from '@/hooks/useHooks';
import { hapticFeedback } from '@/utils/helpers';

const QUICK_PROMPTS = [
  { icon: <Lightbulb className="w-3.5 h-3.5" />, label: 'Best strategy?', prompt: 'What is the best internship application strategy based on current listings?' },
  { icon: <BarChart3 className="w-3.5 h-3.5" />, label: 'Compare top 5', prompt: 'Compare the top 5 highest paying internships for me' },
  { icon: <FileText className="w-3.5 h-3.5" />, label: 'Cover letter tips', prompt: 'Give me cover letter tips for MBA internship applications' },
  { icon: <Shield className="w-3.5 h-3.5" />, label: 'Risk assessment', prompt: 'What are the safest sources for auto-apply with least risk of detection?' },
];

export default function LLMPanel() {
  const { isLLMPanelOpen, setLLMPanelOpen, llmMessages, clearLLMChat } = useAppStore();
  const { sendMessage, isLoading } = useLLMChat();
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [llmMessages]);

  const handleSend = () => {
    if (!input.trim() || isLoading) return;
    sendMessage(input.trim());
    setInput('');
    hapticFeedback('light');
  };

  const handleQuickPrompt = (prompt: string) => {
    sendMessage(prompt);
    hapticFeedback('light');
  };

  if (!isLLMPanelOpen) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 bg-black/30 backdrop-blur-sm"
        onClick={() => setLLMPanelOpen(false)}
      >
        <motion.div
          initial={{ y: '100%' }}
          animate={{ y: 0 }}
          exit={{ y: '100%' }}
          transition={{ type: 'spring', damping: 30, stiffness: 300 }}
          className="absolute bottom-0 left-0 right-0 bg-white rounded-t-3xl h-[85vh] flex flex-col"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Handle */}
          <div className="flex justify-center pt-3 pb-1">
            <div className="w-10 h-1 bg-primary-200 rounded-full" />
          </div>

          {/* Header */}
          <div className="flex items-center justify-between px-5 py-3 border-b border-surface-border">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 bg-gradient-to-br from-violet-500 to-purple-600 rounded-xl flex items-center justify-center">
                <Sparkles className="w-4 h-4 text-white" />
              </div>
              <div>
                <h2 className="text-sm font-bold text-primary-900">AI Assistant</h2>
                <p className="text-[10px] text-primary-500">Powered by Groq LLaMA3</p>
              </div>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={() => { clearLLMChat(); hapticFeedback('light'); }}
                className="p-2 rounded-xl hover:bg-surface-muted transition-colors"
                title="Clear chat"
              >
                <Trash2 className="w-4 h-4 text-primary-400" />
              </button>
              <button onClick={() => setLLMPanelOpen(false)} className="p-2">
                <X className="w-5 h-5 text-primary-500" />
              </button>
            </div>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
            {llmMessages.length === 0 && (
              <div className="text-center py-8">
                <div className="w-16 h-16 bg-gradient-to-br from-violet-100 to-purple-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
                  <MessageSquare className="w-8 h-8 text-violet-500" />
                </div>
                <h3 className="text-sm font-bold text-primary-800 mb-1">Ask me anything</h3>
                <p className="text-xs text-primary-500 mb-6 max-w-xs mx-auto">
                  I can help analyze internships, compare options, draft cover letters, and provide career advice.
                </p>

                {/* Quick Prompts */}
                <div className="grid grid-cols-2 gap-2">
                  {QUICK_PROMPTS.map((qp, idx) => (
                    <button
                      key={idx}
                      onClick={() => handleQuickPrompt(qp.prompt)}
                      className="flex items-center gap-2 p-3 bg-surface-muted rounded-xl text-left hover:bg-surface-light transition-colors border border-surface-border"
                    >
                      <span className="text-violet-500">{qp.icon}</span>
                      <span className="text-xs font-medium text-primary-700">{qp.label}</span>
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
                <div className={`flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center ${
                  msg.role === 'user'
                    ? 'bg-accent text-white'
                    : 'bg-gradient-to-br from-violet-500 to-purple-600 text-white'
                }`}>
                  {msg.role === 'user'
                    ? <User className="w-3.5 h-3.5" />
                    : <Bot className="w-3.5 h-3.5" />
                  }
                </div>

                {/* Message Bubble */}
                <div className={`max-w-[80%] ${msg.role === 'user' ? 'text-right' : ''}`}>
                  <div className={`inline-block px-3.5 py-2.5 rounded-2xl text-xs leading-relaxed ${
                    msg.role === 'user'
                      ? 'bg-accent text-white rounded-tr-md'
                      : 'bg-surface-muted text-primary-800 rounded-tl-md border border-surface-border'
                  }`}>
                    <div className="whitespace-pre-wrap">{formatMarkdown(msg.content)}</div>
                  </div>
                  <p className="text-[9px] text-primary-400 mt-1 px-1">
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
                <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center">
                  <Bot className="w-3.5 h-3.5 text-white" />
                </div>
                <div className="bg-surface-muted rounded-2xl rounded-tl-md px-4 py-3 border border-surface-border">
                  <div className="flex items-center gap-2">
                    <Loader2 className="w-3.5 h-3.5 text-violet-500 animate-spin" />
                    <span className="text-xs text-primary-500">Thinking...</span>
                  </div>
                </div>
              </motion.div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Input Area */}
          <div className="px-5 py-3 border-t border-surface-border bg-white">
            <div className="flex items-center gap-2">
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                placeholder="Ask about internships..."
                className="flex-1 px-4 py-2.5 bg-surface-muted border border-surface-border rounded-xl text-sm text-primary-900 placeholder-primary-400 focus:outline-none focus:ring-2 focus:ring-violet-200 focus:border-violet-300 transition-all"
              />
              <button
                onClick={handleSend}
                disabled={!input.trim() || isLoading}
                className={`p-2.5 rounded-xl transition-all ${
                  input.trim() && !isLoading
                    ? 'bg-gradient-to-br from-violet-500 to-purple-600 text-white shadow-md'
                    : 'bg-primary-100 text-primary-400'
                }`}
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

// ===== SIMPLE MARKDOWN FORMATTER =====
function formatMarkdown(text: string): string {
  return text
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/\*(.*?)\*/g, '$1');
}
