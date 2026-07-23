'use client';

import { Camera, KeyRound, LogOut, Mail, Trash2, UserRound } from 'lucide-react';
import Image from 'next/image';
import { useRouter } from 'next/navigation';
import { FormEvent, useEffect, useRef, useState } from 'react';
import { clearPrivatePwaStorage } from '../../../components/system/pwa-client';
import { Button } from '../../../components/ui/button';
import { useToast } from '../../../components/ui/feedback';
import { withBasePath } from '../../../lib/base-path';
import { DEFAULT_ACCOUNT_AVATAR_PATH } from '../../../lib/brand';

type CurrentUser = {
  id: string;
  email: string;
  name: string;
  avatarUrl?: string | null;
};

type AuthPayload = {
  ok: boolean;
  data?: { user?: CurrentUser };
  error?: { message?: string };
};

const inputClassName = 'mt-2 h-11 w-full rounded-[12px] border border-[#DED8D1] bg-white px-3.5 text-sm text-[#242220] outline-none transition placeholder:text-[#AAA39C] focus:border-[#ED9D86] focus:ring-4 focus:ring-[#FFE4DC]';
const fallbackAvatar = withBasePath(DEFAULT_ACCOUNT_AVATAR_PATH);

export function AccountPanel() {
  const router = useRouter();
  const toast = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
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
    fetch('/api/auth/me')
      .then((response) => response.json() as Promise<AuthPayload>)
      .then((payload) => {
        const nextUser = payload.ok ? payload.data?.user ?? null : null;
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
    await fetch('/api/auth/logout', { method: 'POST' }).catch(() => null);
    await clearPrivatePwaStorage();
    router.replace('/login');
    router.refresh();
  }

  async function uploadAvatar(file: File) {
    if (file.size > 5 * 1024 * 1024) {
      toast.error('头像过大', '请选择不超过 5 MB 的图片');
      return;
    }
    setBusy('avatar');
    const form = new FormData();
    form.append('avatar', file);
    try {
      const response = await fetch('/api/auth/avatar', { method: 'POST', body: form });
      const payload = (await response.json()) as AuthPayload;
      if (!response.ok || !payload.ok) throw new Error(payload.error?.message ?? '上传头像失败');
      applyUser(payload.data?.user);
      toast.success('头像已更新');
    } catch (reason) {
      toast.error('上传头像失败', reason instanceof Error ? reason.message : '请稍后重试');
    } finally {
      setBusy('');
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }

  async function removeAvatar() {
    setBusy('avatar');
    try {
      const response = await fetch('/api/auth/avatar', { method: 'DELETE' });
      const payload = (await response.json()) as AuthPayload;
      if (!response.ok || !payload.ok) throw new Error(payload.error?.message ?? '移除头像失败');
      applyUser(payload.data?.user);
      toast.success('已恢复默认头像');
    } catch (reason) {
      toast.error('移除头像失败', reason instanceof Error ? reason.message : '请稍后重试');
    } finally {
      setBusy('');
    }
  }

  async function saveEmail(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy('email');
    try {
      const response = await fetch('/api/auth/account/email', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim(), currentPassword: emailPassword })
      });
      const payload = (await response.json()) as AuthPayload;
      if (!response.ok || !payload.ok) throw new Error(payload.error?.message ?? '修改邮箱失败');
      applyUser(payload.data?.user);
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
      const response = await fetch('/api/auth/account/name', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: normalizedName })
      });
      const payload = (await response.json()) as AuthPayload;
      if (!response.ok || !payload.ok) throw new Error(payload.error?.message ?? '修改用户名失败');
      applyUser(payload.data?.user);
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
      const response = await fetch('/api/auth/account/password', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ currentPassword, newPassword })
      });
      const payload = (await response.json()) as { ok: boolean; error?: { message?: string } };
      if (!response.ok || !payload.ok) throw new Error(payload.error?.message ?? '修改密码失败');
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
    <section aria-labelledby="account-title" className="space-y-7">
      <div>
        <h3 id="account-title" className="text-lg font-semibold text-[#2A2825]">账户</h3>
        <p className="mt-1 text-sm leading-6 text-[#77716A]">管理头像、用户名、登录邮箱和密码。</p>
      </div>

      <section aria-labelledby="avatar-title" className="flex flex-col gap-4 border-b border-[#DEDAD4] pb-7 sm:flex-row sm:items-center">
        <Image
          key={avatarSrc}
          src={avatarSrc}
          alt="账户头像"
          width={80}
          height={80}
          unoptimized
          onError={() => setAvatarFailed(true)}
          className="h-20 w-20 shrink-0 rounded-full border border-black/[0.06] object-cover shadow-sm"
        />
        <div className="min-w-0 flex-1">
          <h4 id="avatar-title" className="text-sm font-semibold text-[#2A2825]">头像</h4>
          <p className="mt-1 text-sm text-[#77716A]">支持 JPEG、PNG、WebP，系统会自动裁切为正方形，最大 5 MB。</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              className="sr-only"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void uploadAvatar(file);
              }}
            />
            <Button type="button" variant="secondary" icon={Camera} loading={busy === 'avatar'} loadingText="处理中" onClick={() => fileInputRef.current?.click()}>
              {user?.avatarUrl ? '更换头像' : '上传头像'}
            </Button>
            {user?.avatarUrl ? (
              <Button type="button" variant="ghost" icon={Trash2} disabled={busy === 'avatar'} onClick={() => void removeAvatar()}>
                使用默认头像
              </Button>
            ) : null}
          </div>
        </div>
      </section>

      <form onSubmit={saveName} className="border-b border-[#DEDAD4] pb-7">
        <div className="flex items-center gap-2 text-sm font-semibold text-[#2A2825]"><UserRound size={16} />用户名</div>
        <p className="mt-1 text-sm text-[#77716A]">用于侧边栏和账户区域展示，不影响登录。</p>
        <label className="mt-4 block max-w-md text-sm text-[#5F5A55]">
          用户名
          <input type="text" required minLength={1} maxLength={40} autoComplete="name" value={name} onChange={(event) => setName(event.target.value)} className={inputClassName} />
        </label>
        <Button type="submit" className="mt-4" loading={busy === 'name'} loadingText="保存中" disabled={!name.trim() || name.trim() === user?.name}>
          保存用户名
        </Button>
      </form>

      <form onSubmit={saveEmail} className="border-b border-[#DEDAD4] pb-7">
        <div className="flex items-center gap-2 text-sm font-semibold text-[#2A2825]"><Mail size={16} />登录邮箱</div>
        <div className="mt-4 grid max-w-2xl gap-4 sm:grid-cols-2">
          <label className="text-sm text-[#5F5A55]">
            邮箱
            <input type="email" required autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} className={inputClassName} />
          </label>
          <label className="text-sm text-[#5F5A55]">
            当前密码
            <input type="password" required maxLength={128} autoComplete="current-password" value={emailPassword} onChange={(event) => setEmailPassword(event.target.value)} className={inputClassName} />
          </label>
        </div>
        <Button type="submit" className="mt-4" loading={busy === 'email'} loadingText="保存中" disabled={!email.trim() || !emailPassword}>
          修改邮箱
        </Button>
      </form>

      <form onSubmit={savePassword} className="border-b border-[#DEDAD4] pb-7">
        <div className="flex items-center gap-2 text-sm font-semibold text-[#2A2825]"><KeyRound size={16} />修改密码</div>
        <p className="mt-1 text-sm text-[#77716A]">修改后会退出所有已登录设备。</p>
        <div className="mt-4 grid max-w-3xl gap-4 md:grid-cols-3">
          <label className="text-sm text-[#5F5A55]">
            当前密码
            <input type="password" required maxLength={128} autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} className={inputClassName} />
          </label>
          <label className="text-sm text-[#5F5A55]">
            新密码
            <input type="password" required minLength={10} maxLength={128} autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} className={inputClassName} />
          </label>
          <label className="text-sm text-[#5F5A55]">
            再次输入新密码
            <input type="password" required minLength={10} maxLength={128} autoComplete="new-password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} className={inputClassName} />
          </label>
        </div>
        <Button type="submit" className="mt-4" loading={busy === 'password'} loadingText="更新中" disabled={!currentPassword || !newPassword || !confirmPassword}>
          更新密码
        </Button>
      </form>

      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <div className="text-sm font-medium text-[#2A2825]">退出当前设备</div>
          <div className="mt-1 truncate text-sm text-[#77716A]">{user?.email ?? '正在读取账户…'}</div>
        </div>
        <Button type="button" variant="ghost" icon={LogOut} loading={busy === 'logout'} loadingText="退出中" onClick={() => void logout()}>
          退出登录
        </Button>
      </div>
    </section>
  );
}
