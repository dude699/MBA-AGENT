// ============================================================
// BOTTOM BAR — PRISM v0.2 Zero-Glitch Navigation
// ------------------------------------------------------------
// Changes vs v0.1:
//   - Removed `layoutId` spring on the active indicator. The
//     spring re-animates on every tap and on parent re-renders,
//     producing a visible wobble on slower devices.
//   - Replaced framer-motion <motion.button> wrappers with plain
//     buttons + CSS `:active` scale. Identical feel, no layer
//     thrash.
//   - Floating "Apply to N" pill is now a simple CSS slide-in
//     (slide-up keyframe) instead of a spring AnimatePresence.
//   - Indicator pill is a plain absolutely-positioned span; its
//     position is driven entirely by which NavItem renders it,
//     so there is no shared-layout animation.
// ============================================================

import React from 'react';
import { Zap, Sparkles, BarChart3, Home, Settings, Shield } from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';
import { hapticFeedback } from '@/utils/helpers';

interface BottomBarProps {
  activeTab: string;
  onTabChange: (tab: string) => void;
  isAdmin?: boolean;
}

export default function BottomBar({ activeTab, onTabChange, isAdmin = false }: BottomBarProps) {
  const { selectedIds, setBatchPanelOpen, setLLMPanelOpen } = useAppStore();
  const hasSelection = selectedIds.size > 0;

  return (
    <>
      {/* Floating Apply Button — pure CSS slide-in, no spring physics. */}
      {hasSelection && (
        <div
          className="fixed left-4 right-4 z-[45] gpu-overlay animate-slide-up"
          style={{
            bottom: 'calc(72px + env(safe-area-inset-bottom, 0px))',
          }}
        >
          <button
            type="button"
            onClick={() => { setBatchPanelOpen(true); hapticFeedback('medium'); }}
            className="w-full py-3.5 rounded-2xl font-bold text-sm flex items-center justify-center gap-2.5 active:scale-[0.97] transition-transform"
            style={{
              background: 'linear-gradient(135deg, #0a0a0a 0%, #1a1a2e 100%)',
              color: '#ffffff',
              boxShadow: '0 8px 32px rgba(0,0,0,0.25), 0 2px 8px rgba(0,0,0,0.15)',
              transitionDuration: '120ms',
            }}
          >
            <Zap className="w-4 h-4" />
            Apply to {selectedIds.size} Internship{selectedIds.size > 1 ? 's' : ''}
            <span
              className="ml-1 px-2 py-0.5 rounded-full text-[10px] font-bold"
              style={{ background: 'rgba(255,255,255,0.15)' }}
            >
              {selectedIds.size}
            </span>
          </button>
        </div>
      )}

      {/* Bottom Navigation */}
      <nav className="bottom-bar gpu-overlay" aria-label="Primary">
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
          {isAdmin && (
            <NavItem
              icon={<Shield />}
              label="Admin"
              active={activeTab === 'admin'}
              onClick={() => { onTabChange('admin'); hapticFeedback('medium'); }}
            />
          )}
        </div>
      </nav>
    </>
  );
}

interface NavItemProps {
  icon: React.ReactElement;
  label: string;
  active: boolean;
  onClick: () => void;
  badge?: number;
  hasIndicator?: boolean;
}

function NavItem({ icon, label, active, onClick, badge, hasIndicator }: NavItemProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      aria-label={label}
      className="relative flex flex-col items-center gap-0.5 px-4 py-1.5 rounded-xl select-none active:scale-[0.92] transition-transform"
      style={{
        transitionDuration: '120ms',
        transitionTimingFunction: 'cubic-bezier(0.22, 1, 0.36, 1)',
      }}
    >
      {/* Active pill — plain CSS, no layout animation. */}
      <span
        aria-hidden="true"
        className="absolute -top-0.5 rounded-full"
        style={{
          width: 20,
          height: 3,
          background: 'linear-gradient(90deg, #0a0a0a, #374151)',
          borderRadius: '0 0 4px 4px',
          boxShadow: active ? '0 2px 8px rgba(10,10,10,0.2)' : 'none',
          opacity: active ? 1 : 0,
          transition: 'opacity 140ms ease',
        }}
      />

      <span className="relative block">
        {React.cloneElement(icon, {
          className: 'w-[20px] h-[20px]',
          strokeWidth: active ? 2.4 : 1.8,
          style: {
            color: active ? '#0a0a0a' : '#9ca3af',
            transition: 'color 140ms ease',
          },
        })}
        {badge && badge > 0 && (
          <span
            className="absolute -top-1.5 -right-1.5 w-4 h-4 bg-red-500 rounded-full text-[8px] text-white font-bold flex items-center justify-center"
          >
            {badge}
          </span>
        )}
        {hasIndicator && (
          <span
            aria-hidden="true"
            className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full"
            style={{
              background: '#10b981',
              boxShadow: '0 0 6px rgba(16,185,129,0.5)',
              border: '2px solid #ffffff',
            }}
          />
        )}
      </span>
      <span
        className="text-[10px] font-semibold"
        style={{
          color: active ? '#0a0a0a' : '#9ca3af',
          transition: 'color 140ms ease',
        }}
      >
        {label}
      </span>
    </button>
  );
}
