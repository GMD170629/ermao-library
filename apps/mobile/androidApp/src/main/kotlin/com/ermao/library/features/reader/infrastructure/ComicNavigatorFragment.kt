package com.ermao.library.features.reader.infrastructure

import android.animation.ValueAnimator
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.view.View
import android.view.ViewGroup
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.rememberTransformableState
import androidx.compose.foundation.gestures.transformable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.ScrollState
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.ComposeView
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.ViewCompositionStrategy
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.unit.dp
import androidx.fragment.app.Fragment
import com.ermao.library.shared.modules.reader.ComicNavigationCommand
import com.ermao.library.shared.modules.reader.ComicPresentationInput
import com.ermao.library.shared.modules.reader.ComicPresentationPlan
import com.ermao.library.shared.modules.reader.ComicReaderRuntime
import com.ermao.library.shared.modules.reader.ComicViewport
import com.ermao.library.shared.modules.reader.ReaderComicDirection
import com.ermao.library.shared.modules.reader.ReaderComicImageFit
import com.ermao.library.shared.modules.reader.ReaderComicPage
import com.ermao.library.shared.modules.reader.ReaderError
import com.ermao.library.shared.modules.reader.ReaderErrorCode
import com.ermao.library.shared.modules.reader.ReaderLocation
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.comicNormalizePage
import com.ermao.library.shared.modules.reader.comicNavigationGoToIndex
import com.ermao.library.shared.modules.reader.comicNavigationGoToProgress
import com.ermao.library.shared.modules.reader.comicNavigationNext
import com.ermao.library.shared.modules.reader.comicNavigationPrevious
import com.ermao.library.shared.modules.reader.comicOrderedPages
import com.ermao.library.shared.modules.reader.comicSpreadPages
import com.ermao.library.shared.modules.reader.comicSpreadStarts
import com.ermao.library.shared.modules.reader.comicVisualPages
import com.ermao.library.shared.modules.reader.readerSafetyComicPageMaxBytes
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.distinctUntilChanged
import org.readium.r2.shared.util.getOrElse
import kotlinx.coroutines.withContext
import org.readium.r2.shared.publication.Publication
import kotlin.math.roundToInt

internal class ComicNavigatorFragment : Fragment() {
    private var publication: Publication? = null
    private var pages: List<ReaderComicPage> = emptyList()
    private var onError: (ReaderError) -> Unit = {}

    private val preferenceState = MutableStateFlow(ReaderPreferences())
    private val _presentation = MutableStateFlow<Presentation?>(null)
    val presentation: StateFlow<Presentation?> = _presentation.asStateFlow()
    val currentProgress: Double
        get() = _presentation.value?.plan?.progress ?: 0.0
    private val _currentLocation = MutableStateFlow<ReaderLocation?>(null)
    val currentLocation: StateFlow<ReaderLocation?> = _currentLocation.asStateFlow()
    private var runtime: ComicReaderRuntime? = null
    private var viewport = ComicViewport(width = 600, height = 800, wide = false)
    private var focusedPageIndex = 0

    fun configure(
        publication: Publication,
        pages: List<ReaderComicPage>,
        preferences: ReaderPreferences,
        initialPageIndex: Int,
        onError: (ReaderError) -> Unit,
    ) {
        check(runtime == null) { "Comic navigator is already configured" }
        require(pages.isNotEmpty()) { "Comic navigator requires pages" }
        this.publication = publication
        this.pages = pages
        focusedPageIndex = initialPageIndex.coerceIn(0, pages.lastIndex)
        this.onError = onError
        preferenceState.value = preferences
        runtime = ComicReaderRuntime(
            ComicPresentationInput(
                pageCount = pages.size,
                preferences = preferences.comic,
                currentPageIndex = focusedPageIndex,
                viewport = viewport,
                resourceHrefs = pages.map(ReaderComicPage::resourceHref),
                reducedMotion = !ValueAnimator.areAnimatorsEnabled(),
            ),
        )
        publishPlan(requireNotNull(runtime).plan)
    }

    fun updatePreferences(preferences: ReaderPreferences) {
        val current = checkNotNull(runtime) { "Comic navigator is not configured" }
        preferenceState.value = preferences
        val updated = current.update(
            preferences = preferences.comic,
            viewport = viewport,
        )
        publishPlan(updated)
    }

