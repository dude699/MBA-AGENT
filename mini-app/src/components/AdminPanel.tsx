// ============================================================
// ADMIN PANEL — Super-admin-only control surface
// ============================================================
// Visible only when /api/whoami returns is_admin:true. Every API
// it calls is independently gated server-side by @_admin_only,
// so even if the tab is force-rendered the data calls 403 out.
// ============================================================

import React, { useEffect, useState, useCallback } from 'react';
import {
  Shield, Users, KeyRound, Database, Activity, AlertTriangle,
  RefreshCw, Trash2, Play, Lock, CheckCircle2, XCircle, Server,
  ChevronRight,
} from 'lucide-react';
import { hapticFeedback } from '@/utils/helpers';

// ---------- types ---------------------------------------------------
interface Overview {
  sqlite: Record<string, number>;
  supabase: Record<string, number | string>;
  users: { total: number; admins: number; users: any[] };
  nexus: { version?: string; layers_ok?: string[]; layers_fail?: any; triad_live?: boolean; error?: string };
  env_warnings: {
    force_db_reset_enabled: boolean;
    vault_key_set: boolean;
    supabase_configured: boolean;
  };
  timestamp: string;
}

interface CredRow {
  telegram_id: string;
  portal: string;
  risk_level?: string;
  updated_at?: string;
}

// ---------- helpers -------------------------------------------------
function getTelegramId(): string {
  try {
    const tg = (window as any)?.Telegram?.WebApp;
    const id = tg?.initDataUnsafe?.user?.id;
    if (id) return String(id);
  } catch {}
  return '';
}

const adminFetch = async (path: string, init?: RequestInit) => {
  const headers: Record<string, string> = {
    'X-Telegram-Id': getTelegramId(),
    ...((init?.headers as Record<string, string>) || {}),
  };
  if (init?.body && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }
  const resp = await fetch(`/api${path}`, { ...init, headers });
  return resp.json();
};

