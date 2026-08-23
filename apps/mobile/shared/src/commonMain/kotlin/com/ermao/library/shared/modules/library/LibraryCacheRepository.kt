package com.ermao.library.shared.modules.library

import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.library.domain.BookDetailSummary
import com.ermao.library.shared.modules.library.domain.BookSummary

data class CachedContent<T>(val value: T, val savedAtEpochMillis: Long)

/** Platform adapters persist these values in app-private storage using atomic replacement. */
interface LibraryCacheRepository {
    suspend fun home(namespace: PrivateDataNamespace): CachedContent<HomeSnapshot>?
    suspend fun saveHome(namespace: PrivateDataNamespace, value: HomeSnapshot, savedAtEpochMillis: Long)
    suspend fun books(namespace: PrivateDataNamespace, queryKey: String, page: Int): CachedContent<LibraryPage<BookSummary>>?
    suspend fun saveBooks(namespace: PrivateDataNamespace, queryKey: String, value: LibraryPage<BookSummary>, savedAtEpochMillis: Long)
    suspend fun groupings(namespace: PrivateDataNamespace, queryKey: String, page: Int): CachedContent<LibraryPage<GroupingSummary>>?
    suspend fun saveGroupings(namespace: PrivateDataNamespace, queryKey: String, value: LibraryPage<GroupingSummary>, savedAtEpochMillis: Long)
    suspend fun facet(namespace: PrivateDataNamespace, queryKey: String, page: Int): CachedContent<FacetPage>?
    suspend fun saveFacet(namespace: PrivateDataNamespace, queryKey: String, value: FacetPage, savedAtEpochMillis: Long)
    suspend fun detail(namespace: PrivateDataNamespace, bookId: String): CachedContent<BookDetailSummary>?
    suspend fun saveDetail(namespace: PrivateDataNamespace, value: BookDetailSummary, savedAtEpochMillis: Long)
    suspend fun clear(namespace: PrivateDataNamespace)
}

class InMemoryLibraryCacheRepository : LibraryCacheRepository {
    private val entries = mutableMapOf<String, CachedContent<*>>()

    override suspend fun home(namespace: PrivateDataNamespace) = value<HomeSnapshot>(namespace, "home")
    override suspend fun saveHome(namespace: PrivateDataNamespace, value: HomeSnapshot, savedAtEpochMillis: Long) = save(namespace, "home", value, savedAtEpochMillis)
    override suspend fun books(namespace: PrivateDataNamespace, queryKey: String, page: Int) = value<LibraryPage<BookSummary>>(namespace, "books|$queryKey|$page")
    override suspend fun saveBooks(namespace: PrivateDataNamespace, queryKey: String, value: LibraryPage<BookSummary>, savedAtEpochMillis: Long) = save(namespace, "books|$queryKey|${value.page}", value, savedAtEpochMillis)
    override suspend fun groupings(namespace: PrivateDataNamespace, queryKey: String, page: Int) = value<LibraryPage<GroupingSummary>>(namespace, "groupings|$queryKey|$page")
    override suspend fun saveGroupings(namespace: PrivateDataNamespace, queryKey: String, value: LibraryPage<GroupingSummary>, savedAtEpochMillis: Long) = save(namespace, "groupings|$queryKey|${value.page}", value, savedAtEpochMillis)
    override suspend fun facet(namespace: PrivateDataNamespace, queryKey: String, page: Int) = value<FacetPage>(namespace, "facet|$queryKey|$page")
    override suspend fun saveFacet(namespace: PrivateDataNamespace, queryKey: String, value: FacetPage, savedAtEpochMillis: Long) = save(namespace, "facet|$queryKey|${value.books.page}", value, savedAtEpochMillis)
    override suspend fun detail(namespace: PrivateDataNamespace, bookId: String) = value<BookDetailSummary>(namespace, "detail|$bookId")
    override suspend fun saveDetail(namespace: PrivateDataNamespace, value: BookDetailSummary, savedAtEpochMillis: Long) = save(namespace, "detail|${value.id}", value, savedAtEpochMillis)
    override suspend fun clear(namespace: PrivateDataNamespace) {
        val prefix = namespace.key() + "|"
        entries.keys.filter { it.startsWith(prefix) }.forEach(entries::remove)
    }

    private fun PrivateDataNamespace.key() = "$serverIdentity|$userId|$authorizationVersion"
    private fun save(namespace: PrivateDataNamespace, key: String, value: Any, savedAt: Long) {
        entries[namespace.key() + "|" + key] = CachedContent(value, savedAt)
    }

    @Suppress("UNCHECKED_CAST")
    private fun <T> value(namespace: PrivateDataNamespace, key: String): CachedContent<T>? =
        entries[namespace.key() + "|" + key] as? CachedContent<T>
}
