'use client';

import { apiV2Fetch } from '@/lib/api-v2';
import type { AccountResponse, ProblemDetails } from '@/generated/api-v2';

import { KeyRound, LogOut } from 'lucide-react';
import Image from 'next/image';
import { useRouter } from 'next/navigation';
import { FormEvent, useEffect, useState } from 'react';
import { clearPrivatePwaStorage } from '../../../components/system/pwa-client';
import { Button } from '../../../components/ui/button';
import { useToast } from '../../../components/ui/feedback';
import { withBasePath } from '../../../lib/base-path';
import { DEFAULT_ACCOUNT_AVATAR_PATH } from '../../../lib/brand';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

type CurrentUser = {
  id: string;
  email: string;
  name: string;
  avatarUrl?: string | null;
};

const inputClassName = 'mt-1.5 h-10 w-full rounded-[10px] border border-[#DED8D1] bg-white px-3 text-sm text-[#242220] outline-none transition placeholder:text-[#AAA39C] focus:border-[#ED9D86] focus:ring-3 focus:ring-[#FFE4DC]';
const fallbackAvatar = withBasePath(DEFAULT_ACCOUNT_AVATAR_PATH);

export function AccountPanel() {
  const { t: i18nAttribute } = useAttributeI18n();
  const router = useRouter();
  const toast = useToast();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [emailPassword, setEmailPassword] = useState('');
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [busy, setBusy] = useState('');
  const [avatarFailed, setAvatarFailed] = useState(false);

  useEffect(() => {
    let active = true;
    apiV2Fetch('/api/v2/account')
      .then(readAccount)
      .then((account) => {
        const nextUser = currentUser(account);
        if (!active) return;
        setUser(nextUser);
        setName(nextUser?.name ?? '');
        setEmail(nextUser?.email ?? '');
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  const avatarSrc = user?.avatarUrl && !avatarFailed ? withBasePath(user.avatarUrl) : fallbackAvatar;

  function currentUser(account: AccountResponse): CurrentUser {
    return {
      id: account.id,
      email: account.email,
      name: account.displayName,
      avatarUrl: null
    };
  }

  async function readAccount(response: Response): Promise<AccountResponse> {
    const payload = await response.json().catch(() => null) as AccountResponse | ProblemDetails | null;
    if (!response.ok || !payload || !('id' in payload)) {
      throw new Error(payload && 'detail' in payload ? payload.detail : '读取账户失败');
    }
    return payload;
  }

  function applyUser(nextUser: CurrentUser | undefined) {
    if (!nextUser) return;
    setUser(nextUser);
    setName(nextUser.name);
    setEmail(nextUser.email);
    setAvatarFailed(false);
    window.dispatchEvent(new CustomEvent('shuku:account-changed', { detail: nextUser }));
  }

  async function logout() {
    setBusy('logout');
    await apiV2Fetch('/api/v2/auth/logout', { method: 'POST' }).catch(() => null);
    await clearPrivatePwaStorage();
    router.replace('/login');
    router.refresh();
  }

  async function saveEmail(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy('email');
    try {
      const response = await apiV2Fetch('/api/v2/account', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim(), currentPassword: emailPassword })
      });
      applyUser(currentUser(await readAccount(response)));
      setEmailPassword('');
      toast.success('登录邮箱已更新');
    } catch (reason) {
      toast.error('修改邮箱失败', reason instanceof Error ? reason.message : '请稍后重试');
    } finally {
      setBusy('');
    }
  }

  async function saveName(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedName = name.trim();
    if (!normalizedName) {
      toast.error('请输入用户名');
      return;
    }
    setBusy('name');
    try {
      const response = await apiV2Fetch('/api/v2/account', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ displayName: normalizedName })
      });
      applyUser(currentUser(await readAccount(response)));
      toast.success('用户名已更新');
    } catch (reason) {
      toast.error('修改用户名失败', reason instanceof Error ? reason.message : '请稍后重试');
    } finally {
      setBusy('');
    }
  }

  async function savePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (newPassword !== confirmPassword) {
      toast.error('两次输入的新密码不一致');
      return;
    }
    if (newPassword.length < 10) {
      toast.error('新密码至少需要 10 个字符');
      return;
    }
    setBusy('password');
    try {
      const response = await apiV2Fetch('/api/v2/account', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ currentPassword, password: newPassword })
      });
      await readAccount(response);
      toast.success('密码已更新', '请使用新密码重新登录');
      await clearPrivatePwaStorage();
      router.replace('/login');
      router.refresh();
    } catch (reason) {
      toast.error('修改密码失败', reason instanceof Error ? reason.message : '请稍后重试');
      setBusy('');
    }
  }

  return (
    <section aria-labelledby="account-title" className="rounded-[20px] border border-[#E2DED8] bg-white p-4 sm:p-5">
      <div>
        <h3 id="account-title" className="text-base font-semibold text-[#2A2825]"><I18nText>账户</I18nText></h3>
        <p className="mt-0.5 text-xs leading-5 text-[#77716A]"><I18nText>管理用户名、登录邮箱和密码。</I18nText></p>
      </div>

      <section aria-labelledby="avatar-title" className="mt-4 flex flex-col gap-3 rounded-2xl bg-[#F7F4F0] p-3 sm:flex-row sm:items-center">
        <Image
          key={avatarSrc}
          src={avatarSrc}
          alt={i18nAttribute("账户头像")}
          width={64}
          height={64}
          unoptimized
          onError={() => setAvatarFailed(true)}
          className="h-16 w-16 shrink-0 rounded-full border border-black/[0.06] object-cover shadow-sm"
        />
        <div className="min-w-0 flex-1">
          <h4 id="avatar-title" className="text-sm font-semibold text-[#2A2825]"><I18nText>头像</I18nText></h4>
          <p className="mt-0.5 text-xs leading-5 text-[#77716A]"><I18nText>使用默认账户头像。</I18nText></p>
        </div>
      </section>

      <form onSubmit={saveName} className="mt-4 border-t border-[#E8E3DD] pt-4">
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
          <label className="block text-sm font-medium text-[#5F5A55]">
            <I18nText>用户名</I18nText>
            <input type="text" required minLength={1} maxLength={40} autoComplete="name" value={name} onChange={(event) => setName(event.target.value)} className={inputClassName} />
          </label>
          <Button type="submit" loading={busy === 'name'} loadingText={i18nAttribute("保存中")} disabled={!name.trim() || name.trim() === user?.name}>
            <I18nText>保存用户名</I18nText>
          </Button>
        </div>
        <p className="mt-1.5 text-xs text-[#817A73]"><I18nText>用于侧边栏和账户区域展示，不影响登录。</I18nText></p>
      </form>

      <form onSubmit={saveEmail} className="mt-4 border-t border-[#E8E3DD] pt-4">
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] lg:items-end">
          <label className="text-sm font-medium text-[#5F5A55]">
            <I18nText>登录邮箱</I18nText>
            <input type="email" required autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} className={inputClassName} />
          </label>
          <label className="text-sm font-medium text-[#5F5A55]">
            <I18nText>当前密码</I18nText>
            <input type="password" required maxLength={128} autoComplete="current-password" value={emailPassword} onChange={(event) => setEmailPassword(event.target.value)} className={inputClassName} />
          </label>
          <Button type="submit" loading={busy === 'email'} loadingText={i18nAttribute("保存中")} disabled={!email.trim() || !emailPassword}>
            <I18nText>修改邮箱</I18nText>
          </Button>
        </div>
      </form>

      <form onSubmit={savePassword} className="mt-4 border-t border-[#E8E3DD] pt-4">
        <div className="flex items-center gap-2 text-sm font-semibold text-[#2A2825]">
          <KeyRound size={16} aria-hidden="true" />
          <I18nText>修改密码</I18nText>
        </div>
        <p className="mt-0.5 text-xs text-[#77716A]"><I18nText>修改后会退出所有已登录设备。</I18nText></p>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          <label className="text-sm font-medium text-[#5F5A55]">
            <I18nText>当前密码</I18nText>
            <input type="password" required maxLength={128} autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} className={inputClassName} />
          </label>
          <label className="text-sm font-medium text-[#5F5A55]">
            <I18nText>新密码</I18nText>
            <input type="password" required minLength={10} maxLength={128} autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} className={inputClassName} />
          </label>
          <label className="text-sm font-medium text-[#5F5A55]">
            <I18nText>再次输入新密码</I18nText>
            <input type="password" required minLength={10} maxLength={128} autoComplete="new-password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} className={inputClassName} />
          </label>
        </div>
        <div className="mt-3 flex justify-end">
          <Button type="submit" loading={busy === 'password'} loadingText={i18nAttribute("更新中")} disabled={!currentPassword || !newPassword || !confirmPassword}>
            <I18nText>更新密码</I18nText>
          </Button>
        </div>
      </form>

      <div className="mt-4 flex items-center justify-between gap-4 border-t border-[#E8E3DD] pt-4">
        <div className="min-w-0">
          <div className="text-sm font-medium text-[#2A2825]"><I18nText>退出当前设备</I18nText></div>
          <div className="mt-0.5 truncate text-xs text-[#77716A]">{user?.email ?? i18nAttribute("正在读取账户…")}</div>
        </div>
        <Button type="button" variant="ghost" icon={LogOut} loading={busy === 'logout'} loadingText={i18nAttribute("退出中")} onClick={() => void logout()}>
          <I18nText>退出登录</I18nText>
        </Button>
      </div>
    </section>
  );
}
