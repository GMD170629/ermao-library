export type SmartShelfCondition = {
  field: string;
  operator: string;
  value?: string | string[];
};

export type SmartShelfRules = {
  search?: string;
  statuses?: string[];
  mediaKinds?: string[];
  tags?: string[];
  authors?: string[];
  publishers?: string[];
  combinator?: 'ALL' | 'ANY';
  conditions?: SmartShelfCondition[];
};

export type SmartShelfRuleSummary = {
  label: string;
  value: string;
};

const fieldLabels: Record<string, string> = {
  title: '书名', author: '作者', tag: '标签', series: '丛书', description: '简介',
  publishedYear: '出版年份', seriesIndex: '丛书序号', metadataQuality: '元数据完整度',
  publisher: '出版社', language: '语言', isbn: 'ISBN', identifier: '外部标识',
  volumeTitle: '卷册名称', narrator: '演播者', mediaKind: '读物类型', format: '文件格式',
  fileSize: '文件总大小', pageCount: '页数', chapterCount: '章节数', duration: '时长',
  volumeCount: '卷册数量', sourcePath: '原始文件路径', readingStatus: '阅读状态',
  progress: '阅读进度', lastReadAt: '最近阅读时间', publicationStatus: '连载状态',
  trackingStatus: '追踪状态', organizeStatus: '整理状态', organized: '已完成整理',
  hasCover: '有封面', shelf: '所在普通书架', monitorFolder: '监控文件夹', origin: '加入来源',
  importStatus: '导入状态', createdAt: '加入时间', updatedAt: '最后更新时间'
};

const operatorLabels: Record<string, string> = {
  contains: '包含', not_contains: '不包含', equals: '等于', not_equals: '不等于',
  starts_with: '开头是', ends_with: '结尾是', greater_than: '大于',
  greater_or_equal: '大于等于', less_than: '小于', less_or_equal: '小于等于',
  after: '晚于', on_or_after: '不早于', before: '早于', on_or_before: '不晚于',
  between: '介于', is_empty: '为空', is_not_empty: '不为空', is_true: '是', is_false: '否'
};

const valueLabels: Record<string, string> = {
  UNREAD: '未开始', WANT: '未开始', READING: '进行中', FINISHED: '已完成',
  EBOOK: '电子书', COMIC: '漫画', AUDIOBOOK: '有声书',
  UNKNOWN: '未知', ONGOING: '连载中', COMPLETED: '已完结', HIATUS: '暂停', CANCELLED: '已取消',
  NOT_TRACKING: '未追踪', TRACKING: '追踪中', PAUSED: '已暂停', IGNORED: '已忽略',
  PENDING: '待整理', REVIEWING: '待确认', APPLIED: '已应用', FAILED: '失败'
};

function displayValue(value: string | string[] | undefined) {
  if (value === undefined) return '';
  const values = Array.isArray(value) ? value : [value];
  return values.map((item) => valueLabels[item] ?? item).join(' 至 ');
}

export function summarizeSmartShelfRules(rules?: SmartShelfRules): SmartShelfRuleSummary[] {
  if (!rules) return [];
  const summaries: SmartShelfRuleSummary[] = [];
  if (rules.search?.trim()) summaries.push({ label: '搜索', value: `包含“${rules.search.trim()}”` });
  if (rules.statuses?.length) summaries.push({ label: '阅读状态', value: rules.statuses.map((item) => valueLabels[item] ?? item).join('、') });
  if (rules.mediaKinds?.length) summaries.push({ label: '读物类型', value: rules.mediaKinds.map((item) => valueLabels[item] ?? item).join('、') });
  if (rules.tags?.length) summaries.push({ label: '标签', value: rules.tags.join('、') });
  if (rules.authors?.length) summaries.push({ label: '作者', value: rules.authors.join('、') });
  if (rules.publishers?.length) summaries.push({ label: '出版社', value: rules.publishers.join('、') });
  for (const condition of rules.conditions ?? []) {
    const operator = operatorLabels[condition.operator] ?? condition.operator;
    const value = displayValue(condition.value);
    summaries.push({
      label: fieldLabels[condition.field] ?? condition.field,
      value: value ? `${operator} ${value}` : operator
    });
  }
  return summaries;
}
