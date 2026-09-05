package com.ermao.buildlogic;

import groovy.json.JsonOutput;
import groovy.json.JsonSlurper;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.regex.Pattern;

final class VisualTokenGenerator {
    private static final Pattern COLOR = Pattern.compile("^#[0-9A-F]{6}$");
    private static final Pattern VERSION = Pattern.compile("^[0-9]+\\.[0-9]+\\.[0-9]+$");
    private static final List<String> READER_THEMES = List.of("day", "warm", "green", "night", "black");
    private static final Set<String> READER_PALETTE_KEYS = Set.of(
        "canvas", "surface", "surfaceRaised", "textPrimary", "textSecondary", "textTertiary",
        "divider", "link", "accent", "accentSoft", "onAccent", "colorScheme"
    );
    private static final Set<String> APP_PALETTE_KEYS = Set.of(
        "canvas", "navigation", "surface", "surfaceRaised", "textPrimary", "textSecondary",
        "textTertiary", "divider", "dividerStrong", "brandAccent", "brandHover", "actionAccent",
        "accentSoft", "accentSofter", "focusRing", "success", "warning", "danger",
        "dangerContainer", "onDanger", "onDangerContainer", "onAction"
    );
    private static final Set<String> TYPOGRAPHY_ROLES = Set.of(
        "display", "title", "sectionTitle", "headline", "body", "callout", "label", "caption",
        "button", "readerChapter", "readerBody", "readerAuxiliary"
    );

    private VisualTokenGenerator() {}

    static Map<String, Object> parse(File file) {
        Object parsed = new JsonSlurper().parse(file);
        if (!(parsed instanceof Map<?, ?> raw)) {
            throw new IllegalStateException("Visual token root must be an object");
        }
        return normalizeMap(raw);
    }

    static Map<String, Object> parseText(String source) {
        Object parsed = new JsonSlurper().parseText(source);
        if (!(parsed instanceof Map<?, ?> raw)) {
            throw new IllegalStateException("Visual token root must be an object");
        }
        return normalizeMap(raw);
    }

