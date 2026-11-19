'use client';

import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/button';
import type { NetworkProxyView, ProxyProbe, StoredProxy } from '@/generated/network-proxy';
import { useI18n } from '@/i18n/provider';
import { useReleaseFeed } from '../../updates/public';
import { fetchNetworkProxy, saveNetworkProxy, testNetworkProxy } from '../api/network-proxy-client';

const presets = ['updates', 'github', 'bangumi'] as const;
type Preset = typeof presets[number];
const input = 'mt-1.5 w-full rounded-xl border border-[#DEDAD4] bg-white px-3 py-2 text-[#272522] focus-visible:outline-2 focus-visible:outline-[#EF4D2F]';

export function NetworkProxySettingsPanel() {
  const { t } = useI18n();
  const releaseFeed = useReleaseFeed();
  const [settings, setSettings] = useState<NetworkProxyView>();
  const [protocol, setProtocol] = useState<'http' | 'socks5'>('http');
  const [host, setHost] = useState('');
  const [port, setPort] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState<string>();
  const [selected, setSelected] = useState<Preset[]>([]);
  const [domains, setDomains] = useState('');
  const [busy, setBusy] = useState<'test' | 'save' | null>(null);
  const [notice, setNotice] = useState<{ error: boolean; text: string }>();
  const [results, setResults] = useState<ProxyProbe[]>();
  const [loadAttempt, setLoadAttempt] = useState(0);
  const controller = useRef<AbortController | null>(null);
  const form = useRef<HTMLFormElement>(null);

  function load(next: NetworkProxyView) {
    setSettings(next);
    setProtocol(next.connection?.protocol ?? 'http');
    setHost(next.connection?.host ?? '');
    setPort(next.connection ? String(next.connection.port) : '');
    setUsername(next.connection?.username ?? '');
    setPassword(undefined);
    setSelected(next.presets);
    setDomains(next.domains.join('\n'));
  }

  useEffect(() => {
    const abort = new AbortController();
    fetchNetworkProxy(abort.signal).then(next => {
      if (!abort.signal.aborted) load(next);
    }).catch(() => {
      if (!abort.signal.aborted) setNotice({ error: true, text: '读取代理设置失败' });
    });
    return () => { abort.abort(); controller.current?.abort(); };
  }, [loadAttempt]);

  const presetLabels = { updates: t('版本更新'), github: 'GitHub', bangumi: 'Bangumi' };
  const resultLabels = {
    connected: t('连接成功'), timeout: t('连接超时'), authentication: t('代理认证失败'),
    failed: t('连接失败'), not_configured: t('尚未配置代理')
  };

  async function submit(action: 'test' | 'save') {
    if (controller.current || !form.current?.reportValidity()) return;
    if (host.trim() && !port || !host.trim() && port) {
      setNotice({ error: true, text: '请填写代理服务器地址和端口' });
      return;
    }
    const body: StoredProxy = {
      connection: host.trim() ? { protocol, host: host.trim(), port: Number(port), username, password } : null,
      presets: selected, domains: domains.split('\n').map(domain => domain.trim()).filter(Boolean)
    };
    const abort = new AbortController();
    controller.current = abort;
    setBusy(action);
    setNotice(undefined);
    try {
      if (action === 'test') {
        setResults(undefined);
        const data = await testNetworkProxy(body, abort.signal);
        if (!abort.signal.aborted) setResults(data);
      } else {
        const data = await saveNetworkProxy(body, abort.signal);
        if (!abort.signal.aborted) {
          load(data);
          setNotice({ error: false, text: '代理设置已保存' });
          releaseFeed.retry();
        }
      }
    } catch {
      if (!abort.signal.aborted) setNotice({ error: true, text: action === 'test' ? '测试代理连接失败' : '保存代理设置失败' });
    } finally {
      controller.current = null;
      if (!abort.signal.aborted) setBusy(null);
    }
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submit('save');
  }

  if (!settings) return notice
    ? <div className="space-y-3"><p role="alert">{t(notice.text)}</p><Button variant="secondary" onClick={() => { setNotice(undefined); setLoadAttempt(value => value + 1); }}>{t('重试')}</Button></div>
    : <p role="status" className="text-sm text-[#77716A]">{t('正在加载')}</p>;

  return <form ref={form} onSubmit={save} onChange={() => setResults(undefined)} className="space-y-6 text-sm">
    <fieldset disabled={busy !== null} className="space-y-4">
      <legend className="mb-4 text-lg font-semibold">{t('代理连接')}</legend>
      <div className="grid gap-4 sm:grid-cols-[1fr_2fr_1fr]">
        <label>{t('协议')}<select className={input} value={protocol} onChange={event => setProtocol(event.target.value === 'socks5' ? 'socks5' : 'http')}>
          <option value="http">HTTP</option><option value="socks5">SOCKS5</option>
        </select></label>
        <label>{t('服务器地址')}<input className={input} value={host} placeholder="proxy.example.com" onChange={event => setHost(event.target.value)} /></label>
        <label>{t('端口')}<input className={input} type="number" min="1" max="65535" value={port} onChange={event => setPort(event.target.value)} /></label>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <label>{t('用户名（可选）')}<input className={input} autoComplete="off" value={username} onChange={event => setUsername(event.target.value)} /></label>
        <div>
          <label>{t('密码（可选）')}<input className={input} type="password" autoComplete="new-password" value={password ?? ''} placeholder={settings.connection?.passwordConfigured && password === undefined ? t('已配置') : undefined} onChange={event => setPassword(event.target.value)} /></label>
          {settings.connection?.passwordConfigured ? <button type="button" className="mt-2 text-[#D94329] underline" onClick={() => { setPassword(password === '' ? undefined : ''); setResults(undefined); }}>{password === '' ? t('保留已保存的密码') : t('清除已保存的密码')}</button> : null}
        </div>
      </div>
    </fieldset>

    <fieldset disabled={busy !== null} className="border-t border-[#DEDAD4] pt-5">
      <h3 className="text-lg font-semibold">{t('代理域名')}</h3>
      <div className="my-4 flex flex-wrap gap-x-6 gap-y-3">
        {presets.map(preset => <label key={preset} className="flex items-center gap-2">
          <input type="checkbox" className="size-4 accent-[#EF4D2F]" checked={selected.includes(preset)} onChange={event => setSelected(current => event.target.checked ? [...current, preset] : current.filter(key => key !== preset))} />
          {presetLabels[preset]}
        </label>)}
      </div>
      <details className="mb-4">
        <summary className="w-fit cursor-pointer text-[#D94329]">{t('查看域名')}</summary>
        <dl className="mt-2 space-y-2 break-words text-[#645F59]">{presets.map(preset => <div key={preset}><dt className="font-medium">{presetLabels[preset]}</dt><dd>{settings.presetDomains[preset]?.join(', ')}</dd></div>)}</dl>
      </details>
      <label>{t('自定义域名')}
        <span className="mt-1 block text-[#77716A]">{t('每行一个域名，同时匹配其子域名。')}</span>
        <textarea className={input} rows={3} value={domains} placeholder="api.example.com" onChange={event => setDomains(event.target.value)} />
      </label>
    </fieldset>
    <div className="flex flex-wrap justify-end gap-3 border-t border-[#DEDAD4] pt-4">
      <Button variant="secondary" type="button" loading={busy === 'test'} disabled={busy !== null} onClick={() => void submit('test')}>{t('测试连接')}</Button>
      <Button type="submit" loading={busy === 'save'} disabled={busy !== null}>{t('保存设置')}</Button>
    </div>
    {notice ? <p role={notice.error ? 'alert' : 'status'} className={notice.error ? 'text-[#A5251C]' : 'text-[#23643E]'}>{t(notice.text)}</p> : null}
    {results ? <section aria-live="polite" aria-labelledby="proxy-test-results">
      <h3 id="proxy-test-results" className="mb-3 text-lg font-semibold">{t('连接测试结果')}</h3>
      {results.length ? <ul className="divide-y divide-[#DEDAD4]">{results.map(row => <li key={row.host} className="grid gap-1 py-2 sm:grid-cols-[2fr_1fr_1fr] sm:gap-3">
        <span className="break-all">{row.host}</span>
        <span className="break-all text-[#645F59]">{row.rules.map(rule => presets.includes(rule as Preset) ? presetLabels[rule as Preset] : rule).join(', ')}</span>
        <span className={row.result === 'connected' ? 'text-[#23643E]' : 'text-[#99441C]'}>{resultLabels[row.result]}</span>
      </li>)}</ul> : <p>{t('没有需要测试的代理域名')}</p>}
    </section> : null}
  </form>;
}
