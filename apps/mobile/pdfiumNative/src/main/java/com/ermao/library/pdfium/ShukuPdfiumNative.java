package com.ermao.library.pdfium;

import java.nio.ByteBuffer;
import java.util.Objects;

/** Stable Java ABI for the repository-owned PDFium build. */
public final class ShukuPdfiumNative {
    public static final String EXPECTED_REVISION = "875172eae557a308d0c5b2be43822814c8a885bb";
    public static final int EXPECTED_WRAPPER_ABI = 1;
    private static final boolean LIBRARY_LOADED;

    static {
        boolean loaded;
        try {
            System.loadLibrary("shuku_pdfium");
            loaded = EXPECTED_REVISION.equals(nativeRevision())
                    && nativeWrapperAbiVersion() == EXPECTED_WRAPPER_ABI
                    && nativeInitialize() == Status.OK.value;
        } catch (LinkageError error) {
            loaded = false;
        }
        LIBRARY_LOADED = loaded;
    }

    private ShukuPdfiumNative() {}

    public static boolean isAvailable() {
        return LIBRARY_LOADED;
    }

    public static String revision() {
        requireAvailable();
        return nativeRevision();
    }

    public static int wrapperAbiVersion() {
        requireAvailable();
        return nativeWrapperAbiVersion();
    }

    public interface ByteSource {
        boolean isRangeCached(long offset, long size);
        boolean readCachedBlock(long offset, ByteBuffer destination);
        void requestRange(long offset, long size);
    }

    public enum Status {
        OK(0), NEED_DATA(1), INVALID_ARGUMENT(2), INVALID_DOCUMENT(3),
        ENCRYPTED(4), PAGE_LOAD_FAILED(5), RENDER_FAILED(6), OUT_OF_MEMORY_RISK(7);

        public final int value;

        Status(int value) {
            this.value = value;
        }

        public static Status fromNative(int value) {
            for (Status status : values()) {
                if (status.value == value) return status;
            }
            throw new IllegalStateException("Unknown PDFium status: " + value);
        }
    }

    public static final class PageSize {
        public final float widthPoints;
        public final float heightPoints;

        PageSize(float widthPoints, float heightPoints) {
            this.widthPoints = widthPoints;
            this.heightPoints = heightPoints;
        }
    }

    public static final class Document implements AutoCloseable {
        private long handle;

        public Document(long length, ByteSource source) {
            requireAvailable();
            Objects.requireNonNull(source, "source");
            handle = nativeCreateDocument(length, source);
            if (handle == 0) throw new IllegalArgumentException("Unable to create PDFium byte source");
        }

        public Status stepDocument() {
            return Status.fromNative(nativeStepDocument(requireOpen()));
        }

        public Status stepPage(int pageIndex) {
            return Status.fromNative(nativeStepPage(requireOpen(), pageIndex));
        }

        public int pageCount() {
            return nativePageCount(requireOpen());
        }

        public PageSize pageSize(int pageIndex) {
            float[] size = nativePageSize(requireOpen(), pageIndex);
            return size == null ? null : new PageSize(size[0], size[1]);
        }

        public Status renderPage(
                int pageIndex,
                int width,
                int height,
                int stride,
                long maxPixels,
                ByteBuffer destination
        ) {
            if (!destination.isDirect()) throw new IllegalArgumentException("Destination must be direct");
            return Status.fromNative(nativeRenderPage(
                    requireOpen(), pageIndex, width, height, stride, maxPixels, destination));
        }

        @Override
        public synchronized void close() {
            if (handle == 0) return;
            nativeCloseDocument(handle);
            handle = 0;
        }

        private synchronized long requireOpen() {
            if (handle == 0) throw new IllegalStateException("PDFium document is closed");
            return handle;
        }
    }

    private static void requireAvailable() {
        if (!LIBRARY_LOADED) throw new IllegalStateException("Locked PDFium artifact is unavailable or mismatched");
    }

    private static native String nativeRevision();
    private static native int nativeWrapperAbiVersion();
    private static native int nativeInitialize();
    private static native long nativeCreateDocument(long length, ByteSource source);
    private static native void nativeCloseDocument(long handle);
    private static native int nativeStepDocument(long handle);
    private static native int nativeStepPage(long handle, int pageIndex);
    private static native int nativePageCount(long handle);
    private static native float[] nativePageSize(long handle, int pageIndex);
    private static native int nativeRenderPage(
            long handle, int pageIndex, int width, int height, int stride, long maxPixels, ByteBuffer destination);
}