    fun replacePublication(publication: Publication, preferences: ReaderPreferences) {
        checkNotNull(runtime) { "Comic navigator is not configured" }
        this.publication = publication
        updatePreferences(preferences)
    }

    fun updateViewport(width: Int, height: Int, wide: Boolean, reducedMotion: Boolean) {
        val current = runtime ?: return
        val safeWidth = width.coerceAtLeast(1)
        val safeHeight = height.coerceAtLeast(1)
        val nextViewport = ComicViewport(safeWidth, safeHeight, wide)
        if (nextViewport == viewport && current.plan.animatePageTurn ==
            (preferenceState.value.comic.pageTurnAnimation ==
                com.ermao.library.shared.modules.reader.ReaderPageTurnAnimation.Slide && !reducedMotion)
        ) return
        viewport = nextViewport
        publishPlan(current.update(viewport = viewport, reducedMotion = reducedMotion))
    }

    fun goBackward(animated: Boolean): Boolean = dispatch(
        comicNavigationPrevious(),
        animated,
    )

    fun goForward(animated: Boolean): Boolean = dispatch(
        comicNavigationNext(),
        animated,
    )

    fun goTo(pageIndex: Int, animated: Boolean): Boolean = dispatch(
        comicNavigationGoToIndex(pageIndex),
        animated,
    )

    fun goToProgress(progression: Double, animated: Boolean): Boolean = dispatch(
        comicNavigationGoToProgress(progression),
        animated,
    )

    fun release() {
        publication = null
        pages = emptyList()
        runtime = null
        _presentation.value = null
        _currentLocation.value = null
    }

    override fun onCreateView(
        inflater: android.view.LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: android.os.Bundle?,
    ): View {
        checkNotNull(runtime) { "Comic navigator is not configured" }
        return ComposeView(requireContext()).apply {
            setViewCompositionStrategy(ViewCompositionStrategy.DisposeOnViewTreeLifecycleDestroyed)
            setContent { ComicNavigatorContent(this@ComicNavigatorFragment) }
        }
    }

    private fun dispatch(command: ComicNavigationCommand, animated: Boolean): Boolean {
        val current = runtime ?: return false
        val result = current.dispatch(command)
        focusedPageIndex = result.plan.currentPageIndex
        publishPlan(result.plan, animated && result.moved)
        return result.moved
    }

    private fun publishPlan(next: ComicPresentationPlan, animated: Boolean = false) {
        _presentation.value = Presentation(next, animated)
        val pageIndex = focusedPageIndex.takeIf { it in next.logicalPageIndices } ?: next.anchorPageIndex
        focusedPageIndex = pageIndex
        val page = pages.getOrNull(pageIndex) ?: return
        _currentLocation.value = com.ermao.library.shared.modules.reader.ComicReaderLocation(
            resourceHref = page.resourceHref,
            pageIndex = page.pageIndex,
        )
    }

    private fun onVisiblePage(pageIndex: Int) {
        val current = runtime ?: return
        val normalized = comicNormalizePage(
            comicOrderedPages(pages.size),
            pageIndex,
            current.plan.spreadMode,
            current.plan.pairingPolicy,
        )
        if (normalized != current.plan.anchorPageIndex) {
            publishPlan(current.dispatch(comicNavigationGoToIndex(normalized)).plan)
        } else {
            val visiblePageIndex = focusedPageIndex.takeIf { it in current.plan.logicalPageIndices } ?: normalized
            focusedPageIndex = visiblePageIndex
            val page = pages.getOrNull(visiblePageIndex) ?: return
            _currentLocation.value = com.ermao.library.shared.modules.reader.ComicReaderLocation(
                resourceHref = page.resourceHref,
                pageIndex = page.pageIndex,
            )
        }
    }

    private fun requestError(error: ReaderError) {
        onError(error)
    }

    data class Presentation(
        val plan: ComicPresentationPlan,
        val animated: Boolean,
    )

    companion object {
        private const val MAX_DECODE_DIMENSION_PX = 8192
    }

