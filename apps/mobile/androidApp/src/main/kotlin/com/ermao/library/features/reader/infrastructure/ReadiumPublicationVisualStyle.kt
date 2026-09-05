package com.ermao.library.features.reader.infrastructure

import com.ermao.library.design.GeneratedDesignTokens

/** Platform CSS that completes Readium's semantic theme mapping for authored backgrounds and links. */
internal object ReadiumPublicationVisualStyle {
    val markup: String = """
        <style data-shuku-reader-theme-adapter="v1">
        :root[style*="--USER__backgroundColor"] {
          background-image: none !important;
        }
        :root[style*="--USER__backgroundColor"] body,
        :root[style*="--USER__backgroundColor"] body *,
        :root[style*="--USER__backgroundColor"] body *::before,
        :root[style*="--USER__backgroundColor"] body *::after {
          background-color: transparent !important;
          background-image: none !important;
        }
        :root.readium-sepia-on {
          --RS__linkColor: ${GeneratedDesignTokens.Reader.Warm.Link} !important;
          --RS__visitedColor: ${GeneratedDesignTokens.Reader.Warm.Link} !important;
        }
        :root.readium-night-on {
          --RS__linkColor: ${GeneratedDesignTokens.Reader.Night.Link} !important;
          --RS__visitedColor: ${GeneratedDesignTokens.Reader.Night.Link} !important;
        }
        :root[style*="${GeneratedDesignTokens.Reader.Day.Canvas}" i] {
          --RS__linkColor: ${GeneratedDesignTokens.Reader.Day.Link} !important;
          --RS__visitedColor: ${GeneratedDesignTokens.Reader.Day.Link} !important;
        }
        :root[style*="${GeneratedDesignTokens.Reader.Green.Canvas}" i] {
          --RS__linkColor: ${GeneratedDesignTokens.Reader.Green.Link} !important;
          --RS__visitedColor: ${GeneratedDesignTokens.Reader.Green.Link} !important;
        }
        </style>
    """.trimIndent()
}
