// ============================================================
// SETTINGS PAGE — Credential Management + Per-Portal Config
// ============================================================

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Key, Shield, Trash2, CheckCircle2,
  ExternalLink, Lock, User, ChevronDown, ChevronUp,
  Eye, EyeOff, Save, X
} from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';
import { hapticFeedback, getTelegramUser } from '@/utils/helpers';
import { SOURCE_CONFIG, CREDENTIAL_REQUIREMENTS } from '@/utils/constants';
import { SourceIcon } from '@/components/SourceIcons';
import type { InternshipSource } from '@/types';

export default function SettingsPage() {
  const {
    credentials, setCredentials, removeCredentials,
    appliedIds, dismissedIds, viewedIds,
  } = useAppStore();
  const tgUser = getTelegramUser();

  // Track which portal credential form is expanded
  const [expandedSource, setExpandedSource] = useState<string | null>(null);

  return (
    <div className="px-4 py-4 space-y-5 pb-28 overflow-y-auto" style={{ WebkitOverflowScrolling: 'touch' }}>
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

      {/* Saved Credentials — Clickable Expandable Forms */}
      <div>
        <div className="flex items-center gap-2 mb-3 px-1">
          <Key className="w-4 h-4 text-primary-400" />
          <h3 className="text-sm font-bold text-primary-900 tracking-tight">Portal Credentials</h3>
        </div>
        <p className="text-[11px] text-primary-500 mb-3 px-1">
          Tap a portal to configure credentials for auto-apply. Data is encrypted and stored locally.
        </p>
        <div className="space-y-2">
          {CREDENTIAL_REQUIREMENTS.map((req) => {
            const saved = credentials.find((c) => c.source === req.source);
            const config = SOURCE_CONFIG[req.source] || { name: req.source, color: '#6b7280', riskLevel: 'medium' };
            const isExpanded = expandedSource === req.source;

            return (
              <CredentialCard
                key={req.source}
                source={req.source}
                config={config}
                requirement={req}
                savedCredentials={saved}
                isExpanded={isExpanded}
                onToggle={() => {
                  setExpandedSource(isExpanded ? null : req.source);
                  hapticFeedback('light');
                }}
                onSave={(creds) => {
                  setCredentials({
                    source: req.source,
                    credentials: creds,
                    isValid: true,
                    lastVerified: new Date().toISOString(),
                  });
                  setExpandedSource(null);
                  hapticFeedback('medium');
                }}
                onRemove={() => {
                  removeCredentials(req.source);
                  hapticFeedback('light');
                }}
              />
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
          InternHub Pro v2.1.0
        </p>
        <p className="text-[10px] text-primary-300">
          Operation First Mover
        </p>
      </div>
    </div>
  );
}


// ============================================================
// CREDENTIAL CARD — Expandable form per portal
// ============================================================

interface CredentialCardProps {
  source: InternshipSource;
  config: any;
  requirement: any;
  savedCredentials: any;
  isExpanded: boolean;
  onToggle: () => void;
  onSave: (creds: Record<string, string>) => void;
  onRemove: () => void;
}

function CredentialCard({
  source, config, requirement, savedCredentials,
  isExpanded, onToggle, onSave, onRemove,
}: CredentialCardProps) {
  const [formData, setFormData] = useState<Record<string, string>>(() => {
    if (savedCredentials?.credentials) {
      return { ...savedCredentials.credentials };
    }
    const initial: Record<string, string> = {};
    requirement.fields.forEach((f: any) => { initial[f.key] = ''; });
    return initial;
  });
  const [showPasswords, setShowPasswords] = useState<Record<string, boolean>>({});

  const handleFieldChange = (key: string, value: string) => {
    setFormData(prev => ({ ...prev, [key]: value }));
  };

  const togglePassword = (key: string) => {
    setShowPasswords(prev => ({ ...prev, [key]: !prev[key] }));
  };

  const handleSave = () => {
    // Validate required fields
    const missingRequired = requirement.fields
      .filter((f: any) => f.required && !formData[f.key]?.trim())
      .map((f: any) => f.label);

    if (missingRequired.length > 0) {
      alert(`Please fill in: ${missingRequired.join(', ')}`);
      return;
    }
    onSave(formData);
  };

  return (
    <div
      className="bg-white rounded-xl overflow-hidden transition-all duration-200"
      style={{ boxShadow: '0 1px 4px rgba(0,0,0,0.04)', border: '1px solid rgba(0,0,0,0.05)' }}
    >
      {/* Header — always visible, clickable */}
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 p-3.5 text-left active:bg-primary-50 transition-colors"
      >
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
          style={{ backgroundColor: config.color + '12' }}
        >
          <SourceIcon source={source} size={16} className="opacity-80" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold text-primary-800">{config.name}</p>
          {savedCredentials ? (
            <p className="text-[10px] text-emerald-600 font-medium flex items-center gap-0.5">
              <CheckCircle2 className="w-3 h-3" /> Credentials saved
            </p>
          ) : (
            <p className="text-[10px] text-primary-400">Tap to configure</p>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${
            config.riskLevel === 'low' ? 'bg-emerald-50 text-emerald-600' :
            config.riskLevel === 'medium' ? 'bg-amber-50 text-amber-600' :
            'bg-red-50 text-red-600'
          }`}>
            {config.riskLevel?.toUpperCase()}
          </span>
          {isExpanded ? (
            <ChevronUp className="w-4 h-4 text-primary-400" />
          ) : (
            <ChevronDown className="w-4 h-4 text-primary-400" />
          )}
        </div>
      </button>

      {/* Expandable Form */}
      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-3.5 pb-3.5 space-y-3" style={{ borderTop: '1px solid rgba(0,0,0,0.04)' }}>
              {/* Notes */}
              <p className="text-[11px] text-primary-500 mt-3 leading-relaxed">{requirement.notes}</p>

              {/* Fields */}
              {requirement.fields.map((field: any) => (
                <div key={field.key}>
                  <label className="block text-[11px] font-semibold text-primary-700 mb-1">
                    {field.label} {field.required && <span className="text-red-500">*</span>}
                  </label>
                  {field.helpText && (
                    <p className="text-[10px] text-primary-400 mb-1">{field.helpText}</p>
                  )}
                  <div className="relative">
                    <input
                      type={field.type === 'password' && !showPasswords[field.key] ? 'password' : (field.type === 'email' ? 'email' : 'text')}
                      value={formData[field.key] || ''}
                      onChange={(e) => handleFieldChange(field.key, e.target.value)}
                      placeholder={field.placeholder}
                      className="w-full px-3 py-2.5 bg-primary-50 border border-primary-200/60 rounded-lg text-xs text-primary-900 placeholder-primary-400 focus:outline-none focus:ring-2 focus:ring-primary-900/10 focus:border-primary-400 transition-all"
                    />
                    {field.type === 'password' && (
                      <button
                        type="button"
                        onClick={() => togglePassword(field.key)}
                        className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-primary-400 hover:text-primary-600"
                      >
                        {showPasswords[field.key] ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                      </button>
                    )}
                  </div>
                </div>
              ))}

              {/* Login URL */}
              <a
                href={requirement.loginUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 text-[10px] font-semibold text-blue-600 hover:underline"
              >
                <ExternalLink className="w-3 h-3" /> Open {config.name} Login
              </a>

              {/* Action Buttons */}
              <div className="flex gap-2 pt-1">
                <button
                  onClick={handleSave}
                  className="flex-1 flex items-center justify-center gap-1.5 py-2.5 rounded-lg text-xs font-bold text-white transition-all active:scale-[0.97]"
                  style={{ background: 'var(--gradient-accent)' }}
                >
                  <Save className="w-3.5 h-3.5" />
                  Save Credentials
                </button>
                {savedCredentials && (
                  <button
                    onClick={onRemove}
                    className="px-4 py-2.5 rounded-lg text-xs font-bold text-red-600 bg-red-50 hover:bg-red-100 transition-all active:scale-[0.97]"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
