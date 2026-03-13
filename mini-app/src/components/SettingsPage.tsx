// ============================================================
// SETTINGS PAGE — Premium Settings with Professional Icons
// ============================================================

import React from 'react';
import { motion } from 'framer-motion';
import {
  Key, Shield, Bell, Trash2, CheckCircle2,
  ExternalLink, Lock, User, Info
} from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';
import { hapticFeedback, getTelegramUser } from '@/utils/helpers';
import { SOURCE_CONFIG, CREDENTIAL_REQUIREMENTS } from '@/utils/constants';
import { SourceIcon } from '@/components/SourceIcons';
import type { InternshipSource } from '@/types';

export default function SettingsPage() {
  const {
    credentials, preferences, removeCredentials,
    appliedIds, dismissedIds, viewedIds,
  } = useAppStore();
  const tgUser = getTelegramUser();

  return (
    <div className="px-4 py-4 space-y-5 pb-28">
      {/* User Profile Card */}
      <div className="rounded-2xl p-5 text-white" style={{ background: 'var(--gradient-dark)' }}>
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 bg-white/10 rounded-xl flex items-center justify-center backdrop-blur-sm">
            <User className="w-6 h-6 text-white/90" />
          </div>
          <div>
            <h2 className="text-base font-bold tracking-tight">
              {tgUser ? `${tgUser.first_name} ${tgUser.last_name || ''}` : 'Guest User'}
            </h2>
            <p className="text-xs text-white/50 font-medium">
              {tgUser?.username ? `@${tgUser.username}` : 'Telegram Mini App'}
            </p>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3 mt-5">
          <div className="text-center p-3 bg-white/5 rounded-xl backdrop-blur-sm">
            <p className="text-lg font-bold">{appliedIds.size}</p>
            <p className="text-[10px] text-white/50 font-medium uppercase tracking-wider">Applied</p>
          </div>
          <div className="text-center p-3 bg-white/5 rounded-xl backdrop-blur-sm">
            <p className="text-lg font-bold">{viewedIds.size}</p>
            <p className="text-[10px] text-white/50 font-medium uppercase tracking-wider">Viewed</p>
          </div>
          <div className="text-center p-3 bg-white/5 rounded-xl backdrop-blur-sm">
            <p className="text-lg font-bold">{dismissedIds.size}</p>
            <p className="text-[10px] text-white/50 font-medium uppercase tracking-wider">Dismissed</p>
          </div>
        </div>
      </div>

      {/* Saved Credentials */}
      <div>
        <div className="flex items-center gap-2 mb-3 px-1">
          <Key className="w-4 h-4 text-primary-400" />
          <h3 className="text-sm font-bold text-primary-900 tracking-tight">Saved Credentials</h3>
        </div>
        <div className="space-y-2">
          {CREDENTIAL_REQUIREMENTS.map((req) => {
            const saved = credentials.find((c) => c.source === req.source);
            const config = SOURCE_CONFIG[req.source];
            return (
              <div
                key={req.source}
                className="flex items-center gap-3 p-3.5 bg-white rounded-xl"
                style={{ boxShadow: '0 1px 4px rgba(0,0,0,0.04)', border: '1px solid rgba(0,0,0,0.05)' }}
              >
                <div
                  className="w-8 h-8 rounded-lg flex items-center justify-center"
                  style={{ backgroundColor: config.color + '12' }}
                >
                  <SourceIcon source={req.source} size={16} className="opacity-80" />
                </div>
                <div className="flex-1">
                  <p className="text-xs font-semibold text-primary-800">{config.name}</p>
                  {saved ? (
                    <p className="text-[10px] text-emerald-600 font-medium flex items-center gap-0.5">
                      <CheckCircle2 className="w-3 h-3" /> Credentials saved
                    </p>
                  ) : (
                    <p className="text-[10px] text-primary-400">Not configured</p>
                  )}
                </div>
                {saved ? (
                  <button
                    onClick={() => { removeCredentials(req.source); hapticFeedback('light'); }}
                    className="p-1.5 text-status-danger hover:bg-status-danger/5 rounded-lg transition-colors"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                ) : (
                  <Lock className="w-4 h-4 text-primary-200" />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Platform Requirements */}
      <div>
        <div className="flex items-center gap-2 mb-3 px-1">
          <Info className="w-4 h-4 text-primary-400" />
          <h3 className="text-sm font-bold text-primary-900 tracking-tight">Platform Requirements</h3>
        </div>
        <div className="space-y-2">
          {CREDENTIAL_REQUIREMENTS.map((req) => {
            const config = SOURCE_CONFIG[req.source];
            return (
              <div
                key={req.source}
                className="p-3.5 bg-white rounded-xl"
                style={{ boxShadow: '0 1px 4px rgba(0,0,0,0.04)', border: '1px solid rgba(0,0,0,0.05)' }}
              >
                <div className="flex items-center gap-2 mb-2">
                  <SourceIcon source={req.source} size={14} className="opacity-70" />
                  <span className="text-xs font-bold text-primary-800">{config.name}</span>
                  <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${
                    config.riskLevel === 'low' ? 'bg-emerald-50 text-emerald-600' :
                    config.riskLevel === 'medium' ? 'bg-amber-50 text-amber-600' :
                    'bg-red-50 text-red-600'
                  }`}>
                    {config.riskLevel.toUpperCase()} RISK
                  </span>
                </div>
                <p className="text-[11px] text-primary-500 mb-2 leading-relaxed">{req.notes}</p>
                <div className="flex flex-wrap gap-1.5">
                  {req.fields.map((field) => (
                    <span key={field.key} className="text-[10px] font-medium px-2 py-0.5 bg-primary-50 rounded-md text-primary-600">
                      {field.label} {field.required && '*'}
                    </span>
                  ))}
                </div>
                <a
                  href={req.loginUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-[10px] font-semibold text-blue-600 mt-2 hover:underline"
                >
                  <ExternalLink className="w-3 h-3" /> Login URL
                </a>
              </div>
            );
          })}
        </div>
      </div>

      {/* Security Notice */}
      <div className="p-4 bg-amber-50/50 border border-amber-200/30 rounded-2xl">
        <div className="flex items-center gap-2 mb-2">
          <Shield className="w-5 h-5 text-amber-600" />
          <h3 className="text-sm font-bold text-amber-700">Security & Privacy</h3>
        </div>
        <ul className="space-y-1.5">
          {[
            { ok: true, text: 'Credentials are stored locally on your device only' },
            { ok: true, text: 'No data is sent to external servers without your consent' },
            { ok: true, text: 'Rate limits protect your accounts from detection' },
            { ok: false, text: 'Auto-apply carries inherent risk -- use at your own discretion' },
            { ok: false, text: 'Some platforms may flag automated activity' },
          ].map((item, idx) => (
            <li key={idx} className="text-[11px] text-primary-600 flex items-start gap-1.5">
              <CheckCircle2 className={`w-3.5 h-3.5 mt-0.5 flex-shrink-0 ${item.ok ? 'text-emerald-500' : 'text-amber-500'}`} />
              {item.text}
            </li>
          ))}
        </ul>
      </div>

      {/* App Info */}
      <div className="text-center pb-8">
        <p className="text-[10px] text-primary-400 font-medium tracking-wide">
          InternHub Pro v2.0.0
        </p>
        <p className="text-[10px] text-primary-300">
          Operation First Mover
        </p>
      </div>
    </div>
  );
}