    static void validate(Map<String, Object> root) {
        requireExactKeys(root, "root", Set.of(
            "$schema", "schemaVersion", "contractVersion", "appearance", "colors", "reader",
            "spacing", "radii", "typography", "components", "accessibility"
        ));
        require(((Number) required(root, "schemaVersion", Number.class)).intValue() == 3, "Unsupported token schema");
        require(VERSION.matcher(string(root, "contractVersion")).matches(), "Invalid contractVersion");

        Map<String, Object> appearance = map(root, "appearance");
        requireExactKeys(appearance, "appearance", Set.of("app"));
        require("lightOnly".equals(string(appearance, "app")), "App appearance must be lightOnly");

        Map<String, Object> colors = map(root, "colors");
        requireExactKeys(colors, "colors", Set.of("app"));
        Map<String, Object> app = map(colors, "app");
        requireExactKeys(app, "colors.app", APP_PALETTE_KEYS);
        validateColors(app, "colors.app", Set.of());
        require(contrast(string(app, "textPrimary"), string(app, "canvas")) >= 4.5,
            "App primary text contrast must be at least 4.5:1");
        require(contrast(string(app, "onAction"), string(app, "actionAccent")) >= 4.5,
            "App action contrast must be at least 4.5:1");

        Map<String, Object> reader = map(root, "reader");
        requireExactKeys(reader, "reader", Set.of("themes"));
        Map<String, Object> themes = map(reader, "themes");
        requireExactKeys(themes, "reader.themes", Set.copyOf(READER_THEMES));
        for (String name : READER_THEMES) {
            Map<String, Object> palette = map(themes, name);
            requireExactKeys(palette, "reader.themes." + name, READER_PALETTE_KEYS);
            validateColors(palette, "reader.themes." + name, Set.of("colorScheme"));
            require(Set.of("light", "dark").contains(string(palette, "colorScheme")),
                "Invalid reader colorScheme: " + name);
            require(contrast(string(palette, "textPrimary"), string(palette, "canvas")) >= 4.5,
                "Reader " + name + " primary text contrast must be at least 4.5:1");
            require(contrast(string(palette, "link"), string(palette, "canvas")) >= 3.0,
                "Reader " + name + " link contrast must be at least 3:1");
            require(contrast(string(palette, "onAccent"), string(palette, "accent")) >= 3.0,
                "Reader " + name + " control contrast must be at least 3:1");
        }

        validateNumericMap(map(root, "spacing"), "spacing", 0.0);
        Map<String, Object> radii = map(root, "radii");
        requireExactKeys(radii, "radii", Set.of(
            "coverCompact", "control", "coverHero", "panel", "task", "dialog", "pill"
        ));
        validateNumericMap(radii, "radii", 0.0);

        Map<String, Object> typography = map(root, "typography");
        requireExactKeys(typography, "typography", TYPOGRAPHY_ROLES);
        for (Map.Entry<String, Object> entry : typography.entrySet()) {
            String name = entry.getKey();
            Map<String, Object> role = asMap(entry.getValue(), "typography." + name);
            requireExactKeys(role, "typography." + name, Set.of("size", "lineHeight", "weight", "familyRole"));
            double size = number(role, "size").doubleValue();
            double lineHeight = number(role, "lineHeight").doubleValue();
            double weight = number(role, "weight").doubleValue();
            require(size > 0 && lineHeight >= size, "Invalid typography metrics: " + name);
            require(weight >= 100 && weight <= 900, "Invalid typography weight: " + name);
            require(Set.of("systemSans", "readerSerif").contains(string(role, "familyRole")),
                "Unknown typography familyRole: " + name);
        }

        Map<String, Object> components = map(root, "components");
        requireExactKeys(components, "components", Set.of("cover", "progress", "settings", "readerControls"));
        Map<String, Object> cover = map(components, "cover");
        requireExactKeys(cover, "components.cover", Set.of(
            "aspectWidth", "aspectHeight", "contentMode", "compactRadiusToken", "heroRadiusToken"
        ));
        require(number(cover, "aspectWidth").doubleValue() > 0, "Invalid cover aspectWidth");
        require(number(cover, "aspectHeight").doubleValue() > 0, "Invalid cover aspectHeight");
        require("contain".equals(string(cover, "contentMode")), "Unsupported cover contentMode");
        for (String key : List.of("compactRadiusToken", "heroRadiusToken")) {
            require(radii.containsKey(string(cover, key)), "Unknown radius reference: " + key);
        }
        validateNumericMap(map(components, "progress"), "components.progress", 0.0);
        validateNumericMap(map(components, "settings"), "components.settings", 0.0);
        Map<String, Object> readerControls = map(components, "readerControls");
        requireExactKeys(readerControls, "components.readerControls", Set.of(
            "homeHeight", "homeContentHeight", "tocPanelHeight", "notesPanelHeight",
            "appearancePanelHeight", "settingsPanelHeight", "navigationHeight", "contentInset",
            "outerRadius", "topClearance", "compactControlHeight", "themeSwatchSize"
        ));
        validateNumericMap(readerControls, "components.readerControls", 0.0);
        require(number(readerControls, "compactControlHeight").doubleValue() >= 44.0,
            "Reader compact controls must remain at least 44 logical pixels");
        require(number(readerControls, "homeHeight").doubleValue()
                >= number(readerControls, "homeContentHeight").doubleValue(),
            "Reader home surface must contain its home controls");
        for (String key : List.of("tocPanelHeight", "notesPanelHeight", "appearancePanelHeight", "settingsPanelHeight")) {
            require(number(readerControls, key).doubleValue()
                    > number(readerControls, "navigationHeight").doubleValue(),
                "Reader panel must leave room above persistent navigation: " + key);
        }

        Map<String, Object> accessibility = map(root, "accessibility");
        requireExactKeys(accessibility, "accessibility", Set.of("minimumTouchTarget"));
        Map<String, Object> targets = map(accessibility, "minimumTouchTarget");
        requireExactKeys(targets, "accessibility.minimumTouchTarget", Set.of("web", "ios", "android"));
        validateNumericMap(targets, "accessibility.minimumTouchTarget", 44.0);
        require(number(targets, "android").doubleValue() >= 48.0,
            "Android minimum touch target must be at least 48");
    }

