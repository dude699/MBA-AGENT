// ============================================================
// SETTINGS PAGE — Credentials, Preferences, Account
// ============================================================

import React from 'react';
import { motion } from 'framer-motion';
import {
  Key, Shield, Bell, Palette, Eye, Trash2, CheckCircle2,
  AlertTriangle, ExternalLink, ChevronRight, Lock, User,
  RefreshCw, Database, Info
} from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';
import { hapticFeedback, hapticNotification, getTelegramUser } from '@/utils/helpers';
import { SOURCE_CONFIG, CREDENTIAL_REQUIREMENTS } from '@/utils/constants';
import type { InternshipSource } from '@/types';

export default function SettingsPage() {
  const {
    credentials, preferences, removeCredentials,
    appliedIds, dismissedIds, viewedIds,
  } = useAppStore();
  const tgUser = getTelegramUser();

  return (
    <div className="px-5 py-4 space-y-6 pb-28">
      {/* User Profile */}
      <div className="bg-gradient-to-br from-accent to-accent-light rounded-2xl p-5 text-white">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 bg-white/20 rounded-xl flex items-center justify-center">
            <User className="w-6 h-6 text-white" />
          </div>
          <div>
            <h2 className="text-base font-bold">
              {tgUser ? `${tgUser.first_name} ${tgUser.last_name || ''}` : 'Guest User'}
            </h2>
            <p className="text-xs text-white/70">
              {tgUser?.username ? `@${tgUser.username}` : 'Telegram Mini App'}
            </p>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3 mt-4">
          <div className="text-center">
            <p className="text-lg font-bold">{appliedIds.size}</p>
            <p className="text-[10px] text-white/70">Applied</p>
          </div>
          <div className="text-center">
            <p className="text-lg font-bold">{viewedIds.size}</p>
            <p className="text-[10px] text-white/70">Viewed</p>
          </div>
          <div className="text-center">
            <p className="text-lg font-bold">{dismissedIds.size}</p>
            <p className="text-[10px] text-white/70">Dismissed</p>
          </div>
        </div>
      </div>

      {/* Saved Credentials */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <Key className="w-4 h-4 text-primary-500" />
          <h3 className="text-sm font-bold text-primary-900">Saved Credentials</h3>
        </div>
        <div className="space-y-2">
          {CREDENTIAL_REQUIREMENTS.map((req) => {
            const saved = credentials.find((c) => c.source === req.source);
            const config = SOURCE_CONFIG[req.source];
            return (
              <div key={req.source} className="flex items-center gap-3 p-3 bg-surface-muted rounded-xl border border-surface-border">
                <span className="text-lg">{config.icon}</span>
                <div className="flex-1">
                  <p className="text-xs font-semibold text-primary-800">{config.name}</p>
                  {saved ? (
                    <p className="text-[10px] text-status-success font-medium flex items-center gap-0.5">
                      <CheckCircle2 className="w-3 h-3" /> Credentials saved
                    </p>
                  ) : (
                    <p className="text-[10px] text-primary-400">Not configured</p>
                  )}
                </div>
                {saved ? (
                  <button
                    onClick={() => { removeCredentials(req.source); hapticFeedback('light'); }}
                    className="p-1.5 text-status-danger hover:bg-status-danger/10 rounded-lg transition-colors"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                ) : (
                  <Lock className="w-4 h-4 text-primary-300" />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Platform Requirements */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <Info className="w-4 h-4 text-primary-500" />
          <h3 className="text-sm font-bold text-primary-900">Platform Requirements</h3>
        </div>
        <div className="space-y-2">
          {CREDENTIAL_REQUIREMENTS.map((req) => {
            const config = SOURCE_CONFIG[req.source];
            return (
              <div key={req.source} className="p-3 bg-surface-muted rounded-xl border border-surface-border">
                <div className="flex items-center gap-2 mb-2">
                  <span>{config.icon}</span>
                  <span className="text-xs font-bold text-primary-800">{config.name}</span>
                  <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${
                    config.riskLevel === 'low' ? 'bg-status-success/10 text-status-success' :
                    config.riskLevel === 'medium' ? 'bg-status-warning/10 text-status-warning' :
                    'bg-status-danger/10 text-status-danger'
                  }`}>
                    {config.riskLevel.toUpperCase()} RISK
                  </span>
                </div>
                <p className="text-[11px] text-primary-600 mb-2">{req.notes}</p>
                <div className="flex flex-wrap gap-1.5">
                  {req.fields.map((field) => (
                    <span key={field.key} className="text-[10px] font-medium px-2 py-0.5 bg-white rounded-md border border-surface-border text-primary-600">
                      {field.label} {field.required && '(required)'}
                    </span>
                  ))}
                </div>
                <a
                  href={req.loginUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-[10px] font-semibold text-status-info mt-2 hover:underline"
                >
                  <ExternalLink className="w-3 h-3" /> Login URL
                </a>
              </div>
            );
          })}
        </div>
      </div>

      {/* Security Notice */}
      <div className="p-4 bg-status-warning/5 border border-status-warning/20 rounded-2xl">
        <div className="flex items-center gap-2 mb-2">
          <Shield className="w-5 h-5 text-status-warning" />
          <h3 className="text-sm font-bold text-status-warning">Security & Privacy</h3>
        </div>
        <ul className="space-y-1.5">
          <li className="text-[11px] text-primary-600 flex items-start gap-1.5">
            <span className="text-status-success mt-0.5">✓</span>
            Credentials are stored locally on your device only
          </li>
          <li className="text-[11px] text-primary-600 flex items-start gap-1.5">
            <span className="text-status-success mt-0.5">✓</span>
            No data is sent to external servers without your consent
          </li>
          <li className="text-[11px] text-primary-600 flex items-start gap-1.5">
            <span className="text-status-success mt-0.5">✓</span>
            Rate limits protect your accounts from detection
          </li>
          <li className="text-[11px] text-primary-600 flex items-start gap-1.5">
            <span className="text-status-warning mt-0.5">⚠</span>
            Auto-apply carries inherent risk — use at your own discretion
          </li>
          <li className="text-[11px] text-primary-600 flex items-start gap-1.5">
            <span className="text-status-warning mt-0.5">⚠</span>
            Some platforms may flag automated activity — review their terms
          </li>
        </ul>
      </div>

      {/* App Info */}
      <div className="text-center pb-8">
        <p className="text-[10px] text-primary-400 font-medium">
          InternHub Pro v1.0.0
        </p>
        <p className="text-[10px] text-primary-300">
          Operation First Mover — Zero Cost MBA Agent
        </p>
      </div>
    </div>
  );
}
