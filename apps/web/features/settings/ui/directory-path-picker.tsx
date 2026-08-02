'use client';

import { ChevronDown, ChevronRight, FolderOpen, RotateCcw } from 'lucide-react';
import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { cn } from '../../../components/ui/cn';
import { I18nText, useI18n } from '@/i18n/provider';
import { loadMonitorDirectory } from '../api/monitor-folders-client';
import type { DirectoryNode } from '../api/monitor-folders-client';
import { directoryPathChain } from '../model/directory-path';

type DirectoryPathPickerVariant = 'default' | 'setup';

export function DirectoryPathPicker({
  value,
  onChange,
  compact = false,
  disabled = false,
  variant = 'default'
}: {
  value: string;
  onChange: (value: string) => void;
  compact?: boolean;
  disabled?: boolean;
  variant?: DirectoryPathPickerVariant;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [rootPath, setRootPath] = useState('');
  const [nodes, setNodes] = useState<Record<string, DirectoryNode>>({});
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [loadingPath, setLoadingPath] = useState('');
  const [treeError, setTreeError] = useState('');
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const treeId = useId();

  const loadNode = useCallback(async (
    path?: string,
    signal?: AbortSignal
  ) => {
    setLoadingPath(path || '__root__');
    setTreeError('');
    try {
      const node = await loadMonitorDirectory(path, signal);
      if (!path) setRootPath(node.path);
      setNodes((current) => ({ ...current, [node.path]: node }));
      return node;
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === 'AbortError') return null;
      setTreeError(reason instanceof Error ? reason.message : '读取目录树失败');
      return null;
    } finally {
      if (!signal?.aborted) setLoadingPath('');
    }
  }, []);

  const revealPath = useCallback(async (path: string, signal?: AbortSignal) => {
    const pathChain = directoryPathChain(path);
    for (const pathPart of pathChain) {
      if (signal?.aborted) return;
      const node = await loadNode(pathPart === '/' ? undefined : pathPart, signal);
      if (!node) return;
      setExpanded((current) => ({ ...current, [node.path]: true }));
    }
  }, [loadNode]);

  useEffect(() => {
    const controller = new AbortController();
    void loadNode(undefined, controller.signal);
    return () => controller.abort();
  }, [loadNode]);

  useEffect(() => {
    if (!open) return;
    const typedPath = value.trim();
    if (typedPath && !typedPath.startsWith('/')) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void revealPath(typedPath || '/', controller.signal);
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [open, revealPath, value]);

  useEffect(() => {
    if (!open) return;
    const closeOnOutside = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setOpen(false);
      inputRef.current?.focus();
    };
    document.addEventListener('mousedown', closeOnOutside);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('mousedown', closeOnOutside);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [open]);

  async function toggleDirectory(path: string) {
    const nextExpanded = !expanded[path];
    setExpanded((current) => ({ ...current, [path]: nextExpanded }));
    if (nextExpanded && !nodes[path]) await loadNode(path);
  }

  function selectPath(path: string) {
    onChange(path);
    setOpen(false);
    window.requestAnimationFrame(() => inputRef.current?.focus());
  }

  function openTypedPath() {
    setOpen(true);
  }

  async function refreshTree() {
    const typedPath = value.trim();
    if (typedPath && !typedPath.startsWith('/')) {
      await loadNode();
      return;
    }
    await revealPath(typedPath || '/');
  }

  const rootNode = rootPath ? nodes[rootPath] : Object.values(nodes)[0];
  const setup = variant === 'setup';
  return (
    <div ref={rootRef} className={cn('relative', compact ? 'mt-1.5' : 'mt-2')}>
      <div className={cn(
        'flex w-full min-w-0 items-center overflow-hidden border outline-none transition focus-within:ring-4 disabled:cursor-not-allowed',
        setup
          ? 'rounded-2xl border-[#B08B6E]/55 bg-[#E8DCC7] text-[#606C38] focus-within:border-[#C66B3D] focus-within:ring-[#C66B3D]/15'
          : 'border-slate-200 bg-white text-slate-900 focus-within:border-[#F19B84] focus-within:ring-[#FCE5DE]',
        compact ? 'h-10 rounded-xl' : 'h-12 rounded-2xl',
        disabled && 'cursor-not-allowed opacity-60'
      )}>
        <FolderOpen size={17} className={cn('ml-4 shrink-0', setup ? 'text-[#8B9D83]' : 'text-slate-500')} />
        <input
          ref={inputRef}
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'ArrowDown') {
              event.preventDefault();
              setOpen(true);
            }
            if (event.key === 'Enter') {
              event.preventDefault();
              openTypedPath();
            }
          }}
          placeholder={t('请输入或选择文件夹')}
          aria-label={t('监控文件夹路径')}
          aria-controls={treeId}
          aria-expanded={open}
          aria-autocomplete="list"
          role="combobox"
          autoComplete="off"
          spellCheck={false}
          className={cn(
            'h-full min-w-0 flex-1 bg-transparent px-3 text-sm outline-none placeholder:opacity-60 disabled:cursor-not-allowed',
            setup ? 'placeholder:text-[#8B9D83]' : 'placeholder:text-slate-400'
          )}
        />
        <button
          type="button"
          disabled={disabled}
          onClick={() => open ? setOpen(false) : openTypedPath()}
          className={cn(
            'flex h-full w-12 shrink-0 items-center justify-center border-l transition disabled:cursor-not-allowed',
            setup
              ? 'border-[#B08B6E]/35 text-[#606C38]/70 hover:bg-[#DCC7A7]/55'
              : 'border-slate-200 text-slate-400 hover:bg-slate-50'
          )}
          aria-label={open ? t('收起文件夹路径树') : t('展开文件夹路径树')}
          aria-expanded={open}
          aria-controls={treeId}
        >
          <ChevronDown size={17} className={cn('transition', open && 'rotate-180')} />
        </button>
      </div>

      {open ? (
        <div className={cn(
          'left-0 right-0 z-50 mt-2 border p-3 text-sm shadow-xl',
          setup
            ? 'relative rounded-2xl border-[#B08B6E]/45 bg-[#E8DCC7] text-[#606C38] shadow-[#606C38]/15'
            : 'absolute top-full rounded-2xl border-slate-200 bg-white text-slate-700 shadow-slate-200/60'
        )}>
          <div className="mb-2 flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className={cn('font-semibold', setup ? 'text-[#606C38]' : 'text-slate-950')}><I18nText>可访问目录</I18nText></div>
              <div className={cn('truncate text-xs', setup ? 'text-[#606C38]/65' : 'text-slate-500')}>{rootPath || t('读取中')}</div>
            </div>
            <button
              type="button"
              onClick={() => void refreshTree()}
              className={cn(
                'inline-flex h-9 items-center gap-2 rounded-xl border px-3 text-xs font-medium transition',
                setup
                  ? 'border-[#B08B6E]/45 bg-[#F2E8D5]/60 text-[#606C38] hover:bg-[#F2E8D5]'
                  : 'border-slate-200 text-slate-600 hover:bg-slate-50'
              )}
            >
              <RotateCcw size={14} />
              <I18nText>刷新</I18nText>
            </button>
          </div>
          <div
            id={treeId}
            role="tree"
            aria-label={t('文件夹路径树')}
            className={cn(
              'overflow-auto rounded-xl p-2',
              setup ? 'shuku-setup-scrollbar max-h-64' : 'max-h-64',
              setup ? 'bg-[#DCC7A7]/45' : 'bg-slate-50'
            )}
          >
            {rootNode ? (
              <DirectoryNodeRow
                node={rootNode}
                level={0}
                selectedPath={value}
                nodes={nodes}
                expanded={expanded}
                loadingPath={loadingPath}
                variant={variant}
                onSelect={selectPath}
                onToggle={toggleDirectory}
              />
            ) : (
              <div className={cn('px-3 py-2', setup ? 'text-[#606C38]/65' : 'text-slate-500')}>
                {loadingPath ? t('正在读取目录...') : t('暂无可选目录')}
              </div>
            )}
          </div>
          {treeError ? <div className="mt-2 rounded-xl bg-red-50 px-3 py-2 text-xs text-red-700">{treeError}</div> : null}
          <div className={cn('mt-2 text-xs leading-5', setup ? 'text-[#606C38]/65' : 'text-slate-500')}>
            <I18nText>可以输入、粘贴或从目录树选择；保存时会验证路径。</I18nText>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function DirectoryNodeRow({
  node,
  level,
  selectedPath,
  nodes,
  expanded,
  loadingPath,
  variant,
  onSelect,
  onToggle
}: {
  node: DirectoryNode;
  level: number;
  selectedPath: string;
  nodes: Record<string, DirectoryNode>;
  expanded: Record<string, boolean>;
  loadingPath: string;
  variant: DirectoryPathPickerVariant;
  onSelect: (path: string) => void;
  onToggle: (path: string) => void;
}) {
  const { t } = useI18n();
  const isExpanded = Boolean(expanded[node.path]);
  const isSelected = selectedPath === node.path;
  const setup = variant === 'setup';

  return (
    <div role="treeitem" aria-expanded={isExpanded} aria-selected={isSelected} aria-disabled={!node.readable}>
      <div
        className={cn(
          'flex items-center gap-1 rounded-xl px-2 py-1.5 transition',
          setup
            ? isSelected ? 'bg-[#C66B3D]/15 text-[#9E4D29]' : 'text-[#606C38] hover:bg-[#F2E8D5]/70'
            : isSelected ? 'bg-[#fff0ea] text-[#d94724]' : 'text-slate-700 hover:bg-white',
          !node.readable && 'opacity-50'
        )}
        style={{ paddingLeft: `${8 + level * 18}px` }}
      >
        <button
          type="button"
          onClick={() => void onToggle(node.path)}
          className={cn(
            'flex h-7 w-7 shrink-0 items-center justify-center rounded-lg transition',
            setup ? 'text-[#606C38]/70 hover:bg-[#F2E8D5]' : 'text-slate-500 hover:bg-slate-100'
          )}
          aria-label={isExpanded ? t('收起目录') : t('展开目录')}
        >
          <ChevronRight size={15} className={cn('transition', isExpanded && 'rotate-90')} />
        </button>
        <button
          type="button"
          disabled={!node.readable}
          onClick={() => onSelect(node.path)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left disabled:cursor-not-allowed"
        >
          <FolderOpen size={15} className="shrink-0" />
          <span className="truncate">{node.name || node.path}</span>
        </button>
        {!node.readable ? <span className="text-xs opacity-60"><I18nText>不可读取</I18nText></span> : null}
        {loadingPath === node.path ? <span className="text-xs opacity-60"><I18nText>读取中</I18nText></span> : null}
      </div>
      {isExpanded ? (
        <div role="group">
          {node.children.length > 0 ? node.children.map((child) => (
            <DirectoryNodeRow
              key={child.path}
              node={nodes[child.path] ?? { ...child, children: [] }}
              level={level + 1}
              selectedPath={selectedPath}
              nodes={nodes}
              expanded={expanded}
              loadingPath={loadingPath}
              variant={variant}
              onSelect={onSelect}
              onToggle={onToggle}
            />
          )) : (
            <div className="px-3 py-1.5 text-xs opacity-60" style={{ paddingLeft: `${42 + level * 18}px` }}><I18nText>没有子目录</I18nText></div>
          )}
        </div>
      ) : null}
    </div>
  );
}