    static Map<String, String> outputs(Map<String, Object> root, String digest) {
        String version = string(root, "contractVersion");
        String header = "Generated from packages/design-contracts/visual-tokens.json v" + version
            + " sha256:" + digest + ". Do not edit.";
        Map<String, String> output = new LinkedHashMap<>();
        output.put("kotlin/com/ermao/library/design/GeneratedDesignTokens.kt", renderKotlin(root, digest, header));
        output.put("swift/GeneratedDesignTokens.swift", renderSwift(root, digest, header));
        output.put("android/values/generated_design_tokens.xml", renderAndroid(root, header));
        output.put("android/values-night/generated_design_tokens.xml", renderAndroid(root, header));
        output.put("css/visual-tokens.css", renderCss(root, header));
        output.put("typescript/visual-tokens.ts", renderTypeScript(root, header));
        return output;
    }

    private static String renderKotlin(Map<String, Object> root, String digest, String header) {
        StringBuilder out = new StringBuilder();
        line(out, "// " + header);
        line(out, "package com.ermao.library.design");
        line(out, "");
        line(out, "internal object GeneratedDesignTokens {");
        line(out, "    const val ContractVersion = \"" + string(root, "contractVersion") + "\"");
        line(out, "    const val ContractSha256 = \"" + digest + "\"");
        appendKotlinObject(out, "App", map(map(root, "colors"), "app"), 4);
        line(out, "    object Reader {");
        Map<String, Object> themes = map(map(root, "reader"), "themes");
        for (String theme : READER_THEMES) {
            appendKotlinObject(out, identifier(theme), map(themes, theme), 8);
        }
        line(out, "    }");
        appendKotlinObject(out, "Spacing", map(root, "spacing"), 4);
        appendKotlinObject(out, "Radii", map(root, "radii"), 4);
        for (Map.Entry<String, Object> entry : sorted(map(root, "typography")).entrySet()) {
            appendKotlinObject(out, identifier(entry.getKey()), asMap(entry.getValue(), entry.getKey()), 4);
        }
        Map<String, Object> components = map(root, "components");
        appendKotlinObject(out, "Cover", map(components, "cover"), 4);
        appendKotlinObject(out, "Progress", map(components, "progress"), 4);
        appendKotlinObject(out, "Settings", map(components, "settings"), 4);
        appendKotlinObject(out, "ReaderControls", map(components, "readerControls"), 4);
        line(out, "    object Accessibility {");
        appendKotlinObject(out, "MinimumTouchTarget", map(map(root, "accessibility"), "minimumTouchTarget"), 8);
        line(out, "    }");
        line(out, "}");
        return out.toString();
    }

    private static void appendKotlinObject(
        StringBuilder out,
        String name,
        Map<String, Object> values,
        int indent
    ) {
        String pad = " ".repeat(indent);
        line(out, pad + "object " + name + " {");
        for (Map.Entry<String, Object> entry : sorted(values).entrySet()) {
            line(out, pad + "    const val " + property(entry.getKey(), true) + " = " + kotlinLiteral(entry.getValue()));
        }
        line(out, pad + "}");
    }

