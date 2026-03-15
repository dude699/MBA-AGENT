// ============================================================
// BOTTOM BAR — PRISM v0.1 Ultra Premium Navigation
// Frosted glass, spring animations, active glow indicator
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
            initial={{ y: 100, opacity: 0, scale: 0.9 }}
            animate={{ y: 0, opacity: 1, scale: 1 }}
            exit={{ y: 100, opacity: 0, scale: 0.9 }}
            transition={{ type: 'spring', damping: 25, stiffness: 300 }}
            className="fixed left-4 right-4 z-[41]"
            style={{ bottom: 'calc(76px + env(safe-area-inset-bottom, 0px))' }}
          >
            <motion.button
              onClick={() => { setBatchPanelOpen(true); hapticFeedback('medium'); }}
              className="w-full py-3.5 rounded-2xl font-bold text-sm flex items-center justify-center gap-2.5"
              style={{
                background: '#0a0a0a',
                color: '#ffffff',
                boxShadow: '0 8px 32px rgba(0,0,0,0.25), 0 2px 8px rgba(0,0,0,0.15)',
              }}
              whileTap={{ scale: 0.97 }}
              whileHover={{ y: -1 }}
            >
              <Zap className="w-4.5 h-4.5" />
              Auto-Apply to {selectedIds.size} Internship{selectedIds.size > 1 ? 's' : ''}
              <motion.span
                className="ml-1 px-2 py-0.5 rounded-full text-[10px] font-bold"
                style={{ background: 'rgba(255,255,255,0.15)' }}
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ type: 'spring', stiffness: 500, damping: 15, delay: 0.1 }}
              >
                {selectedIds.size}
              </motion.span>
            </motion.button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Bottom Navigation */}
      <nav className="bottom-bar">
        <div className="flex items-center justify-around max-w-md mx-auto relative">
          <NavItem
            icon={<Home />}
            label="Browse"
            active={activeTab === 'browse'}
            onClick={() => { onTabChange('browse'); hapticFeedback('light'); }}
          />
          <NavItem
            icon={<Sparkles />}
            label="AI Chat"
            active={false}
            onClick={() => { setLLMPanelOpen(true); hapticFeedback('light'); }}
            hasIndicator
            accentColor="#6366f1"
          />
          <NavItem
            icon={<BarChart3 />}
            label="Analytics"
            active={activeTab === 'analytics'}
            onClick={() => { onTabChange('analytics'); hapticFeedback('light'); }}
          />
          <NavItem
            icon={<Settings />}
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
  icon, label, active, onClick, badge, hasIndicator, accentColor,
}: {
  icon: React.ReactElement;
  label: string;
  active: boolean;
  onClick: () => void;
  badge?: number;
  hasIndicator?: boolean;
  accentColor?: string;
}) {
  return (
    <motion.button
      onClick={onClick}
      className="flex flex-col items-center gap-0.5 px-4 py-1.5 rounded-xl relative"
      whileTap={{ scale: 0.88 }}
      transition={{ type: 'spring', stiffness: 400, damping: 15 }}
    >
      <div className="relative">
        <motion.span
          className="block transition-colors duration-200"
          style={{ color: active ? '#0a0a0a' : '#9ca3af' }}
          animate={{
            scale: active ? 1 : 0.95,
          }}
          transition={{ type: 'spring', stiffness: 400, damping: 20 }}
        >
          {React.cloneElement(icon, {
            className: 'w-[20px] h-[20px]',
            strokeWidth: active ? 2.5 : 1.8,
          })}
        </motion.span>
        {badge && badge > 0 && (
          <motion.span
            className="absolute -top-1.5 -right-1.5 w-4 h-4 bg-red-500 rounded-full text-[8px] text-white font-bold flex items-center justify-center"
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ type: 'spring', stiffness: 500, damping: 15 }}
          >
            {badge}
          </motion.span>
        )}
        {hasIndicator && (
          <span
            className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full"
            style={{
              background: '#10b981',
              boxShadow: '0 0 6px rgba(16,185,129,0.5)',
              border: '2px solid #ffffff',
            }}
          />
        )}
      </div>
      <span
        className="text-[10px] font-semibold transition-all duration-200"
        style={{
          color: active ? '#0a0a0a' : '#9ca3af',
          letterSpacing: active ? '0.02em' : '0',
        }}
      >
        {label}
      </span>
      {/* Active indicator — animated underline with glow */}
      {active && (
        <motion.div
          layoutId="bottomBarActiveIndicator"
          className="absolute -top-0.5 rounded-full"
          style={{
            width: 24,
            height: 3,
            background: '#0a0a0a',
            borderRadius: '0 0 4px 4px',
            boxShadow: '0 2px 8px rgba(10,10,10,0.15)',
          }}
          transition={{ type: 'spring', stiffness: 500, damping: 30 }}
        />
      )}
    </motion.button>
  );
}
