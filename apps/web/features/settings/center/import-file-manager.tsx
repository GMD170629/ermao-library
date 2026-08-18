'use client';

import { ChevronRight, Folder, FolderOpen, RefreshCw, Search, Square } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Button } from '../../../components/ui/button';
import { cn } from '../../../components/ui/cn';
import { useToast } from '../../../components/ui/feedback';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';
import { useI18n as useExpressionI18n } from '@/i18n/provider';

type Library = {
  id: string;
  name: string;
  rootPath: string;
  enabled: boolean;
};

type DirectoryNode = {
  name: string;
  path: string;
  readable: boolean;
  error?: string | null;
  children: Array<{ name: string; path: string; readable: boolean }>;
};

type ScanJob = {
  id: string;
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED';
  directoriesScanned: number;
  filesScanned: number;
  candidatesFound: number;
  queuedCount: number;
  skippedCount: number;
  errorCount: number;
  errorSamples: Array<{
    path: string;
    error: string;
    code?: string | null;
    limit?: number | null;
    observedCount?: number | null;
  }>;
  restartCount: number;
};

function normalizePath(value: string) {
  return value.replace(/\/+$/, '') || value;
}

function isInside(rootPath: string, targetPath: string) {
  const root = normalizePath(rootPath);
  const target = normalizePath(targetPath);
  return target === root || target.startsWith(`${root}/`);
}