    private static String renderSwift(Map<String, Object> root, String digest, String header) {
        StringBuilder out = new StringBuilder();
        line(out, "// " + header);
        line(out, "import Foundation");
        line(out, "");
        line(out, "enum GeneratedDesignTokens {");
        line(out, "    static let contractVersion = \"" + string(root, "contractVersion") + "\"");
        line(out, "    static let contractSha256 = \"" + digest + "\"");
        appendSwiftEnum(out, "App", map(map(root, "colors"), "app"), 4);
        line(out, "    enum Reader {");
        Map<String, Object> themes = map(map(root, "reader"), "themes");
        for (String theme : READER_THEMES) {
            appendSwiftEnum(out, identifier(theme), map(themes, theme), 8);
        }
        line(out, "    }");
        appendSwiftEnum(out, "Spacing", map(root, "spacing"), 4);
        appendSwiftEnum(out, "Radii", map(root, "radii"), 4);
        for (Map.Entry<String, Object> entry : sorted(map(root, "typography")).entrySet()) {
            appendSwiftEnum(out, identifier(entry.getKey()), asMap(entry.getValue(), entry.getKey()), 4);
        }
        Map<String, Object> components = map(root, "components");
        appendSwiftEnum(out, "Cover", map(components, "cover"), 4);
        appendSwiftEnum(out, "Progress", map(components, "progress"), 4);
        appendSwiftEnum(out, "Settings", map(components, "settings"), 4);
        appendSwiftEnum(out, "ReaderControls", map(components, "readerControls"), 4);
        line(out, "    enum Accessibility {");
        appendSwiftEnum(out, "MinimumTouchTarget", map(map(root, "accessibility"), "minimumTouchTarget"), 8);
        line(out, "    }");
        line(out, "}");
        return out.toString();
    }

    private static void appendSwiftEnum(
        StringBuilder out,
        String name,
        Map<String, Object> values,
        int indent
    ) {
        String pad = " ".repeat(indent);
        line(out, pad + "enum " + name + " {");
        for (Map.Entry<String, Object> entry : sorted(values).entrySet()) {
            String type = entry.getValue() instanceof Number ? ": Double" : "";
            line(out, pad + "    static let " + property(entry.getKey(), false) + type + " = " + swiftLiteral(entry.getValue()));
        }
        line(out, pad + "}");
    }

    private static String renderAndroid(Map<String, Object> root, String header) {
        String canvas = string(map(map(root, "colors"), "app"), "canvas");
        return "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
            + "<!-- " + header + " -->\n"
            + "<resources>\n"
            + "    <color name=\"launcher_background\">" + canvas + "</color>\n"
            + "    <color name=\"window_background\">" + canvas + "</color>\n"
            + "</resources>\n";
    }

    private static String renderCss(Map<String, Object> root, String header) {
        StringBuilder out = new StringBuilder();
        line(out, "/* " + header + " */");
        line(out, ":root {");
        Map<String, Object> app = map(map(root, "colors"), "app");
        appendCssMap(out, "color-app", app, "");
        Map<String, Object> themes = map(map(root, "reader"), "themes");
        for (String theme : READER_THEMES) {
            appendCssMap(out, "color-reader-" + theme, map(themes, theme), "");
        }
        appendCssMap(out, "spacing", map(root, "spacing"), "px");
        appendCssMap(out, "radius", map(root, "radii"), "px");
        for (Map.Entry<String, Object> role : sorted(map(root, "typography")).entrySet()) {
            Map<String, Object> values = asMap(role.getValue(), role.getKey());
            for (Map.Entry<String, Object> token : sorted(values).entrySet()) {
                String suffix = Set.of("size", "lineHeight").contains(token.getKey()) ? "px" : "";
                line(out, "  --visual-typography-" + kebab(role.getKey()) + "-" + kebab(token.getKey())
                    + ": " + cssLiteral(token.getValue()) + suffix + ";");
            }
        }
        for (Map.Entry<String, Object> group : sorted(map(root, "components")).entrySet()) {
            Map<String, Object> values = asMap(group.getValue(), group.getKey());
            for (Map.Entry<String, Object> token : sorted(values).entrySet()) {
                String suffix = token.getValue() instanceof Number && !token.getKey().startsWith("aspect") ? "px" : "";
                line(out, "  --visual-component-" + kebab(group.getKey()) + "-" + kebab(token.getKey())
                    + ": " + cssLiteral(token.getValue()) + suffix + ";");
            }
        }
        appendCssMap(out, "minimum-touch-target", map(map(root, "accessibility"), "minimumTouchTarget"), "px");
        line(out, "}");
        line(out, "");
        for (int themeIndex = 0; themeIndex < READER_THEMES.size(); themeIndex++) {
            String theme = READER_THEMES.get(themeIndex);
            line(out, "[data-reader-theme='" + theme + "'] {");
            for (String key : sorted(map(themes, theme)).keySet()) {
                line(out, "  --visual-reader-" + kebab(key) + ": var(--visual-color-reader-" + theme + "-" + kebab(key) + ");");
            }
            line(out, "}");
            if (themeIndex + 1 < READER_THEMES.size()) {
                line(out, "");
            }
        }
        return out.toString();
    }