// ---------- main ----------------------------------------------------
export default function AdminPanel() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [creds, setCreds] = useState<CredRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string>('');
  const [busy, setBusy] = useState<string>('');

  const refresh = useCallback(async () => {
    setLoading(true);
    setErr('');
    try {
      const [ov, cr] = await Promise.all([
        adminFetch('/admin/overview'),
        adminFetch('/admin/credentials'),
      ]);
      if (!ov.success) throw new Error(ov.error || 'overview failed');
      setOverview(ov.data);
      setCreds(cr.rows || []);
    } catch (e: any) {
      setErr(e.message || 'failed to load');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const triggerScrape = async (wave: 'morning' | 'afternoon' | 'evening' | 'auto') => {
    setBusy(`scrape:${wave}`);
    hapticFeedback('medium');
    try {
      const r = await adminFetch('/admin/trigger-scrape', {
        method: 'POST', body: JSON.stringify({ wave }),
      });
      if (r.success) alert(`✅ ${wave} wave kicked off`);
      else alert(`❌ ${r.error || 'failed'}`);
    } catch (e: any) {
      alert(`❌ ${e.message}`);
    } finally {
      setBusy('');
    }
  };

  const revokeCreds = async (telegram_id: string, portal: string) => {
    if (!confirm(`Revoke ${portal} for user ${telegram_id}?`)) return;
    setBusy(`revoke:${telegram_id}:${portal}`);
    try {
      const r = await adminFetch('/admin/credentials/revoke', {
        method: 'POST',
        body: JSON.stringify({ telegram_id, portal }),
      });
      if (r.success) {
        setCreds(c => c.filter(x => !(x.telegram_id === telegram_id && x.portal === portal)));
      } else {
        alert(`❌ ${r.error || 'revoke failed'}`);
      }
    } finally {
      setBusy('');
    }
  };

  const resetDb = async () => {
    if (!confirm('⚠️ Wipe SQLite cache?\n(Supabase will be preserved.)')) return;
    if (!confirm('Are you absolutely sure? This is destructive.')) return;
    setBusy('reset');
    try {
      const r = await adminFetch('/admin/reset-db', {
        method: 'POST',
        body: JSON.stringify({ confirm: true, clear_supabase: false }),
      });
      if (r.success) {
        alert('✅ SQLite cache wiped. Supabase intact.');
        refresh();
      } else {
        alert(`❌ ${r.error || 'reset failed'}`);
      }
    } finally {
      setBusy('');
    }
  };

  const triggerPurge = async () => {
    if (!confirm('Run TTL retention sweep?\n• Low-score (<60) jobs older than 15 days will be deleted\n• High-score (≥60) jobs older than 25 days will be deleted\n• Applied jobs are PROTECTED.')) return;
    setBusy('purge');
    hapticFeedback('medium');
    try {
      const r = await adminFetch('/admin/trigger-purge', {
        method: 'POST', body: JSON.stringify({}),
      });
      if (r.success) {
        const s = r.stats || {};
        const total = (s.low_score_purged_supabase||0)+(s.high_score_purged_supabase||0)+(s.legacy_purged_supabase||0)+(s.latest_jobs_purged||0)+(s.sqlite_purged||0);
        alert(`✅ Retention sweep complete\n\n• Low-score (Supabase): ${s.low_score_purged_supabase||0}\n• High-score (Supabase): ${s.high_score_purged_supabase||0}\n• Legacy unscored: ${s.legacy_purged_supabase||0}\n• latest_jobs: ${s.latest_jobs_purged||0}\n• SQLite: ${s.sqlite_purged||0}\n\nTotal: ${total}\nApplied protected: ${s.applied_protected||0}`);
        refresh();
      } else {
        alert(`❌ ${r.error || 'purge failed'}`);
      }
    } catch (e: any) {
      alert(`❌ ${e.message}`);
    } finally {
      setBusy('');
    }
  };

  if (loading) {
    return (
      <div className="px-4 py-12 flex flex-col items-center text-center">
        <div className="w-12 h-12 rounded-2xl flex items-center justify-center mb-3"
             style={{ background: 'linear-gradient(135deg, #1f2937 0%, #374151 100%)' }}>
          <Shield className="w-6 h-6 text-white" />
        </div>
        <p className="text-xs text-primary-500 flex items-center gap-2">
          <RefreshCw className="w-3 h-3 animate-spin" /> Loading admin panel…
        </p>
      </div>
    );
  }

  if (err) {
    return (
      <div className="px-4 py-12 text-center">
        <XCircle className="w-12 h-12 mx-auto mb-3 text-red-500" />
        <h3 className="text-base font-bold mb-2">Admin access denied</h3>
        <p className="text-xs text-primary-500 mb-4">{err}</p>
        <p className="text-[11px] text-primary-400 max-w-xs mx-auto">
          Only the configured super-admin can reach this panel. If you set
          <code className="bg-gray-100 px-1.5 py-0.5 rounded mx-1">NEXUS_SUPER_ADMIN_ID</code>
          in Render env, make sure your Telegram ID matches.
        </p>
      </div>
    );
  }

  if (!overview) return null;

  const env = overview.env_warnings;
  const dangerCount = (env.force_db_reset_enabled ? 1 : 0)
                    + (!env.vault_key_set ? 1 : 0)
                    + (!env.supabase_configured ? 1 : 0);

  return (
    <div className="px-4 pb-24 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between pt-2">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-xl flex items-center justify-center"
               style={{ background: 'linear-gradient(135deg, #0a0a0a 0%, #1f2937 100%)' }}>
            <Shield className="w-4.5 h-4.5 text-white" />
          </div>
          <div>
            <h2 className="text-base font-bold leading-tight">Admin</h2>
            <p className="text-[10px] text-primary-500">Super-admin only</p>
          </div>
        </div>
        <button
          onClick={() => { refresh(); hapticFeedback('light'); }}
          className="p-2 rounded-lg hover:bg-gray-100"
        >
          <RefreshCw className="w-4 h-4 text-primary-500" />
        </button>
      </div>

      {/* Env warnings — never let the admin miss these */}
      {dangerCount > 0 && (
        <div className="rounded-2xl p-3 border"
             style={{ background: 'linear-gradient(135deg, #fef3c7 0%, #fde68a 100%)', borderColor: '#fbbf24' }}>
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle className="w-4 h-4 text-amber-700" />
            <p className="text-xs font-bold text-amber-900">
              {dangerCount} environment issue{dangerCount > 1 ? 's' : ''} detected
            </p>
          </div>
          <ul className="space-y-1.5 text-[11px] text-amber-900">
            {env.force_db_reset_enabled && (
              <li>• <b>FORCE_DB_RESET=true</b> — every restart wipes SQLite. Remove this env var.</li>
            )}
            {!env.vault_key_set && (
              <li>• <b>CREDENTIAL_VAULT_KEY missing</b> — credentials use a temp dev key that won't survive restart.</li>
            )}
            {!env.supabase_configured && (
              <li>• <b>SUPABASE_URL / KEY missing</b> — CV + creds won't survive restart.</li>
            )}
          </ul>
        </div>
      )}

      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-2">
        <StatCard
          icon={<Database className="w-4 h-4" />}
          label="Supabase listings"
          value={overview.supabase.latest_jobs ?? '—'}
          tone="indigo"
        />
        <StatCard
          icon={<Users className="w-4 h-4" />}
          label="Users"
          value={overview.users.total}
          sub={`${overview.users.admins} admin${overview.users.admins === 1 ? '' : 's'}`}
          tone="emerald"
        />
        <StatCard
          icon={<Server className="w-4 h-4" />}
          label="NEXUS layers"
          value={`${overview.nexus.layers_ok?.length ?? 0}/${(overview.nexus.layers_ok?.length ?? 0) + Object.keys(overview.nexus.layers_fail || {}).length}`}
          sub={overview.nexus.triad_live ? 'triad live' : 'triad off'}
          tone={overview.nexus.triad_live ? 'emerald' : 'gray'}
        />
        <StatCard
          icon={<KeyRound className="w-4 h-4" />}
          label="Saved creds"
          value={creds.length}
          sub={`${new Set(creds.map(c => c.telegram_id)).size} user${new Set(creds.map(c => c.telegram_id)).size === 1 ? '' : 's'}`}
          tone="purple"
        />
      </div>

      {/* Scrape control */}
      <Section title="Scrape control" icon={<Play className="w-4 h-4" />}>
        <div className="grid grid-cols-2 gap-2">
          {(['morning', 'afternoon', 'evening', 'auto'] as const).map(w => (
            <button
              key={w}
              onClick={() => triggerScrape(w)}
              disabled={busy.startsWith('scrape:')}
              className="py-2.5 rounded-xl text-xs font-semibold border border-gray-200 bg-white hover:bg-gray-50 disabled:opacity-50 transition-all flex items-center justify-center gap-1.5"
            >
              {busy === `scrape:${w}` ? (
                <RefreshCw className="w-3 h-3 animate-spin" />
              ) : (
                <Play className="w-3 h-3" />
              )}
              <span className="capitalize">{w}</span>
            </button>
          ))}
        </div>
      </Section>

      {/* Saved credentials */}
      <Section title={`Saved portal credentials (${creds.length})`} icon={<Lock className="w-4 h-4" />}>
        {creds.length === 0 ? (
          <p className="text-[11px] text-primary-400 text-center py-4">
            No credentials saved by any user yet.
          </p>
        ) : (
          <div className="space-y-2 max-h-72 overflow-y-auto">
            {creds.map(c => (
              <div
                key={`${c.telegram_id}::${c.portal}`}
                className="flex items-center justify-between p-2.5 rounded-xl bg-gray-50 border border-gray-100"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-[11px] font-semibold truncate">
                    {c.portal} <span className="text-primary-400">·</span>{' '}
                    <span className="text-primary-500">{c.telegram_id}</span>
                  </p>
                  <p className="text-[9px] text-primary-400 mt-0.5">
                    risk: {c.risk_level || '—'} · {fmtRel(c.updated_at)}
                  </p>
                </div>
                <button
                  onClick={() => revokeCreds(c.telegram_id, c.portal)}
                  disabled={busy === `revoke:${c.telegram_id}:${c.portal}`}
                  className="ml-2 p-1.5 rounded-lg hover:bg-red-50 text-red-500 disabled:opacity-50"
                  title="Revoke (encrypted blob deleted from Supabase)"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* User list */}
      <Section title={`Users (${overview.users.users.length})`} icon={<Users className="w-4 h-4" />}>
        <div className="space-y-1.5 max-h-72 overflow-y-auto">
          {overview.users.users.map(u => (
            <div key={u.telegram_id}
                 className="flex items-center gap-2 p-2 rounded-xl bg-white border border-gray-100">
              <div className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold text-white"
                   style={{ background: u.is_admin ? '#0a0a0a' : '#9ca3af' }}>
                {(u.username || '?').slice(0, 1).toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-[11px] font-semibold truncate">
                  @{u.username || 'unknown'}
                </p>
                <p className="text-[9px] text-primary-400">
                  ID: {u.telegram_id}
                </p>
              </div>
              {u.is_admin && (
                <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-black text-white">
                  ADMIN
                </span>
              )}
              <ChevronRight className="w-3 h-3 text-primary-300" />
            </div>
          ))}
          {overview.users.users.length === 0 && (
            <p className="text-[11px] text-primary-400 text-center py-4">
              No users yet — they'll appear after first /start.
            </p>
          )}
        </div>
      </Section>

      {/* NEXUS layer health */}
      <Section title="NEXUS runtime" icon={<Activity className="w-4 h-4" />}>
        <div className="text-[11px] space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-primary-500">Version</span>
            <code className="text-[10px] bg-gray-100 px-1.5 py-0.5 rounded">{overview.nexus.version || '?'}</code>
          </div>
          <div>
            <p className="text-primary-500 mb-1">Healthy layers</p>
            <div className="flex flex-wrap gap-1">
              {(overview.nexus.layers_ok || []).map(L => (
                <span key={L} className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-medium bg-emerald-50 text-emerald-700">
                  <CheckCircle2 className="w-2.5 h-2.5" /> {L}
                </span>
              ))}
              {(overview.nexus.layers_ok || []).length === 0 && (
                <span className="text-[10px] text-primary-400">none reported</span>
              )}
            </div>
          </div>
          {Object.keys(overview.nexus.layers_fail || {}).length > 0 && (
            <div className="mt-2">
              <p className="text-primary-500 mb-1">Failed layers</p>
              <div className="flex flex-wrap gap-1">
                {Object.keys(overview.nexus.layers_fail).map(L => (
                  <span key={L} className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-medium bg-red-50 text-red-700">
                    <XCircle className="w-2.5 h-2.5" /> {L}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </Section>

      {/* Retention */}
      <Section title="Retention policy" icon={<Database className="w-4 h-4" />}>
        <p className="text-[11px] text-primary-500 mb-2 leading-relaxed">
          Score-tiered TTL purge. Low-score (&lt;60) jobs older than <b>15 days</b> are
          deleted; high-score (≥60) older than <b>25 days</b>. Applied jobs are
          NEVER auto-purged. Runs daily at 04:30 IST.
        </p>
        <button
          onClick={triggerPurge}
          disabled={busy === 'purge'}
          className="w-full py-2.5 rounded-xl text-xs font-semibold flex items-center justify-center gap-2 disabled:opacity-50 transition-all"
          style={{
            background: 'linear-gradient(135deg, #f3e8ff 0%, #ede9fe 100%)',
            color: '#5b21b6',
            border: '1px solid #c4b5fd',
          }}
        >
          {busy === 'purge'
            ? <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            : <Trash2 className="w-3.5 h-3.5" />
          }
          Run retention sweep now
        </button>
      </Section>

      {/* Danger zone */}
      <Section title="Danger zone" icon={<AlertTriangle className="w-4 h-4" />} danger>
        <button
          onClick={resetDb}
          disabled={busy === 'reset'}
          className="w-full py-3 rounded-xl text-xs font-semibold flex items-center justify-center gap-2 disabled:opacity-50"
          style={{
            background: 'linear-gradient(135deg, #fee2e2 0%, #fecaca 100%)',
            color: '#991b1b',
            border: '1px solid #fca5a5',
          }}
        >
          {busy === 'reset' ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
          Wipe SQLite cache (Supabase preserved)
        </button>
      </Section>

      <p className="text-[9px] text-primary-300 text-center pt-2">
        Last refresh: {new Date(overview.timestamp).toLocaleTimeString()}
      </p>
    </div>
  );
}

// ============================================================
// Sub-components
// ============================================================

function StatCard({ icon, label, value, sub, tone = 'gray' }: {
  icon: React.ReactNode; label: string; value: any; sub?: string; tone?: string;
}) {
  const TONES: Record<string, { bg: string; fg: string; iconBg: string }> = {
    indigo:  { bg: 'linear-gradient(135deg, #eef2ff 0%, #e0e7ff 100%)', fg: '#3730a3', iconBg: '#6366f1' },
    emerald: { bg: 'linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%)', fg: '#065f46', iconBg: '#10b981' },
    purple:  { bg: 'linear-gradient(135deg, #faf5ff 0%, #f3e8ff 100%)', fg: '#6b21a8', iconBg: '#8b5cf6' },
    gray:    { bg: 'linear-gradient(135deg, #f9fafb 0%, #f3f4f6 100%)', fg: '#374151', iconBg: '#6b7280' },
  };
  const t = TONES[tone] || TONES.gray;
  return (
    <div className="rounded-2xl p-3" style={{ background: t.bg }}>
      <div className="flex items-center gap-1.5 mb-2">
        <div className="w-6 h-6 rounded-lg flex items-center justify-center text-white"
             style={{ background: t.iconBg }}>
          {icon}
        </div>
        <p className="text-[10px] font-semibold" style={{ color: t.fg, opacity: 0.8 }}>
          {label}
        </p>
      </div>
      <p className="text-xl font-bold leading-none" style={{ color: t.fg }}>{value}</p>
      {sub && <p className="text-[10px] mt-1" style={{ color: t.fg, opacity: 0.7 }}>{sub}</p>}
    </div>
  );
}

function Section({ title, icon, children, danger }: {
  title: string; icon: React.ReactNode; children: React.ReactNode; danger?: boolean;
}) {
  return (
    <div className="rounded-2xl bg-white border p-3"
         style={{ borderColor: danger ? '#fca5a5' : '#f3f4f6' }}>
      <div className="flex items-center gap-2 mb-3">
        <span style={{ color: danger ? '#dc2626' : '#0a0a0a' }}>{icon}</span>
        <h3 className="text-[11px] font-bold uppercase tracking-wider"
            style={{ color: danger ? '#991b1b' : '#1f2937' }}>
          {title}
        </h3>
      </div>
      {children}
    </div>
  );
}

function fmtRel(iso?: string): string {
  if (!iso) return 'never';
  try {
    const t = new Date(iso).getTime();
    const diff = Date.now() - t;
    const m = Math.floor(diff / 60000);
    if (m < 1) return 'just now';
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  } catch {
    return iso;
  }
}
