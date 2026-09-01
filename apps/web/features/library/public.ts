export { UploadBookDialog } from './upload-book-dialog';
export {
  LibraryTagInput,
  type LibraryTagInputProps
} from './ui/library-tag-input';
export {
  SmartFilterBuilder,
  type SmartFilterCondition,
  type SmartFilterField,
  type SmartFilterRules
} from './smart-filter-builder';
export {
  fetchLibraryFilterOptions,
  fetchLibraryFilterSchema
} from './api/filtering';
export type {
  LibraryFilterOptionPage,
  LibraryFilterOptionSource,
  LibraryFilterSchema,
  SmartFilterOption
} from './model/filter-schema';
export {
  applicableSmartFilterRules,
  parseSmartFilterRules,
  serializableSmartFilterRules,
  smartFilterConditionComplete
} from './model/smart-filter-rules';
export type {
  BookshelfBookSummary,
  LibraryBookSummary,
  ManagementBookSummary
} from './api/books';
export { fetchLibraryNavigationSources } from './api/library-sources';
export {
  updateBulkBookCovers,
  type BulkBookCoverResult
} from './api/bulk-operations';
export {
  librarySourceHref,
  type LibraryNavigationSource
} from './model/library-source-navigation';
