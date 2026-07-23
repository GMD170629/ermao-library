'use client';

import { KeyRound, Plus, Save, ShieldCheck, Trash2, UserRoundCheck, UserRoundX } from 'lucide-react';
import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { Button } from '../../../components/ui/button';
import { cn } from '../../../components/ui/cn';
import { useToast } from '../../../components/ui/feedback';
import { useI18n } from '../../../i18n/provider';
import { SettingsCenterShell } from './settings-center-shell';

type UserRole = 'admin' | 'member';
type UserStatus = 'active' | 'disabled';

type ManagedUser = {
  id: string;
  name: string;
  email: string;
  role: UserRole;
  status: UserStatus;
  canManageSystem: boolean;
  canViewManualImports: boolean;
  monitorFolderIds: string[];
  locale: 'zh-CN' | 'en-US';
  authzVersion: number;
  createdAt?: string | number;
};

type MonitorFolder = {
  id: string;
  name: string;
  rootPath: string;
};

type UserForm = {
  name: string;
  email: string;
  password: string;
  role: UserRole;
  status: UserStatus;
  canManageSystem: boolean;
  canViewManualImports: boolean;
  monitorFolderIds: string[];
  locale: 'zh-CN' | 'en-US';
};

const emptyForm: UserForm = {
  name: '',
  email: '',
  password: '',
  role: 'member',
  status: 'active',
  canManageSystem: false,
  canViewManualImports: false,
  monitorFolderIds: [],
  locale: 'zh-CN'
};

function formFromUser(user: ManagedUser): UserForm {
  return {
    name: user.name,
    email: user.email,
    password: '',
    role: user.role,
    status: user.status,
    canManageSystem: user.canManageSystem,
    canViewManualImports: user.canViewManualImports,
    monitorFolderIds: user.monitorFolderIds ?? [],
    locale: user.locale
  };
}

