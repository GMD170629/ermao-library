package com.ermao.library.shared.modules.library

import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.library.domain.WorkDetailSummary
import com.ermao.library.shared.modules.library.domain.WorkSummary

data class CachedContent<T>(val value: T, val savedAtEpochMillis: Long)

/** Platform adapters persist these values in app-private storage using atomic replacement. */
interface LibraryCacheRepository {
    suspend fun home(namespace: PrivateDataNamespace): CachedContent<HomeSnapshot>?
    suspend fun saveHome(namespace: PrivateDataNamespace, value: HomeSnapshot, savedAtEpochMillis: Long)
    suspend fun works(namespace: PrivateDataNamespace, queryKey: String, page: Int): CachedContent<LibraryPage<WorkSummary>>?
    suspend fun saveWorks(namespace: PrivateDataNamespace, queryKey: String, value: LibraryPage<WorkSummary>, savedAtEpochMillis: Long)
    suspend fun groupings(namespace: PrivateDataNamespace, queryKey: String, page: Int): CachedContent<LibraryPage<GroupingSummary>>?
    suspend fun saveGroupings(namespace: PrivateDataNamespace, queryKey: String, value: LibraryPage<GroupingSummary>, savedAtEpochMillis: Long)
    suspend fun facet(namespace: PrivateDataNamespace, queryKey: String, page: Int): CachedContent<FacetPage>?
    suspend fun saveFacet(namespace: PrivateDataNamespace, queryKey: String, value: FacetPage, savedAtEpochMillis: Long)
    suspend fun detail(namespace: PrivateDataNamespace, workId: String): CachedContent<WorkDetailSummary>?
    suspend fun saveDetail(namespace: PrivateDataNamespace, value: WorkDetailSummary, savedAtEpochMillis: Long)
    suspend fun clear(namespace: PrivateDataNamespace)
}

class InMemoryLibraryCacheRepository : LibraryCacheRepository {
    private val entries = mutableMapOf<String, CachedContent<*>>()

    override suspend fun home(namespace: PrivateDataNamespace) = value<HomeSnapshot>(namespace, "home")
    override suspend fun saveHome(namespace: PrivateDataNamespace, value: HomeSnapshot, savedAtEpochMillis: Long) = save(namespace, "home", value, savedAtEpochMillis)
    override suspend fun works(namespace: PrivateDataNamespace, queryKey: String, page: Int) = value<LibraryPage<WorkSummary>>(namespace, "works|$queryKey|$page")
    override suspend fun saveWorks(namespace: PrivateDataNamespace, queryKey: String, value: LibraryPage<WorkSummary>, savedAtEpochMillis: Long) = save(namespace, "works|$queryKey|${value.page}", value, savedAtEpochMillis)
    override suspend fun groupings(namespace: PrivateDataNamespace, queryKey: String, page: Int) = value<LibraryPage<GroupingSummary>>(namespace, "groupings|$queryKey|$page")
    override suspend fun saveGroupings(namespace: PrivateDataNamespace, queryKey: String, value: LibraryPage<GroupingSummary>, savedAtEpochMillis: Long) = save(namespace, "groupings|$queryKey|${value.page}", value, savedAtEpochMillis)
    override suspend fun facet(namespace: PrivateDataNamespace, queryKey: String, page: Int) = value<FacetPage>(namespace, "facet|$queryKey|$page")
    override suspend fun saveFacet(namespace: PrivateDataNamespace, queryKey: String, value: FacetPage, savedAtEpochMillis: Long) = save(namespace, "facet|$queryKey|${value.works.page}", value, savedAtEpochMillis)
    override suspend fun detail(namespace: PrivateDataNamespace, workId: String) = value<WorkDetailSummary>(namespace, "detail|$workId")
    override suspend fun saveDetail(namespace: PrivateDataNamespace, value: WorkDetailSummary, savedAtEpochMillis: Long) = save(namespace, "detail|${value.id}", value, savedAtEpochMillis)
    override suspend fun clear(namespace: PrivateDataNamespace) {
        val prefix = namespace.key() + "|"
        entries.keys.filter { it.startsWith(prefix) }.forEach(entries::remove)
    }

    private fun PrivateDataNamespace.key() = "$serverIdentity|$userId|$authorizationVersion"
    private fun save(namespace: PrivateDataNamespace, key: String, value: Any, savedAt: Long) {
        entries[namespace.key() + "|" + key] = CachedContent(value, savedAt)
    }
    // Entries are only written and read through the matching capability key above.
    @Suppress("UNCHECKED_CAST")
    private fun <T> value(namespace: PrivateDataNamespace, key: String): CachedContent<T>? =
        entries[namespace.key() + "|" + key] as? CachedContent<T>
}
