@file:OptIn(org.readium.r2.shared.InternalReadiumApi::class)

package com.ermao.library.features.reader.infrastructure

import android.graphics.Bitmap
import android.graphics.PointF
import android.os.Bundle
import android.view.GestureDetector
import android.view.LayoutInflater
import android.view.MotionEvent
import android.view.ScaleGestureDetector
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.ImageView
import androidx.appcompat.widget.AppCompatImageView
import androidx.core.view.doOnLayout
import androidx.lifecycle.lifecycleScope
import com.ermao.library.R
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.readium.r2.navigator.OverflowableNavigator
import org.readium.r2.navigator.SimpleOverflow
import org.readium.r2.navigator.input.TapEvent
import org.readium.r2.navigator.pdf.PdfDocumentFragment
import org.readium.r2.navigator.pdf.PdfDocumentFragmentInput
import org.readium.r2.navigator.pdf.PdfEngineProvider
import org.readium.r2.navigator.preferences.Axis
import org.readium.r2.navigator.preferences.Configurable
import org.readium.r2.navigator.preferences.PreferencesEditor
import org.readium.r2.navigator.preferences.ReadingProgression
import org.readium.r2.navigator.util.SingleFragmentFactory
import org.readium.r2.navigator.util.createFragmentFactory
import org.readium.r2.shared.ExperimentalReadiumApi
import org.readium.r2.shared.publication.Metadata
import org.readium.r2.shared.publication.Publication
import org.readium.r2.shared.util.Url
import org.readium.r2.shared.util.data.ReadError

internal data object ShukuPdfiumSettings : Configurable.Settings

internal data object ShukuPdfiumPreferences : Configurable.Preferences<ShukuPdfiumPreferences> {
    override fun plus(other: ShukuPdfiumPreferences): ShukuPdfiumPreferences = this
}

internal class ShukuPdfiumPreferencesEditor : PreferencesEditor<ShukuPdfiumPreferences> {
    override val preferences: ShukuPdfiumPreferences = ShukuPdfiumPreferences
    override fun clear() = Unit
}

@OptIn(ExperimentalReadiumApi::class)
internal class ShukuPdfiumEngineProvider(
    private val document: ShukuPdfiumDocument,
) : PdfEngineProvider<ShukuPdfiumSettings, ShukuPdfiumPreferences, ShukuPdfiumPreferencesEditor> {
    override fun createDocumentFragmentFactory(
        input: PdfDocumentFragmentInput<ShukuPdfiumSettings>,
    ): SingleFragmentFactory<ShukuPdfiumDocumentFragment> = createFragmentFactory {
        ShukuPdfiumDocumentFragment(
            document = document,
            href = input.href,
            initialPageIndex = input.pageIndex,
            listener = object : ShukuPdfiumDocumentFragment.Listener {
                override fun onFailure(href: Url, error: Exception) {
                    input.navigatorListener?.onResourceLoadFailed(href, ReadError.Decoding(error))
                }

                override fun onTap(point: PointF): Boolean =
                    input.inputListener?.onTap(TapEvent(point)) ?: false
            },
        )
    }

    override fun computeSettings(metadata: Metadata, preferences: ShukuPdfiumPreferences): ShukuPdfiumSettings =
        ShukuPdfiumSettings

    override fun computeOverflow(settings: ShukuPdfiumSettings): OverflowableNavigator.Overflow =
        SimpleOverflow(ReadingProgression.LTR, scroll = false, axis = Axis.HORIZONTAL)

    override fun createPreferenceEditor(
        publication: Publication,
        initialPreferences: ShukuPdfiumPreferences,
    ): ShukuPdfiumPreferencesEditor = ShukuPdfiumPreferencesEditor()

    override fun createEmptyPreferences(): ShukuPdfiumPreferences = ShukuPdfiumPreferences
}