async function apiRequest(path: string, init?: RequestInit) {
  const response = await fetch(path, {
    credentials: 'same-origin',
    ...init,
    headers: init?.body ? { 'Content-Type': 'application/json', ...init.headers } : init?.headers
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload?.ok) {
    const error = new Error(payload?.error?.message ?? '请求失败') as Error & { status?: number };
    error.status = response.status;
    throw error;
  }
  return payload.data;
}

export function UsersPermissionsPage() {
  const { t, formatDateTime } = useI18n();
  const toast = useToast();
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [folders, setFolders] = useState<MonitorFolder[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState<UserForm>(emptyForm);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [forbidden, setForbidden] = useState(false);
  const [passwordTarget, setPasswordTarget] = useState<ManagedUser | null>(null);
  const [password, setPassword] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<ManagedUser | null>(null);
  const [deleteConfirmation, setDeleteConfirmation] = useState('');

  const selected = useMemo(
    () => users.find((user) => user.id === selectedId) ?? null,
    [selectedId, users]
  );

  async function refresh(preferredUserId?: string) {
    setLoading(true);
    try {
      const [usersData, folderData] = await Promise.all([
        apiRequest('/api/admin/users'),
        apiRequest('/api/monitor-folders')
      ]);
      const nextUsers = (usersData?.users ?? []) as ManagedUser[];
      setUsers(nextUsers);
      setFolders((folderData?.folders ?? []) as MonitorFolder[]);
      const nextId = preferredUserId && nextUsers.some((user) => user.id === preferredUserId)
        ? preferredUserId
        : selectedId && nextUsers.some((user) => user.id === selectedId)
          ? selectedId
          : nextUsers[0]?.id ?? null;
      setSelectedId(nextId);
      const nextSelected = nextUsers.find((user) => user.id === nextId);
      if (nextSelected && !creating) setForm(formFromUser(nextSelected));
      setForbidden(false);
    } catch (reason) {
      if ((reason as Error & { status?: number }).status === 403) setForbidden(true);
      else toast.error(t('读取用户列表失败'), reason instanceof Error ? t(reason.message) : t('请稍后重试'));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
    // Initial authorization and data load only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function selectUser(user: ManagedUser) {
    setCreating(false);
    setSelectedId(user.id);
    setForm(formFromUser(user));
  }

  function startCreating() {
    setCreating(true);
    setSelectedId(null);
    setForm(emptyForm);
  }

  function toggleFolder(folderId: string) {
    setForm((current) => ({
      ...current,
      monitorFolderIds: current.monitorFolderIds.includes(folderId)
        ? current.monitorFolderIds.filter((id) => id !== folderId)
        : [...current.monitorFolderIds, folderId]
    }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (saving) return;
    setSaving(true);
    try {
      const body = {
        name: form.name.trim(),
        email: form.email.trim(),
        role: form.role,
        status: form.status,
        canManageSystem: form.role === 'member' && form.canManageSystem,
        canViewManualImports: form.role === 'member' && form.canViewManualImports,
        monitorFolderIds: form.role === 'member' ? form.monitorFolderIds : [],
        locale: form.locale,
        ...(creating ? { password: form.password } : {})
      };
      const data = await apiRequest(
        creating ? '/api/admin/users' : `/api/admin/users/${encodeURIComponent(selectedId ?? '')}`,
        { method: creating ? 'POST' : 'PATCH', body: JSON.stringify(body) }
      );
      toast.success(creating ? t('用户已创建') : t('用户与权限已更新'));
      setCreating(false);
      await refresh(data?.user?.id);
    } catch (reason) {
      toast.error(t('保存用户失败'), reason instanceof Error ? t(reason.message) : t('请稍后重试'));
    } finally {
      setSaving(false);
    }
  }

  async function toggleStatus(user: ManagedUser) {
    try {
      await apiRequest(`/api/admin/users/${encodeURIComponent(user.id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: user.status === 'active' ? 'disabled' : 'active' })
      });
      toast.success(user.status === 'active' ? t('用户已停用，会话已撤销') : t('用户已启用'));
      await refresh(user.id);
    } catch (reason) {
      toast.error(t('更新用户状态失败'), reason instanceof Error ? t(reason.message) : t('请稍后重试'));
    }
  }

  async function resetPassword(event: FormEvent) {
    event.preventDefault();
    if (!passwordTarget) return;
    try {
      await apiRequest(`/api/admin/users/${encodeURIComponent(passwordTarget.id)}/password`, {
        method: 'PUT',
        body: JSON.stringify({ password })
      });
      toast.success(t('密码已重置，该用户的全部会话已撤销'));
      setPasswordTarget(null);
      setPassword('');
    } catch (reason) {
      toast.error(t('重置密码失败'), reason instanceof Error ? t(reason.message) : t('请稍后重试'));
    }
  }

  async function permanentlyDelete(event: FormEvent) {
    event.preventDefault();
    if (!deleteTarget) return;
    try {
      await apiRequest(`/api/admin/users/${encodeURIComponent(deleteTarget.id)}`, {
        method: 'DELETE',
        body: JSON.stringify({ confirmation: deleteConfirmation })
      });
      toast.success(t('用户及其个人数据已永久删除'));
      setDeleteTarget(null);
      setDeleteConfirmation('');
      await refresh();
    } catch (reason) {
      toast.error(t('永久删除用户失败'), reason instanceof Error ? t(reason.message) : t('请稍后重试'));
    }
  }

  if (forbidden) {
    return (
      <SettingsCenterShell title="用户管理" description="仅管理员可以查看和修改用户、角色与书库范围。">
        <div className="rounded-2xl border border-amber-200 bg-amber-50 px-5 py-6 text-sm text-amber-900" role="alert">
          {t('你没有管理用户与权限的权限。')}
        </div>
      </SettingsCenterShell>
    );
  }

  return (
    <SettingsCenterShell
      title="用户管理"
      description="管理账户状态、系统管理能力和每位用户可访问的书库来源。"
      actions={(
        <Button onClick={startCreating}>
          <Plus size={17} />
          {t('创建用户')}
        </Button>
      )}
    >
      <div className="grid gap-6 xl:grid-cols-[minmax(250px,0.75fr)_minmax(0,1.55fr)]">
        <section aria-label={t('用户列表')} className="overflow-hidden rounded-[22px] border border-[#E2DED8] bg-white">
          {loading ? <div className="p-5 text-sm text-[#77716A]" role="status">{t('正在读取用户…')}</div> : null}
          {!loading && users.length === 0 ? <div className="p-5 text-sm text-[#77716A]">{t('暂无用户')}</div> : null}
          <div className="divide-y divide-[#EEEAE5]">
            {users.map((user) => (
              <button
                key={user.id}
                type="button"
                onClick={() => selectUser(user)}
                aria-current={!creating && selectedId === user.id ? 'true' : undefined}
                className={cn(
                  'flex w-full items-start gap-3 px-4 py-4 text-left transition',
                  !creating && selectedId === user.id ? 'bg-[#FFF2ED]' : 'hover:bg-[#FAF8F5]'
                )}
              >
                <span className={cn(
                  'mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full',
                  user.status === 'disabled' ? 'bg-[#EEEAE5] text-[#89827A]' : 'bg-[#FCE5DE] text-[#D94A2E]'
                )}>
                  {user.role === 'admin' ? <ShieldCheck size={18} /> : <UserRoundCheck size={18} />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    <span data-i18n-skip className="truncate text-sm font-semibold text-[#292623]">{user.name}</span>
                    {user.status === 'disabled' ? <span className="rounded-full bg-[#EAE6E1] px-2 py-0.5 text-[10px] text-[#746E68]">{t('已停用')}</span> : null}
                  </span>
                  <span data-i18n-skip className="mt-1 block truncate text-xs text-[#817A73]">{user.email}</span>
                  <span className="mt-1.5 block text-[11px] text-[#9A938C]">
                    {user.role === 'admin' ? t('管理员') : user.canManageSystem ? t('系统管理用户') : t('普通用户')}
                  </span>
                </span>
              </button>
            ))}
          </div>
        </section>

        <form onSubmit={submit} className="rounded-[22px] border border-[#E2DED8] bg-white p-5 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h3 className="text-xl font-semibold text-[#272522]">{creating ? t('创建用户') : t('编辑用户')}</h3>
              {!creating && selected?.createdAt ? (
                <p className="mt-1 text-xs text-[#8B847D]">{t('创建于 {value0}', { value0: formatDateTime(selected.createdAt) })}</p>
              ) : null}
            </div>
            {!creating && selected ? (
              <div className="flex flex-wrap gap-2">
                <Button type="button" variant="secondary" onClick={() => { setPasswordTarget(selected); setPassword(''); }}>
                  <KeyRound size={16} />
                  {t('重置密码')}
                </Button>
                <Button type="button" variant="secondary" onClick={() => void toggleStatus(selected)}>
                  {selected.status === 'active' ? <UserRoundX size={16} /> : <UserRoundCheck size={16} />}
                  {selected.status === 'active' ? t('停用') : t('启用')}
                </Button>
                <Button type="button" variant="secondary" onClick={() => { setDeleteTarget(selected); setDeleteConfirmation(''); }}>
                  <Trash2 size={16} />
                  {t('永久删除')}
                </Button>
              </div>
            ) : null}
          </div>

          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            <label className="text-sm font-medium text-[#3E3935]">
              {t('姓名')}
              <input required maxLength={40} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} className="mt-2 h-11 w-full rounded-xl border border-[#DCD7D1] px-3 outline-none focus:border-[#E9775C] focus:ring-2 focus:ring-[#FAD9D0]" />
            </label>
            <label className="text-sm font-medium text-[#3E3935]">
              {t('邮箱')}
              <input required type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} className="mt-2 h-11 w-full rounded-xl border border-[#DCD7D1] px-3 outline-none focus:border-[#E9775C] focus:ring-2 focus:ring-[#FAD9D0]" />
            </label>
            {creating ? (
              <label className="text-sm font-medium text-[#3E3935]">
                {t('初始密码')}
                <input required minLength={10} maxLength={128} type="password" autoComplete="new-password" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} className="mt-2 h-11 w-full rounded-xl border border-[#DCD7D1] px-3 outline-none focus:border-[#E9775C] focus:ring-2 focus:ring-[#FAD9D0]" />
                <span className="mt-1.5 block text-xs font-normal text-[#89827B]">{t('至少 10 个字符，由管理员安全地告知用户。')}</span>
              </label>
            ) : null}
            <label className="text-sm font-medium text-[#3E3935]">
              {t('界面语言')}
              <select value={form.locale} onChange={(event) => setForm({ ...form, locale: event.target.value as UserForm['locale'] })} className="mt-2 h-11 w-full rounded-xl border border-[#DCD7D1] bg-white px-3 outline-none focus:border-[#E9775C] focus:ring-2 focus:ring-[#FAD9D0]">
                <option value="zh-CN">简体中文</option>
                <option value="en-US">English</option>
              </select>
            </label>
            <label className="text-sm font-medium text-[#3E3935]">
              {t('角色')}
              <select value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value as UserRole })} className="mt-2 h-11 w-full rounded-xl border border-[#DCD7D1] bg-white px-3 outline-none focus:border-[#E9775C] focus:ring-2 focus:ring-[#FAD9D0]">
                <option value="member">{t('普通用户')}</option>
                <option value="admin">{t('管理员')}</option>
              </select>
            </label>
            {!creating ? (
              <label className="text-sm font-medium text-[#3E3935]">
                {t('账户状态')}
                <select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value as UserStatus })} className="mt-2 h-11 w-full rounded-xl border border-[#DCD7D1] bg-white px-3 outline-none focus:border-[#E9775C] focus:ring-2 focus:ring-[#FAD9D0]">
                  <option value="active">{t('有效')}</option>
                  <option value="disabled">{t('已停用')}</option>
                </select>
              </label>
            ) : null}
          </div>

          {form.role === 'admin' ? (
            <div className="mt-6 rounded-2xl border border-[#F2C6B9] bg-[#FFF5F1] px-4 py-3 text-sm leading-6 text-[#8A3E2B]">
              {t('管理员隐式拥有全部书库、系统设置和用户管理权限，不保存额外的文件夹授权。')}
            </div>
          ) : (
            <>
              <fieldset className="mt-6">
                <legend className="text-sm font-semibold text-[#35312D]">{t('管理权限')}</legend>
                <label className="mt-3 flex cursor-pointer items-start gap-3 rounded-2xl border border-[#E3DED8] bg-[#FCFBF9] p-4">
                  <input type="checkbox" checked={form.canManageSystem} onChange={(event) => setForm({ ...form, canManageSystem: event.target.checked })} className="mt-0.5 h-4 w-4 accent-[#E9583A]" />
                  <span>
                    <span className="block text-sm font-semibold text-[#35312D]">{t('允许管理系统')}</span>
                    <span className="mt-1 block text-xs leading-5 text-[#7C756E]">{t('可管理目录、导入整理、日志和备份恢复；这些能力可能接触全量数据。')}</span>
                  </span>
                </label>
              </fieldset>

              <fieldset className="mt-6">
                <legend className="text-sm font-semibold text-[#35312D]">{t('书库文件夹查看范围')}</legend>
                <p className="mt-1 text-xs leading-5 text-[#817A73]">{t('未选择任何范围时，该用户默认看不到书库内容。')}</p>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-[#E3DED8] px-3.5 py-3">
                    <input type="checkbox" checked={form.canViewManualImports} onChange={(event) => setForm({ ...form, canViewManualImports: event.target.checked })} className="mt-0.5 h-4 w-4 accent-[#E9583A]" />
                    <span>
                      <span className="block text-sm font-medium text-[#35312D]">{t('手动导入')}</span>
                      <span className="mt-0.5 block text-xs text-[#817A73]">{t('不属于监控文件夹的内容')}</span>
                    </span>
                  </label>
                  {folders.map((folder) => (
                    <label key={folder.id} className="flex cursor-pointer items-start gap-3 rounded-xl border border-[#E3DED8] px-3.5 py-3">
                      <input type="checkbox" checked={form.monitorFolderIds.includes(folder.id)} onChange={() => toggleFolder(folder.id)} className="mt-0.5 h-4 w-4 accent-[#E9583A]" />
                      <span className="min-w-0">
                        <span data-i18n-skip className="block truncate text-sm font-medium text-[#35312D]">{folder.name}</span>
                        <span data-i18n-skip className="mt-0.5 block truncate text-xs text-[#817A73]">{folder.rootPath}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>
            </>
          )}

          <div className="mt-7 flex justify-end">
            <Button type="submit" disabled={saving || (!creating && !selected)}>
              <Save size={17} />
              {saving ? t('正在保存…') : creating ? t('创建用户') : t('保存更改')}
            </Button>
          </div>
        </form>
      </div>

      {passwordTarget ? (
        <div className="fixed inset-0 z-[120] flex items-end justify-center bg-[#241F1C]/40 p-0 backdrop-blur-sm sm:items-center sm:p-6" role="dialog" aria-modal="true" aria-labelledby="reset-user-password-title">
          <form onSubmit={resetPassword} className="w-full max-w-md rounded-t-3xl bg-white p-6 shadow-2xl sm:rounded-3xl">
            <h2 id="reset-user-password-title" className="text-xl font-semibold text-[#292623]">{t('重置用户密码')}</h2>
            <p className="mt-2 text-sm leading-6 text-[#77716A]">{t('保存后会立即撤销该用户在所有设备上的会话。')}</p>
            <label className="mt-5 block text-sm font-medium text-[#3E3935]">
              {t('新密码')}
              <input autoFocus required minLength={10} maxLength={128} type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-[#DCD7D1] px-3 outline-none focus:border-[#E9775C] focus:ring-2 focus:ring-[#FAD9D0]" />
            </label>
            <div className="mt-6 flex justify-end gap-2">
              <Button type="button" variant="secondary" onClick={() => setPasswordTarget(null)}>{t('取消')}</Button>
              <Button type="submit">{t('重置并撤销会话')}</Button>
            </div>
          </form>
        </div>
      ) : null}

      {deleteTarget ? (
        <div className="fixed inset-0 z-[120] flex items-end justify-center bg-[#241F1C]/40 p-0 backdrop-blur-sm sm:items-center sm:p-6" role="dialog" aria-modal="true" aria-labelledby="delete-user-title">
          <form onSubmit={permanentlyDelete} className="w-full max-w-md rounded-t-3xl bg-white p-6 shadow-2xl sm:rounded-3xl">
            <h2 id="delete-user-title" className="text-xl font-semibold text-red-700">{t('永久删除用户')}</h2>
            <p className="mt-2 text-sm leading-6 text-[#77716A]">{t('此操作会删除该用户的进度、偏好、书签、书架、授权和会话，且无法恢复。')}</p>
            <label className="mt-5 block text-sm font-medium text-[#3E3935]">
              {t('输入用户邮箱 {value0} 以确认', { value0: deleteTarget.email })}
              <input autoFocus required value={deleteConfirmation} onChange={(event) => setDeleteConfirmation(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-red-200 px-3 outline-none focus:border-red-500 focus:ring-2 focus:ring-red-100" />
            </label>
            <div className="mt-6 flex justify-end gap-2">
              <Button type="button" variant="secondary" onClick={() => setDeleteTarget(null)}>{t('取消')}</Button>
              <Button type="submit" disabled={deleteConfirmation.trim().toLowerCase() !== deleteTarget.email.toLowerCase()}>
                <Trash2 size={16} />
                {t('永久删除')}
              </Button>
            </div>
          </form>
        </div>
      ) : null}
    </SettingsCenterShell>
  );
}