    private static void appendCssMap(StringBuilder out, String prefix, Map<String, Object> values, String unit) {
        for (Map.Entry<String, Object> entry : sorted(values).entrySet()) {
            line(out, "  --visual-" + prefix + "-" + kebab(entry.getKey()) + ": "
                + cssLiteral(entry.getValue()) + unit + ";");
        }
    }

    private static String renderTypeScript(Map<String, Object> root, String header) {
        Map<String, Object> exported = new LinkedHashMap<>();
        for (String key : List.of(
            "contractVersion", "appearance", "colors", "reader", "spacing", "radii",
            "typography", "components", "accessibility"
        )) {
            exported.put(key, root.get(key));
        }
        String json = JsonOutput.prettyPrint(JsonOutput.toJson(deepSort(exported)));
        return "// " + header + "\n"
            + "export const visualTokens = " + json + " as const;\n\n"
            + "export type GeneratedReaderTheme = keyof typeof visualTokens.reader.themes;\n";
    }

    private static Object deepSort(Object value) {
        if (value instanceof Map<?, ?> map) {
            Map<String, Object> sorted = new TreeMap<>();
            map.forEach((key, nested) -> sorted.put(key.toString(), deepSort(nested)));
            return sorted;
        }
        if (value instanceof List<?> list) {
            List<Object> sorted = new ArrayList<>();
            list.forEach(item -> sorted.add(deepSort(item)));
            return sorted;
        }
        return value;
    }

    private static void validateColors(Map<String, Object> palette, String path, Set<String> except) {
        palette.forEach((key, value) -> {
            if (!except.contains(key)) {
                require(value instanceof String && COLOR.matcher((String) value).matches(),
                    "Invalid color at " + path + "." + key + ": " + value);
            }
        });
    }

    private static void validateNumericMap(Map<String, Object> values, String path, double minimum) {
        values.forEach((key, value) -> require(
            value instanceof Number && ((Number) value).doubleValue() >= minimum,
            "Invalid numeric token at " + path + "." + key
        ));
    }

    private static double contrast(String first, String second) {
        double a = luminance(first);
        double b = luminance(second);
        return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    }

    private static double luminance(String color) {
        double[] channels = new double[3];
        for (int index = 0; index < 3; index++) {
            double channel = Integer.parseInt(color.substring(1 + index * 2, 3 + index * 2), 16) / 255.0;
            channels[index] = channel <= 0.04045
                ? channel / 12.92
                : Math.pow((channel + 0.055) / 1.055, 2.4);
        }
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
    }

    private static Map<String, Object> map(Map<String, Object> root, String key) {
        return asMap(root.get(key), key);
    }

    private static Map<String, Object> asMap(Object value, String path) {
        if (!(value instanceof Map<?, ?> raw)) {
            throw new IllegalStateException("Missing token object: " + path);
        }
        return normalizeMap(raw);
    }

    private static Map<String, Object> normalizeMap(Map<?, ?> raw) {
        Map<String, Object> normalized = new LinkedHashMap<>();
        raw.forEach((key, value) -> normalized.put(
            key.toString(),
            value instanceof Map<?, ?> nested ? normalizeMap(nested) : value
        ));
        return normalized;
    }

