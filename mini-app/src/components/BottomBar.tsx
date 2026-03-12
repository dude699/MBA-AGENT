// ============================================================
// BOTTOM BAR — Floating Action Bar
// ============================================================

import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Zap, Sparkles, BarChart3, Home, Settings } from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';
import { hapticFeedback } from '@/utils/helpers';

interface BottomBarProps {
  activeTab: string;
  onTabChange: (tab: string) => void;
}

export default function BottomBar({ activeTab, onTabChange }: BottomBarProps) {
  const { selectedIds, setBatchPanelOpen, setLLMPanelOpen } = useAppStore();
  const hasSelection = selectedIds.size > 0;

  return (
    <>
      {/* Floating Apply Button (when items selected) */}
      <AnimatePresence>
        {hasSelection && (
          <motion.div
            initial={{ y: 100, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 100, opacity: 0 }}
            className="fixed bottom-20 left-4 right-4 z-40"
          >
            <button
              onClick={() => { setBatchPanelOpen(true); hapticFeedback('medium'); }}
              className="w-full py-3.5 bg-accent text-white rounded-2xl font-bold text-sm flex items-center justify-center gap-2 shadow-elevated active:scale-[0.98] transition-transform"
            >
              <Zap className="w-4.5 h-4.5" />
              Auto-Apply to {selectedIds.size} Internship{selectedIds.size > 1 ? 's' : ''}
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Bottom Navigation */}
      <nav className="bottom-bar flex items-center justify-around">
        <NavItem
          icon={<Home className="w-5 h-5" />}
          label="Browse"
          active={activeTab === 'browse'}
          onClick={() => { onTabChange('browse'); hapticFeedback('light'); }}
        />
        <NavItem
          icon={<Sparkles className="w-5 h-5" />}
          label="AI Chat"
          active={activeTab === 'ai'}
          onClick={() => { setLLMPanelOpen(true); hapticFeedback('light'); }}
        />
        <NavItem
          icon={<BarChart3 className="w-5 h-5" />}
          label="Analytics"
          active={activeTab === 'analytics'}
          onClick={() => { onTabChange('analytics'); hapticFeedback('light'); }}
        />
        <NavItem
          icon={<Settings className="w-5 h-5" />}
          label="Settings"
          active={activeTab === 'settings'}
          onClick={() => { onTabChange('settings'); hapticFeedback('light'); }}
        />
      </nav>
    </>
  );
}

function NavItem({
  icon, label, active, onClick, badge,
}: {
  icon: React.ReactNode; label: string; active: boolean; onClick: () => void; badge?: number;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex flex-col items-center gap-0.5 px-3 py-1 rounded-xl transition-all relative ${
        active ? 'text-accent' : 'text-primary-400'
      }`}
    >
      <div className="relative">
        {icon}
        {badge && badge > 0 && (
          <span className="absolute -top-1 -right-1 w-4 h-4 bg-status-danger rounded-full text-[8px] text-white font-bold flex items-center justify-center">
            {badge}
          </span>
        )}
      </div>
      <span className={`text-[10px] font-semibold ${active ? 'text-accent' : 'text-primary-400'}`}>
        {label}
      </span>
      {active && (
        <motion.div
          layoutId="bottomBarIndicator"
          className="absolute -top-0.5 w-6 h-0.5 bg-accent rounded-full"
        />
      )}
    </button>
  );
}