    @Composable
    private fun ComicNavigatorContent(fragment: ComicNavigatorFragment) {
        val presentation by fragment.presentation.collectAsState()
        val preferences by fragment.preferenceState.collectAsState()
        val currentPresentation = presentation ?: return
        val currentPlan = currentPresentation.plan
        BoxWithConstraints(
            modifier = Modifier
                .fillMaxSize()
                .background(Color.Transparent),
        ) {
            val width = maxWidth.value.toInt().coerceAtLeast(1)
            val height = maxHeight.value.toInt().coerceAtLeast(1)
            val wide = maxWidth > 640.dp
            val reducedMotion = !ValueAnimator.areAnimatorsEnabled()
            LaunchedEffect(width, height, wide, reducedMotion) {
                fragment.updateViewport(width, height, wide, reducedMotion)
            }
            val units = remember(fragment.pages, currentPlan.spreadMode, currentPlan.pairingPolicy, currentPlan.direction) {
                layoutUnits(fragment.pages, currentPlan)
            }
            if (units.isEmpty()) return@BoxWithConstraints
            when (currentPlan.flow) {
                com.ermao.library.shared.modules.reader.ReaderReadingMode.Paged ->
                    PaginatedComic(
                        fragment = fragment,
                        units = units,
                        plan = currentPlan,
                        animated = currentPresentation.animated,
                        preferences = preferences,
                    )
                com.ermao.library.shared.modules.reader.ReaderReadingMode.ContinuousScroll ->
                    ContinuousComic(
                        fragment = fragment,
                        units = units,
                        plan = currentPlan,
                        animated = currentPresentation.animated,
                        preferences = preferences,
                    )
            }
        }
    }

    private data class RenderUnit(
        val anchorPageIndex: Int,
        val pages: List<ReaderComicPage>,
    )

    private fun layoutUnits(
        pages: List<ReaderComicPage>,
        plan: ComicPresentationPlan,
    ): List<RenderUnit> {
        val ordered = comicOrderedPages(pages.size)
        val starts = comicSpreadStarts(ordered, plan.spreadMode, plan.pairingPolicy)
        return starts.map { anchor ->
            val logical = comicSpreadPages(ordered, anchor, plan.spreadMode, plan.pairingPolicy)
            val visual = comicVisualPages(
                ordered,
                anchor,
                plan.spreadMode,
                plan.direction,
                plan.pairingPolicy,
            )
            RenderUnit(anchor, visual.mapNotNull { pages.getOrNull(it) }.takeIf { it.isNotEmpty() } ?: logical.mapNotNull { pages.getOrNull(it) })
        }
    }

