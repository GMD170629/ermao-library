import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const catalogPath = resolve(scriptDirectory, '../i18n/messages/en-US.json');
const sourceCatalogPath = resolve(scriptDirectory, '../i18n/messages/zh-CN.json');
const catalog = JSON.parse(readFileSync(catalogPath, 'utf8'));
const sourceCatalog = JSON.parse(readFileSync(sourceCatalogPath, 'utf8'));

const exactOverrides = {
  '二毛图书': 'Ermao Books',
  '二毛': 'Ermao',
  '自托管私人图书馆与沉浸阅读应用': 'A self-hosted private library and immersive reading app',
  '和二毛一起，安静读书': 'Read quietly with Ermao',
  '首页': 'Home',
  '主页': 'Home',
  '通用': 'General',
  '书库来源与导入': 'Library Sources & Import',
  '智能整理': 'Smart Organization',
  '邮件与 Kindle': 'Email & Kindle',
  '数据与系统': 'Data & System',
  '系统日志': 'System Logs',
  '书架': 'Shelves',
  '读物': 'Book',
  '有声书': 'Audiobook',
  '在读': 'Reading',
  '在看': 'Reading',
  '在听': 'Listening',
  '确认': 'Confirm',
  '上传读物': 'Upload Books',
  '打开书架': 'Open Library',
  '直接打开全部图书': 'Open all books',
  '打开图书上传入口': 'Open the book upload page',
  '回到首页继续上次的阅读、看漫画或听书': 'Return home to continue reading, viewing comics, or listening',
  '未登录': 'Not signed in',
  '界面语言': 'Interface Language',
  '界面语言已更新': 'Interface language updated',
  '保存语言设置失败': 'Failed to save the language setting',
  '选择界面语言': 'Select interface language',
  '选择整个应用使用的语言。设置会同步到登录页、阅读器和 PWA。': 'Choose the language used throughout the app. It also applies to sign-in, the reader, and the PWA.',
  '正在切换语言…': 'Switching language…',
  '请稍后重试': 'Please try again later',
  '不包含': 'Does not contain',
  '创建下载任务：': 'Created download task: ',
  '创建下载任务：{value0}': 'Created download task: {value0}',
  '等待发送时确定': 'Determined when queued for sending',
  '更新下载任务：': 'Updated download task: ',
  '更新下载任务：{value0}': 'Updated download task: {value0}',
  '监控文件夹不可读：': 'Watch folder is unreadable: ',
  '开始扫描监控文件夹：': 'Started scanning watch folder: ',
  '取消下载任务：': 'Cancelled download task: ',
  '删除监控文件夹': 'Delete watch folder',
  '删除下载任务：': 'Deleted download task: ',
  '删除下载任务：{value0}': 'Deleted download task: {value0}',
  '尚未创建备份。': 'No backups have been created yet.',
  '识别任务执行间隔': 'Recognition task interval',
  '暂无导入任务。': 'No import tasks yet.',
  '整理任务不存在': 'Organization task not found',
  '执行下载任务：': 'Executed download task: ',
  '执行下载任务：{value0}': 'Executed download task: {value0}',
  '执行者：': 'Actor: ',
  '重新排队导入任务：': 'Requeued import task: ',
  '重新排队下载任务：': 'Requeued download task: ',
  '全部': 'All',
  '进行中': 'In Progress',
  '已完成': 'Completed',
  '未读': 'Unread',
  '暂停': 'Paused',
  '失败': 'Failed',
  '成功': 'Succeeded',
  '处理中': 'Processing',
  '保存中': 'Saving',
  '加载中': 'Loading',
  '重试': 'Retry',
  '查看详情': 'View Details',
  '查看全部': 'View All',
  '管理图书': 'Manage Books',
  '返回书架': 'Back to Shelves',
  '正在加载更多图书...': 'Loading more books...',
  '已加载 {value0} / {value1} 本': 'Loaded {value0} of {value1} books',
  '返回': 'Back',
  '关闭': 'Close',
  '下一页': 'Next Page',
  '上一页': 'Previous Page',
  '下一章': 'Next Chapter',
  '上一章': 'Previous Chapter',
  '目录': 'Table of Contents',
  '书签': 'Bookmarks',
  '添加书签': 'Add Bookmark',
  '删除书签': 'Delete Bookmark',
  '阅读进度': 'Reading Progress',
  '字体': 'Font',
  '字号': 'Font Size',
  '主题': 'Theme',
  '白天': 'Light',
  '夜间': 'Dark',
  '纯黑': 'Black',
  '漫画': 'Comic',
  '电子书': 'Ebook',
  '音频': 'Audio',
  '播放': 'Play',
  '暂停播放': 'Pause',
  '播放速度': 'Playback Speed',
  '章节列表': 'Chapters',
  '设置分类': 'Settings Categories',
  '打开导航菜单': 'Open navigation menu',
  '主导航': 'Main navigation',
  '主要页面': 'Main pages',
  '账户与设置': 'Account & Settings',
  '语言': 'Language',
  '保存设置': 'Save Settings',
  '保存更改': 'Save Changes',
  '取消': 'Cancel',
  '删除': 'Delete',
  '保存': 'Save',
  '创建': 'Create',
  '编辑': 'Edit',
  '搜索': 'Search',
  '筛选': 'Filter',
  '排序': 'Sort',
  '上传': 'Upload',
  '下载': 'Download',
  '重命名': 'Rename',
  '移除': 'Remove',
  '添加': 'Add',
  '刷新': 'Refresh',
  '继续': 'Continue',
  '完成': 'Done',
  '确定': 'OK',
  '操作失败': 'Operation failed',
  '保存失败': 'Save failed',
  '读取失败': 'Failed to load',
  '网络错误': 'Network error',
  '暂无数据': 'No data yet',
  '暂无图书': 'No books yet',
  '未知作者': 'Unknown Author',
  '选填': 'Optional',
  '选择': 'Select',
  '朗读者': 'Narrator',
  '整理队列': 'Organization Queue',
  '整理摘要': 'Organization Summary',
  '元数据已应用，整理完成': 'Metadata applied; organization complete',
  '选择的图书文件不存在': 'The selected book file does not exist',
  '取消下载任务：{value0}': 'Cancelled download task: {value0}',
  '重新排队导入任务：{value0}': 'Requeued import task: {value0}',
  '删除监控文件夹“{value0}”？不会删除原始读物文件。': 'Delete watch folder “{value0}”? The original book files will not be deleted.',
  '《{value0}》已由二毛图书发送至 Kindle。': '“{value0}” has been sent to Kindle by Ermao Books.',
  '{value0}{value1} · 第 {value2} 页': '{value0}{value1} · Page {value2}',
  '{value0} · 第 {value1} 部': '{value0} · Part {value1}',
  '查看“{value0}”的全部结果': 'View all results for “{value0}”',
  '管理账户 {value0} 已创建并登录。': 'Administrator account {value0} has been created and signed in.',
  '欢迎回到{value0}': 'Welcome back to {value0}',
  '将“{value0}”及关联的阅读进度移到新作品，文件不会复制或删除。': 'Move “{value0}” and its reading progress to a new work. Files will not be copied or deleted.',
  '将「{value0}」及其内容按媒介和卷册结构转移到另一图书。': 'Move “{value0}” and its contents to another book while preserving the media and volume structure.',
  '删除《{value0}》的书库记录和系统生成文件。你可以选择是否同时删除监控或上传目录中的源文件。': 'Delete “{value0}” from the library along with system-generated files. You can also delete the source file from its watch or upload folder.',
  '删除《{value0}》的书库记录和系统生成文件。你可以选择是否同时删除源文件。': 'Delete “{value0}” from the library along with system-generated files. You can also delete the source file.',
  '搜索候选，选择字段后应用到《{value0}》。': 'Search for metadata candidates, then choose which fields to apply to “{value0}”.',
  '选择《{value0}》的一个 EPUB 或 PDF 文件加入后台队列。': 'Choose an EPUB or PDF file for “{value0}” and add it to the background queue.',
  '此链接在创建后 30 分钟内有效，并且只能使用一次。': 'This link is valid for 30 minutes after creation and can only be used once.',
  '打开二毛图书并设置新密码': 'Open Ermao Books and set a new password',
  '重置二毛图书密码': 'Reset your Ermao Books password'
};