    private static Object required(Map<String, Object> values, String key, Class<?> type) {
        Object value = values.get(key);
        if (!type.isInstance(value)) {
            throw new IllegalStateException("Missing " + type.getSimpleName() + " token: " + key);
        }
        return value;
    }

    private static String string(Map<String, Object> values, String key) {
        return (String) required(values, key, String.class);
    }

    private static Number number(Map<String, Object> values, String key) {
        return (Number) required(values, key, Number.class);
    }

    private static void requireExactKeys(Map<String, Object> values, String path, Set<String> expected) {
        if (!values.keySet().equals(expected)) {
            Set<String> missing = new java.util.HashSet<>(expected);
            missing.removeAll(values.keySet());
            Set<String> unknown = new java.util.HashSet<>(values.keySet());
            unknown.removeAll(expected);
            throw new IllegalStateException("Invalid keys at " + path + ". Missing=" + missing + "; unknown=" + unknown);
        }
    }

    private static void require(boolean condition, String message) {
        if (!condition) {
            throw new IllegalStateException(message);
        }
    }

    private static Map<String, Object> sorted(Map<String, Object> values) {
        return new TreeMap<>(values);
    }

    private static String identifier(String value) {
        return Arrays.stream(value.split("[-_.]"))
            .map(part -> Character.toUpperCase(part.charAt(0)) + part.substring(1))
            .reduce("", String::concat);
    }

    private static String property(String value, boolean uppercase) {
        String normalized = value.replace('-', '_').replace('.', '_');
        return uppercase
            ? Character.toUpperCase(normalized.charAt(0)) + normalized.substring(1)
            : normalized;
    }

    private static String kebab(String value) {
        return value.replaceAll("([a-z0-9])([A-Z])", "$1-$2").replace('_', '-').toLowerCase(Locale.ROOT);
    }

    private static String kotlinLiteral(Object value) {
        if (value instanceof Number number) {
            return numberLiteral(number);
        }
        if (value instanceof String text) {
            return "\"" + text + "\"";
        }
        throw new IllegalStateException("Unsupported token value: " + value);
    }

    private static String swiftLiteral(Object value) {
        return kotlinLiteral(value);
    }

    private static String cssLiteral(Object value) {
        if (value instanceof Number number) {
            double numeric = number.doubleValue();
            return numeric % 1.0 == 0.0 ? Long.toString(number.longValue()) : number.toString();
        }
        if (value instanceof String text) {
            return text;
        }
        throw new IllegalStateException("Unsupported CSS token value: " + value);
    }

    private static String numberLiteral(Number value) {
        double numeric = value.doubleValue();
        return numeric % 1.0 == 0.0 ? value.longValue() + ".0" : value.toString();
    }

    private static void line(StringBuilder builder, String text) {
        builder.append(text).append('\n');
    }

    static byte[] readBytes(File file) {
        try {
            return Files.readAllBytes(file.toPath());
        } catch (IOException exception) {
            throw new IllegalStateException("Unable to read " + file, exception);
        }
    }

    static String readText(File file) {
        return new String(readBytes(file), StandardCharsets.UTF_8);
    }

    static void writeIfChanged(File file, String content) {
        byte[] next = content.getBytes(StandardCharsets.UTF_8);
        if (file.isFile() && Arrays.equals(readBytes(file), next)) {
            return;
        }
        try {
            Files.createDirectories(file.toPath().getParent());
            Files.write(file.toPath(), next);
        } catch (IOException exception) {
            throw new IllegalStateException("Unable to write " + file, exception);
        }
    }

    static String sha256(byte[] bytes) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(bytes);
            StringBuilder out = new StringBuilder();
            for (byte value : digest) {
                out.append(String.format("%02x", value));
            }
            return out.toString();
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 unavailable", exception);
        }
    }
}