    @OptIn(ExperimentalFoundationApi::class)
    @Composable
    private fun PaginatedComic(
        fragment: ComicNavigatorFragment,
        units: List<RenderUnit>,
        plan: ComicPresentationPlan,
        animated: Boolean,
        preferences: ReaderPreferences,
    ) {
        val currentUnit = units.indexOfFirst { it.pages.any { page -> page.pageIndex == plan.anchorPageIndex } }
            .coerceAtLeast(0)
        val pagerState = rememberPagerState(
            initialPage = currentUnit,
            pageCount = { units.size },
        )
        var totalScale by remember(plan.zoom, plan.imageVariant) {
            mutableFloatStateOf(plan.zoom.toFloat())
        }
        var translationX by remember(plan.zoom, plan.imageVariant) { mutableFloatStateOf(0f) }
        var translationY by remember(plan.zoom, plan.imageVariant) { mutableFloatStateOf(0f) }
        LaunchedEffect(plan.anchorPageIndex) {
            // A paginated pinch belongs only to the current page/spread.
            totalScale = plan.zoom.toFloat()
            translationX = 0f
            translationY = 0f
        }
        LaunchedEffect(units, plan.anchorPageIndex, plan.imageFit, plan.zoom, plan.pageGap, animated) {
            val target = units.indexOfFirst { it.pages.any { page -> page.pageIndex == plan.anchorPageIndex } }
                .coerceAtLeast(0)
            if (pagerState.currentPage != target) {
                if (animated && plan.animatePageTurn) pagerState.animateScrollToPage(target)
                else pagerState.scrollToPage(target)
            }
        }
        LaunchedEffect(pagerState, units) {
            snapshotFlow { pagerState.settledPage }
                .distinctUntilChanged()
                .collectLatest { index -> units.getOrNull(index)?.let { fragment.onVisiblePage(it.anchorPageIndex) } }
        }
        BoxWithConstraints(Modifier.fillMaxSize()) {
            val density = LocalDensity.current
            val viewportWidthPx = with(density) { maxWidth.toPx() }.coerceAtLeast(1f)
            val viewportHeightPx = with(density) { maxHeight.toPx() }.coerceAtLeast(1f)
            val transformableState = rememberTransformableState { _, zoomChange, panChange, _ ->
                val nextScale = comicTotalScaleAfterGesture(totalScale, zoomChange)
                totalScale = nextScale
                val maxX = ((viewportWidthPx * nextScale) - viewportWidthPx)
                    .coerceAtLeast(0f) / 2f
                val maxY = ((viewportHeightPx * nextScale) - viewportHeightPx)
                    .coerceAtLeast(0f) / 2f
                translationX = (translationX + panChange.x).coerceIn(-maxX, maxX)
                translationY = (translationY + panChange.y).coerceIn(-maxY, maxY)
            }
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .transformable(
                        state = transformableState,
                        canPan = { totalScale > 1.0001f },
                        lockRotationOnZoomPan = true,
                    ),
            ) {
                HorizontalPager(
                    state = pagerState,
                    modifier = Modifier
                        .fillMaxSize()
                        .graphicsLayer {
                            scaleX = totalScale
                            scaleY = totalScale
                            this.translationX = translationX
                            this.translationY = translationY
                        },
                    // Once enlarged, one-finger movement pans the spread instead
                    // of leaking through to page navigation.
                    userScrollEnabled = preferences.interaction.swipePageTurn && totalScale <= 1.0001f,
                    pageSpacing = 0.dp,
                    reverseLayout = plan.direction == ReaderComicDirection.RightToLeft,
                    key = { index -> units[index].anchorPageIndex },
                ) { index ->
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        ComicRenderUnit(
                            fragment = fragment,
                            unit = units[index],
                            plan = plan,
                            modifier = Modifier.width(plan.effectivePageWidth.dp),
                        )
                    }
                }
            }
        }
    }

    @Composable
    private fun ContinuousComic(
        fragment: ComicNavigatorFragment,
        units: List<RenderUnit>,
        plan: ComicPresentationPlan,
        animated: Boolean,
        preferences: ReaderPreferences,
    ) {
        val initialIndex = units.indexOfFirst { it.pages.any { page -> page.pageIndex == plan.anchorPageIndex } }
            .coerceAtLeast(0)
        val listState = rememberLazyListState(initialFirstVisibleItemIndex = initialIndex)
        LaunchedEffect(units, plan.anchorPageIndex, plan.imageFit, plan.zoom, animated) {
            val target = units.indexOfFirst { it.pages.any { page -> page.pageIndex == plan.anchorPageIndex } }
                .coerceAtLeast(0)
            if (listState.firstVisibleItemIndex != target) {
                if (animated && plan.animatePageTurn) listState.animateScrollToItem(target)
                else listState.scrollToItem(target)
            }
        }
        LaunchedEffect(listState, units) {
            snapshotFlow { listState.mostVisibleItemIndex() }
                .distinctUntilChanged()
                .collectLatest { index -> units.getOrNull(index)?.let { fragment.onVisiblePage(it.anchorPageIndex) } }
        }
        BoxWithConstraints(Modifier.fillMaxSize()) {
            val viewportWidth = maxWidth.value.roundToInt().coerceAtLeast(1)
            val viewportHeight = maxHeight.value.roundToInt().coerceAtLeast(1)
            var totalScale by remember(plan.zoom, plan.imageVariant) {
                mutableFloatStateOf(plan.zoom.toFloat())
            }
            val horizontalScrollState = remember(plan.zoom, plan.imageVariant) { ScrollState(0) }
            val transformableState = rememberTransformableState { _, zoomChange, _, _ ->
                totalScale = comicTotalScaleAfterGesture(totalScale, zoomChange)
            }
            val swipeEnabled = preferences.interaction.swipePageTurn
            val baseStreamWidth = minOf(viewportWidth, plan.effectivePageWidth).coerceAtLeast(1)
            val scaledWidth = (baseStreamWidth * totalScale).roundToInt()
                .coerceAtLeast(viewportWidth)
            val logicalHeight = (viewportHeight / totalScale).roundToInt().coerceAtLeast(1)
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .horizontalScroll(
                        state = horizontalScrollState,
                        enabled = swipeEnabled && scaledWidth > viewportWidth,
                    )
                    .transformable(
                        state = transformableState,
                        canPan = { false },
                        lockRotationOnZoomPan = true,
                    ),
            ) {
                Box(
                    modifier = Modifier
                        .width(scaledWidth.dp)
                        .height(viewportHeight.dp),
                ) {
                Box(
                    modifier = Modifier
                        .align(Alignment.TopCenter)
                        .width(baseStreamWidth.dp)
                        .height(logicalHeight.dp)
                        .graphicsLayer {
                            scaleX = totalScale
                            scaleY = totalScale
                            transformOrigin = TransformOrigin(0.5f, 0f)
                        },
                    ) {
                        LazyColumn(
                            state = listState,
                            modifier = Modifier.fillMaxSize(),
                            userScrollEnabled = swipeEnabled,
                            verticalArrangement = Arrangement.spacedBy(plan.pageGap.dp),
                        ) {
                            items(
                                items = units,
                                key = { it.anchorPageIndex },
                            ) { unit ->
                                Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                                    ComicRenderUnit(
                                        fragment = fragment,
                                        unit = unit,
                                        plan = plan,
                                        modifier = Modifier.width(plan.effectivePageWidth.dp),
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    @Composable
    private fun ComicRenderUnit(
        fragment: ComicNavigatorFragment,
        unit: RenderUnit,
        plan: ComicPresentationPlan,
        modifier: Modifier,
    ) {
        Row(
            modifier = modifier,
            horizontalArrangement = Arrangement.spacedBy(plan.pageGap.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            unit.pages.forEach { page ->
                ComicPageImage(
                    fragment = fragment,
                    page = page,
                    plan = plan,
                    modifier = if (unit.pages.size > 1) Modifier.weight(1f) else Modifier.fillMaxWidth(),
                )
            }
        }
    }

    @Composable
    private fun ComicPageImage(
        fragment: ComicNavigatorFragment,
        page: ReaderComicPage,
        plan: ComicPresentationPlan,
        modifier: Modifier,
    ) {
        val density = LocalDensity.current
        var loadError by remember(page.pageIndex, plan.imageVariant) { mutableStateOf<ReaderError?>(null) }
        val bitmap by androidx.compose.runtime.produceState<Bitmap?>(
            null,
            fragment.publication,
            page.pageIndex,
            plan.imageVariant,
            plan.imageFit,
        ) {
            val opened = fragment.publication ?: return@produceState
            value = try {
                loadComicPageBitmap(
                    opened,
                    page,
                    with(density) { plan.decodeMaxWidth.dp.roundToPx() },
                    with(density) { plan.decodeMaxHeight.dp.roundToPx() },
                )
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: OutOfMemoryError) {
                loadError = ReaderError(ReaderErrorCode.ComicOutOfMemoryRisk)
                null
            } catch (_: Throwable) {
                loadError = ReaderError(ReaderErrorCode.ComicPageDecodeFailed)
                null
            }
        }
        LaunchedEffect(loadError) {
            loadError?.let(fragment::requestError)
        }
        BoxWithConstraints(
            modifier = modifier
                .clip(RectangleShape)
                .heightIn(min = 1.dp),
            contentAlignment = Alignment.Center,
        ) {
            if (bitmap == null) {
                if (loadError == null) CircularProgressIndicator()
                else Spacer(Modifier.fillMaxSize())
                return@BoxWithConstraints
            }
            val image = requireNotNull(bitmap)
            val viewportWidthPx = constraints.maxWidth.coerceAtLeast(1)
            val viewportHeightPx = if (constraints.hasBoundedHeight) {
                constraints.maxHeight.coerceAtLeast(1)
            } else {
                with(density) { plan.decodeMaxHeight.dp.roundToPx() }.coerceAtLeast(1)
            }
            val imageSize = imageSizeFor(
                image = image,
                fit = plan.imageFit,
                viewportWidthPx = viewportWidthPx,
                viewportHeightPx = viewportHeightPx,
            )
            Image(
                bitmap = image.asImageBitmap(),
                contentDescription = null,
                contentScale = ContentScale.FillBounds,
                modifier = Modifier
                    .width(with(density) { imageSize.first.toDp() })
                    .height(with(density) { imageSize.second.toDp() })
            )
        }
    }

    private suspend fun loadComicPageBitmap(
        publication: Publication,
        page: ReaderComicPage,
        maxWidthPx: Int,
        maxHeightPx: Int,
    ): Bitmap {
        val link = publication.readingOrder.getOrNull(page.pageIndex)
            ?: error("Comic page is outside the publication reading order")
        val resource = publication.get(link)
            ?: error("Comic page resource is missing")
        val bytes = withContext(Dispatchers.IO) {
            resource.read().getOrElse { error("Comic page resource could not be read") }
        }
        require(bytes.isNotEmpty()) { "Comic page resource is empty" }
        require(bytes.size.toLong() <= readerSafetyComicPageMaxBytes()) { "Comic page exceeds safety budget" }
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        require(bounds.outWidth > 0 && bounds.outHeight > 0) { "Comic page image bounds are invalid" }
        val target = maxOf(maxWidthPx, maxHeightPx).coerceIn(1, MAX_DECODE_DIMENSION_PX)
        var sample = 1
        while (
            bounds.outWidth / sample > target * 2 ||
            bounds.outHeight / sample > target * 2
        ) {
            sample = (sample * 2).coerceAtMost(MAX_DECODE_DIMENSION_PX)
            if (sample == MAX_DECODE_DIMENSION_PX) break
        }
        val decoded = BitmapFactory.decodeByteArray(
            bytes,
            0,
            bytes.size,
            BitmapFactory.Options().apply {
                inSampleSize = sample
                inPreferredConfig = Bitmap.Config.ARGB_8888
            },
        )
        return decoded ?: error("Comic page image could not be decoded")
    }

    private fun imageSizeFor(
        image: Bitmap,
        fit: ReaderComicImageFit,
        viewportWidthPx: Int,
        viewportHeightPx: Int,
    ): Pair<Int, Int> {
        val aspect = image.width.toFloat() / image.height.toFloat().coerceAtLeast(1f)
        return when (fit) {
            ReaderComicImageFit.Width -> {
                val width = viewportWidthPx
                width to (width / aspect).toInt().coerceAtLeast(1)
            }
            ReaderComicImageFit.Height -> {
                val height = viewportHeightPx
                (height * aspect).toInt().coerceAtLeast(1) to height
            }
            ReaderComicImageFit.Contain -> {
                val width = minOf(viewportWidthPx.toFloat(), viewportHeightPx * aspect).toInt().coerceAtLeast(1)
                width to (width / aspect).toInt().coerceAtLeast(1)
            }
            ReaderComicImageFit.Original -> {
                val shrink = minOf(
                    1f,
                    viewportWidthPx.toFloat() / image.width.coerceAtLeast(1),
                    viewportHeightPx.toFloat() / image.height.coerceAtLeast(1),
                )
                (image.width * shrink).toInt().coerceAtLeast(1) to
                    (image.height * shrink).toInt().coerceAtLeast(1)
            }
        }
    }

    private fun androidx.compose.foundation.lazy.LazyListState.mostVisibleItemIndex(): Int {
        val viewportStart = layoutInfo.viewportStartOffset
        val viewportEnd = layoutInfo.viewportEndOffset
        return layoutInfo.visibleItemsInfo.maxByOrNull { item ->
            val visibleStart = maxOf(item.offset, viewportStart)
            val visibleEnd = minOf(item.offset + item.size, viewportEnd)
            (visibleEnd - visibleStart).coerceAtLeast(0)
        }?.index ?: firstVisibleItemIndex
    }
}

private fun comicTotalScaleAfterGesture(currentScale: Float, zoomChange: Float): Float {
    val safeZoomChange = zoomChange.takeIf { it.isFinite() && it > 0f } ?: 1f
    return (currentScale * safeZoomChange).coerceIn(0.6f, 2.4f)
}
