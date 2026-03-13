// ============================================================
// BOTTOM BAR — Ultra Premium Frosted Glass Navigation
// Fixed z-index hierarchy to prevent overlapping
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
      {/* Floating Apply Button (when items selected) — above bottom bar */}
      <AnimatePresence>
        {hasSelection && (
          <motion.div
            initial={{ y: 100, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 100, opacity: 0 }}
            className="fixed left-4 right-4 z-[41]"
            style={{ bottom: 'calc(72px + env(safe-area-inset-bottom, 0px))' }}
          >
            <button
              onClick={() => { setBatchPanelOpen(true); hapticFeedback('medium'); }}
              className="w-full py-3.5 text-white rounded-2xl font-bold text-sm flex items-center justify-center gap-2 active:scale-[0.98] transition-transform"
              style={{
                background: 'var(--gradient-accent)',
                boxShadow: '0 8px 30px rgba(26,26,46,0.3), 0 2px 8px rgba(0,0,0,0.1)',
              }}
            >
              <Zap className="w-4.5 h-4.5" />
              Auto-Apply to {selectedIds.size} Internship{selectedIds.size > 1 ? 's' : ''}
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Bottom Navigation - Frosted Glass — z-40 */}
      <nav className="bottom-bar">
        <div className="flex items-center justify-around max-w-md mx-auto">
          <NavItem
            icon={<Home className="w-[20px] h-[20px]" />}
            label="Browse"
            active={activeTab === 'browse'}
            onClick={() => { onTabChange('browse'); hapticFeedback('light'); }}
          />
          <NavItem
            icon={<Sparkles className="w-[20px] h-[20px]" />}
            label="AI Chat"
            active={false}
            onClick={() => { setLLMPanelOpen(true); hapticFeedback('light'); }}
            hasIndicator
          />
          <NavItem
            icon={<BarChart3 className="w-[20px] h-[20px]" />}
            label="Analytics"
            active={activeTab === 'analytics'}
            onClick={() => { onTabChange('analytics'); hapticFeedback('light'); }}
          />
          <NavItem
            icon={<Settings className="w-[20px] h-[20px]" />}
            label="Settings"
            active={activeTab === 'settings'}
            onClick={() => { onTabChange('settings'); hapticFeedback('light'); }}
          />
        </div>
      </nav>
    </>
  );
}

function NavItem({
  icon, label, active, onClick, badge, hasIndicator,
}: {
  icon: React.ReactNode; label: string; active: boolean; onClick: () => void; badge?: number; hasIndicator?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className="flex flex-col items-center gap-0.5 px-4 py-1.5 rounded-xl transition-all duration-200 relative"
    >
      <div className="relative">
        <span className={`transition-colors duration-200 ${active ? 'text-primary-900' : 'text-primary-400'}`}>
          {icon}
        </span>
        {badge && badge > 0 && (
          <span className="absolute -top-1.5 -right-1.5 w-4 h-4 bg-status-danger rounded-full text-[8px] text-white font-bold flex items-center justify-center">
            {badge}
          </span>
        )}
        {hasIndicator && (
          <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-emerald-400 border border-white" />
        )}
      </div>
      <span className={`text-[10px] font-semibold transition-colors duration-200 ${active ? 'text-primary-900' : 'text-primary-400'}`}>
        {label}
      </span>
      {active && (
        <motion.div
          layoutId="bottomBarIndicator"
          className="absolute -top-0.5 w-8 h-0.5 rounded-full"
          style={{ background: 'var(--gradient-accent)' }}
          transition={{ type: 'spring', stiffness: 400, damping: 30 }}
        />
      )}
    </button>
  );
}
