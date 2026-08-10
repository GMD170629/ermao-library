export type LibraryFilterOptionSource = 'authors' | 'tags' | 'series';

export type SmartFilterOption = {
  value: string;
  label: string;
  count?: number;
  rootPath?: string;
  translate?: boolean;
};

export type SmartFilterField = {
  key: string;
  label: string;
  group: string;
  type: 'text' | 'select' | 'number' | 'date' | 'boolean';
  operators: string[];
  optionSource?: string;
  options?: SmartFilterOption[];
  allowCustom?: boolean;
  unit?: string;
  valueScale?: number;
};

export type LibraryFilterSchema = {
  fields: SmartFilterField[];
  maxConditions: number;
};

export type LibraryFilterOptionPage = {
  source: LibraryFilterOptionSource;
  query: string;
  options: Array<Required<Pick<SmartFilterOption, 'value' | 'label' | 'count'>>>;
  hasMore: boolean;
  indexReady: boolean;
};

export function isLibraryFilterOptionSource(value: string | undefined): value is LibraryFilterOptionSource {
  return value === 'authors' || value === 'tags' || value === 'series';
}