@OptIn(ExperimentalReadiumApi::class)
internal class ShukuPdfiumDocumentFragment(
    private val document: ShukuPdfiumDocument,
    private val href: Url,
    initialPageIndex: Int,
    private val listener: Listener?,
) : PdfDocumentFragment<ShukuPdfiumSettings>() {
    internal interface Listener {
        fun onFailure(href: Url, error: Exception)
        fun onTap(point: PointF): Boolean
    }

    private val pageMutex = Mutex()
    private val mutablePageIndex = kotlinx.coroutines.flow.MutableStateFlow(initialPageIndex)
    override val pageIndex: kotlinx.coroutines.flow.StateFlow<Int> = mutablePageIndex
    private lateinit var imageView: AppCompatImageView
    private var renderJob: Job? = null
    private var prefetchJob: Job? = null
    private var bitmap: Bitmap? = null
    private var zoom = 1f

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?,
    ): View = FrameLayout(inflater.context).apply {
        setBackgroundColor(android.graphics.Color.BLACK)
        imageView = AppCompatImageView(context).apply {
            scaleType = ImageView.ScaleType.FIT_CENTER
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_YES
        }
        addView(
            imageView,
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            ),
        )
        installGestures(this)
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        view.doOnLayout { render(mutablePageIndex.value) }
    }

    override fun goToPageIndex(index: Int, animated: Boolean): Boolean {
        if (index !in 0 until document.pageCount) return false
        mutablePageIndex.value = index
        zoom = 1f
        applyZoom()
        render(index)
        return true
    }

    override fun applySettings(settings: ShukuPdfiumSettings) = Unit

    override fun onDestroyView() {
        renderJob?.cancel()
        prefetchJob?.cancel()
        imageView.setImageDrawable(null)
        bitmap?.recycle()
        bitmap = null
        super.onDestroyView()
    }

    private fun render(index: Int) {
        if (!::imageView.isInitialized || imageView.width <= 0 || imageView.height <= 0) return
        renderJob?.cancel()
        prefetchJob?.cancel()
        renderJob = viewLifecycleOwner.lifecycleScope.launch {
            try {
                val rendered = pageMutex.withLock {
                    val size = document.pageSize(index)
                    val scale = minOf(
                        imageView.width / size.widthPoints,
                        imageView.height / size.heightPoints,
                    ).coerceAtLeast(MIN_RENDER_SCALE)
                    document.renderPage(
                        index,
                        maxOf(1, (size.widthPoints * scale).toInt()),
                        maxOf(1, (size.heightPoints * scale).toInt()),
                    )
                }
                if (index != mutablePageIndex.value) {
                    rendered.recycle()
                    return@launch
                }
                val previous = bitmap
                bitmap = rendered
                imageView.setImageBitmap(rendered)
                imageView.contentDescription = getString(
                    R.string.reader_pdf_page_description,
                    index + 1,
                    document.pageCount,
                )
                previous?.takeIf { it !== rendered }?.recycle()
                val neighbor = (index + 1).takeIf { it < document.pageCount }
                    ?: (index - 1).takeIf { it >= 0 }
                if (neighbor != null) {
                    prefetchJob = viewLifecycleOwner.lifecycleScope.launch {
                        document.prefetchPage(neighbor)
                    }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                listener?.onFailure(href, error)
            } catch (error: OutOfMemoryError) {
                listener?.onFailure(
                    href,
                    ShukuPdfiumFailure(com.ermao.library.shared.modules.reader.ReaderErrorCode.OutOfMemoryRisk),
                )
            }
        }
    }

    private fun installGestures(view: View) {
        var pendingTap = PointF()
        var clickPending = false
        view.isClickable = true
        view.setOnClickListener { listener?.onTap(pendingTap) }
        val scaleDetector = ScaleGestureDetector(
            view.context,
            object : ScaleGestureDetector.SimpleOnScaleGestureListener() {
                override fun onScale(detector: ScaleGestureDetector): Boolean {
                    zoom = (zoom * detector.scaleFactor).coerceIn(MIN_ZOOM, MAX_ZOOM)
                    applyZoom()
                    return true
                }
            },
        )
        val gestureDetector = GestureDetector(
            view.context,
            object : GestureDetector.SimpleOnGestureListener() {
                override fun onDown(event: MotionEvent): Boolean = true

                override fun onSingleTapUp(event: MotionEvent): Boolean {
                    pendingTap = PointF(event.x, event.y)
                    clickPending = true
                    return true
                }

                override fun onFling(
                    first: MotionEvent?,
                    second: MotionEvent,
                    velocityX: Float,
                    velocityY: Float,
                ): Boolean {
                    clickPending = false
                    if (first == null || zoom > 1.01f || kotlin.math.abs(velocityX) <= kotlin.math.abs(velocityY)) {
                        return false
                    }
                    val target = if (velocityX < 0) mutablePageIndex.value + 1 else mutablePageIndex.value - 1
                    return goToPageIndex(target, animated = true)
                }
            },
        )
        view.setOnTouchListener { _, event ->
            val scaled = scaleDetector.onTouchEvent(event)
            val gestured = gestureDetector.onTouchEvent(event)
            val clicked = if (event.actionMasked == MotionEvent.ACTION_UP && clickPending) {
                clickPending = false
                view.performClick()
            } else {
                false
            }
            gestured || scaled || clicked
        }
    }

    private fun applyZoom() {
        if (!::imageView.isInitialized) return
        imageView.scaleX = zoom
        imageView.scaleY = zoom
    }

    private companion object {
        const val MIN_RENDER_SCALE = 0.1f
        const val MIN_ZOOM = 1f
        const val MAX_ZOOM = 5f
    }
}