export function ImportFileManager() {
  const { t: i18nAttribute } = useAttributeI18n();
  const [folders, setFolders] = useState<Library[]>([]);
  const [rootPath, setRootPath] = useState('');
  const [nodes, setNodes] = useState<Record<string, DirectoryNode>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selectedPath, setSelectedPath] = useState('');
  const [loadingPath, setLoadingPath] = useState('');
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<ScanJob | null>(null);
  const terminalNotifications = useRef(new Set<string>());
  const toast = useToast();
  const activeScanId = result?.id;
  const activeScanStatus = result?.status;

  const loadNode = useCallback(async (path?: string) => {
    const key = path || '__root__';
    setLoadingPath(key);
    setError('');
    try {
      const response = await fetch(`/api/libraries/tree${path ? `?path=${encodeURIComponent(path)}` : ''}`);
      const payload = await response.json() as { ok: boolean; data?: { node: DirectoryNode }; error?: { message: string } };
      if (!response.ok || !payload.ok || !payload.data?.node) throw new Error(payload.error?.message ?? '读取目录失败');
      const node = payload.data.node;
      setRootPath(node.path);
      setNodes((current) => ({ ...current, [node.path]: node }));
      return node;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '读取目录失败');
      return null;
    } finally {
      setLoadingPath('');
    }
  }, []);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const response = await fetch('/api/libraries');
        const payload = await response.json() as { ok: boolean; data?: { libraries: Library[] }; error?: { message: string } };
        if (!active) return;
        if (!response.ok || !payload.ok) throw new Error(payload.error?.message ?? '读取书库失败');
        setFolders(payload.data?.libraries ?? []);
        const root = await loadNode();
        if (active && root) {
          setSelectedPath(root.path);
          setExpanded(new Set([root.path]));
        }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : '读取目录失败');
      }
    }
    void load();
    return () => { active = false; };
  }, [loadNode]);

  useEffect(() => {
    if (!activeScanId || !activeScanStatus || !['PENDING', 'RUNNING'].includes(activeScanStatus)) return;
    const controller = new AbortController();
    const timer = window.setInterval(() => {
      void (async () => {
        try {
          const response = await fetch(`/api/import-scan-jobs/${encodeURIComponent(activeScanId)}`, {
            signal: controller.signal
          });
          const payload = await response.json() as { ok: boolean; data?: { job: ScanJob }; error?: { message: string } };
          if (!response.ok || !payload.ok || !payload.data?.job) throw new Error(payload.error?.message ?? i18nAttribute('读取扫描进度失败'));
          setResult(payload.data.job);
        } catch (reason) {
          if (controller.signal.aborted) return;
          setError(reason instanceof Error ? reason.message : i18nAttribute('读取扫描进度失败'));
        }
      })();
    }, 1000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [activeScanId, activeScanStatus, i18nAttribute]);

  useEffect(() => {
    if (!result || ['PENDING', 'RUNNING'].includes(result.status)) return;
    setScanning(false);
    if (terminalNotifications.current.has(result.id)) return;
    terminalNotifications.current.add(result.id);
    if (result.status === 'COMPLETED') {
      toast.success(i18nAttribute('目录扫描完成'), i18nAttribute('新增 {value0} 条导入任务，跳过 {value1} 项', { value0: result.queuedCount, value1: result.skippedCount }));
    } else if (result.status === 'FAILED') {
      toast.error(i18nAttribute('识别目录失败'), i18nAttribute('扫描任务执行失败，请查看错误样本'));
    }
  }, [i18nAttribute, result, toast]);

  const selectedLibrary = useMemo(() => folders
    .filter((folder) => folder.enabled && selectedPath && isInside(folder.rootPath, selectedPath))
    .sort((left, right) => right.rootPath.length - left.rootPath.length)[0] ?? null, [folders, selectedPath]);

  async function toggle(path: string) {
    const next = new Set(expanded);
    if (next.has(path)) {
      next.delete(path);
      setExpanded(next);
      return;
    }
    next.add(path);
    setExpanded(next);
    if (!nodes[path]) await loadNode(path);
  }

  async function scanSelectedDirectory() {
    if (!selectedPath || !selectedLibrary) return;
    let submitted = false;
    setScanning(true);
    setError('');
    setResult(null);
    try {
      const response = await fetch('/api/import-tasks/scan-directory', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: selectedPath })
      });
      const payload = await response.json() as { ok: boolean; data?: { job: ScanJob; created: boolean }; error?: { message: string } };
      if (!response.ok || !payload.ok || !payload.data?.job) throw new Error(payload.error?.message ?? '识别目录失败');
      setResult(payload.data.job);
      submitted = true;
      toast.success(i18nAttribute(payload.data.created ? '扫描任务已提交' : '扫描任务已在队列中'));
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : '识别目录失败';
      setError(message);
      toast.error('识别目录失败', message);
    } finally {
      if (!submitted) {
        setScanning(false);
      }
    }
  }

  async function cancelScan() {
    if (!result || !['PENDING', 'RUNNING'].includes(result.status)) return;
    try {
      const response = await fetch(`/api/import-scan-jobs/${encodeURIComponent(result.id)}/cancel`, {
        method: 'POST'
      });
      const payload = await response.json() as { ok: boolean; data?: { job: ScanJob }; error?: { message: string } };
      if (!response.ok || !payload.ok || !payload.data?.job) throw new Error(payload.error?.message ?? i18nAttribute('取消扫描失败'));
      setResult(payload.data.job);
      setScanning(false);
      toast.success(i18nAttribute('扫描任务已取消'));
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : i18nAttribute('取消扫描失败');
      setError(message);
      toast.error(i18nAttribute('取消扫描失败'), message);
    }
  }

  const rootNode = rootPath ? nodes[rootPath] : Object.values(nodes)[0];

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-4 rounded-[20px] border border-[#DEDAD4] bg-[#FAF9F7] p-4 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="font-semibold text-[#2A2825]"><I18nText>从目录识别图书</I18nText></div>
          <p className="mt-1 text-sm leading-6 text-[#77716A]"><I18nText>选择已启用书库内的目录。识别仍会应用格式、隐藏文件、大小、忽略规则和已导入检查。</I18nText></p>
        </div>
        <Button variant="secondary" icon={RefreshCw} loading={loadingPath === (selectedPath || '__root__')} loadingText={i18nAttribute("刷新中")} onClick={() => void loadNode(selectedPath || undefined)}><I18nText>刷新目录</I18nText></Button>
      </div>
      <div className="rounded-[16px] border border-[#F0DED5] bg-[#FFF8F4] px-4 py-3 text-sm leading-6 text-[#6D625B]">
        <div className="font-semibold text-[#3D3732]"><I18nText>有声书推荐目录</I18nText></div>
        <p className="mt-1"><I18nText>单卷使用“书名/音轨”，多卷使用“书名/卷名/音轨”；Disc、CD、Disk 目录只作为分轨层。目录名内嵌的作者可以识别，独立的“作者/书名”层级不会作为作者信息。</I18nText></p>
      </div>

      <div className="grid min-h-[420px] overflow-hidden rounded-[20px] border border-[#DEDAD4] bg-white md:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 border-b border-[#DEDAD4] p-3 md:border-b-0 md:border-r">
          <div className="mb-2 px-2 text-xs font-medium text-[#8A847D]"><I18nText>文件夹视图</I18nText></div>
          <div className="max-h-[520px] overflow-auto">
            {rootNode ? <DirectoryRow node={rootNode} level={0} nodes={nodes} expanded={expanded} selectedPath={selectedPath} loadingPath={loadingPath} onToggle={toggle} onSelect={setSelectedPath} /> : <div className="p-5 text-sm text-[#77716A]">{loadingPath ? i18nAttribute("正在读取目录…") : i18nAttribute("暂无可浏览目录")}</div>}
          </div>
        </div>
        <aside className="flex flex-col p-5">
          <div className="text-xs font-medium text-[#8A847D]"><I18nText>当前选择</I18nText></div>
          <div className="mt-2 break-all text-sm font-semibold leading-6 text-[#2A2825]">{selectedPath || i18nAttribute("尚未选择目录")}</div>
          <div className={cn('mt-4 rounded-xl px-3 py-2 text-xs leading-5', selectedLibrary ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-800')}>
            {selectedLibrary ? i18nAttribute("使用“{value0}”的识别规则", { value0: selectedLibrary.name }) : i18nAttribute("此目录不在已启用的书库内，不能识别。")}
          </div>
          {result ? (
            <div className="mt-4 space-y-2 border-t border-[#E9E5DF] pt-4 text-sm text-[#5F5953]">
              <div><I18nText>扫描目录：</I18nText>{result.directoriesScanned}</div>
              <div><I18nText>检查文件：</I18nText>{result.filesScanned}</div>
              <div><I18nText>发现候选：</I18nText>{result.candidatesFound}</div>
              <div><I18nText>加入队列：</I18nText>{result.queuedCount}</div>
              <div><I18nText>按规则跳过：</I18nText>{result.skippedCount}</div>
              <div><I18nText>重启次数：</I18nText>{result.restartCount}</div>
              {result.errorCount > 0 ? <div className="text-red-600"><I18nText>读取失败：</I18nText>{result.errorCount}</div> : null}
              {result.errorSamples.slice(0, 5).map((sample) => (
                <div key={`${sample.code ?? 'scan'}:${sample.path}`} className="rounded-lg bg-red-50 px-3 py-2 text-xs leading-5 text-red-700">
                  <div className="break-all font-medium">{sample.path}</div>
                  <div>
                    {sample.code === 'AUDIO_TRACK_LIMIT_EXCEEDED'
                      ? i18nAttribute('有声书音轨超过 {value0} 条（检测到 {value1} 条），请按卷或子目录拆分后重新识别。', {
                        value0: sample.limit ?? 10_000,
                        value1: sample.observedCount ?? 10_001
                      })
                      : sample.error}
                  </div>
                </div>
              ))}
            </div>
          ) : null}
          {error ? <div className="mt-4 rounded-xl bg-red-50 px-3 py-2 text-xs leading-5 text-red-700">{error}</div> : null}
          <div className="mt-auto space-y-2">
            {result && ['PENDING', 'RUNNING'].includes(result.status) ? <Button className="w-full" variant="secondary" icon={Square} onClick={() => void cancelScan()} aria-label={i18nAttribute("取消扫描任务")}><I18nText>取消扫描</I18nText></Button> : null}
            <Button className="w-full" icon={Search} disabled={!selectedLibrary || !selectedPath} loading={scanning} loadingText={i18nAttribute("识别中")} onClick={() => void scanSelectedDirectory()}><I18nText>识别此目录</I18nText></Button>
          </div>
        </aside>
      </div>
    </div>
  );
}

function DirectoryRow({ node, level, nodes, expanded, selectedPath, loadingPath, onToggle, onSelect }: {
  node: DirectoryNode;
  level: number;
  nodes: Record<string, DirectoryNode>;
  expanded: Set<string>;
  selectedPath: string;
  loadingPath: string;
  onToggle: (path: string) => Promise<void>;
  onSelect: (path: string) => void;
}) {
  const { t: i18nExpression } = useExpressionI18n();
  const isExpanded = expanded.has(node.path);
  const children = nodes[node.path]?.children ?? node.children;
  return (
    <div>
      <div className={cn('group flex min-h-10 items-center rounded-xl pr-2 text-sm', selectedPath === node.path ? 'bg-[#FCE5DE] text-[#C84226]' : 'text-[#4F4A45] hover:bg-[#F7F4F0]')} style={{ paddingLeft: `${Math.min(level, 8) * 16 + 6}px` }}>
        <button type="button" onClick={() => void onToggle(node.path)} className="flex h-8 w-8 shrink-0 items-center justify-center" aria-label={isExpanded ? i18nExpression("收起 {value0}", { value0: node.name }) : i18nExpression("展开 {value0}", { value0: node.name })}>
          <ChevronRight size={15} className={cn('transition-transform', isExpanded && 'rotate-90')} />
        </button>
        <button type="button" onClick={() => onSelect(node.path)} disabled={!node.readable} className="flex min-w-0 flex-1 items-center gap-2 py-2 text-left disabled:opacity-45">
          {isExpanded ? <FolderOpen size={17} className="shrink-0" /> : <Folder size={17} className="shrink-0" />}
          <span className="truncate">{node.name}</span>
          {loadingPath === node.path ? <span className="text-xs text-[#8A847D]"><I18nText>读取中</I18nText></span> : null}
        </button>
      </div>
      {isExpanded ? children.map((child) => (
        <DirectoryRow
          key={child.path}
          node={nodes[child.path] ?? { ...child, children: [] }}
          level={level + 1}
          nodes={nodes}
          expanded={expanded}
          selectedPath={selectedPath}
          loadingPath={loadingPath}
          onToggle={onToggle}
          onSelect={onSelect}
        />
      )) : null}
    </div>
  );
}