for (const source of Object.keys(catalog)) {
  if (!(source in sourceCatalog)) delete catalog[source];
}

const missingTranslations = Object.keys(sourceCatalog).filter((source) => !(source in catalog) && !(source in exactOverrides));
if (missingTranslations.length > 0) {
  process.stderr.write(`Missing English translations:\n${missingTranslations.join('\n')}\n`);
  process.exit(1);
}

for (const source of Object.keys(sourceCatalog)) {
  if (!(source in catalog)) catalog[source] = exactOverrides[source];
}

for (const [source, translation] of Object.entries(exactOverrides)) {
  if (source in sourceCatalog) catalog[source] = translation;
}

for (const [source, originalTranslation] of Object.entries(catalog)) {
  let translation = originalTranslation;
  if (source.includes('书架')) {
    translation = translation
      .replace(/\bbookcases\b/gi, 'shelves')
      .replace(/\bbookcase\b/gi, 'shelf');
  }
  if (source.includes('有声书')) {
    translation = translation
      .replace(/\bvoice books?\b/gi, 'audiobooks')
      .replace(/\baudio books?\b/gi, 'audiobooks');
  }
  if (source.includes('智能整理') || source.includes('整理任务') || source.includes('整理队列')) {
    translation = translation
      .replace(/\bsmart packing\b/gi, 'smart organization')
      .replace(/\bpacking tasks?\b/gi, 'organization tasks')
      .replace(/\bpacking queues?\b/gi, 'organization queues');
  }
  if (source.includes('读物')) {
    translation = translation
      .replace(/\breaders\b/gi, 'books')
      .replace(/\breader\b/gi, 'book');
  }
  catalog[source] = translation;
}

const sortedCatalog = Object.fromEntries(Object.keys(sourceCatalog).map((source) => [source, catalog[source]]));
writeFileSync(catalogPath, `${JSON.stringify(sortedCatalog, null, 2)}\n`);
process.stdout.write(`Applied ${Object.keys(exactOverrides).length} curated i18n overrides\n`);
