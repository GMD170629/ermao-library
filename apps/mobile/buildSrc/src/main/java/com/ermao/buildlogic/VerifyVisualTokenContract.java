package com.ermao.buildlogic;

import groovy.json.JsonOutput;
import java.io.File;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.gradle.api.DefaultTask;
import org.gradle.api.file.RegularFileProperty;
import org.gradle.api.tasks.InputFile;
import org.gradle.api.tasks.TaskAction;

public abstract class VerifyVisualTokenContract extends DefaultTask {
    @InputFile
    public abstract RegularFileProperty getTokenFile();

    @InputFile
    public abstract RegularFileProperty getSchemaFile();

    @TaskAction
    public void verifyContract() {
        File source = getTokenFile().get().getAsFile();
        Map<String, Object> canonical = VisualTokenGenerator.parse(source);
        VisualTokenGenerator.validate(canonical);
        Map<String, Object> schema = VisualTokenGenerator.parse(getSchemaFile().get().getAsFile());
        require(
            ((Number) object(schema, "properties", "schemaVersion").get("const")).intValue() == 3,
            "Visual token schema must require schemaVersion 3"
        );
        Object requiredThemes = object(schema, "properties", "reader", "properties", "themes").get("required");
        require(
            requiredThemes instanceof List<?> themes
                && Set.copyOf(themes).equals(Set.of("day", "warm", "green", "night", "black")),
            "Visual token schema must require the complete Reader theme set"
        );
        String digest = VisualTokenGenerator.sha256(VisualTokenGenerator.readBytes(source));
        Map<String, String> first = VisualTokenGenerator.outputs(canonical, digest);
        Map<String, String> second = VisualTokenGenerator.outputs(
            VisualTokenGenerator.parseText(JsonOutput.toJson(canonical)),
            digest
        );
        require(first.equals(second), "Design token generation must be deterministic");
        require(first.get("css/visual-tokens.css").contains("[data-reader-theme='black']"),
            "Generated CSS must contain all reader theme selectors");
        require(first.get("kotlin/com/ermao/library/design/GeneratedDesignTokens.kt").contains("object Reader"),
            "Generated Kotlin must expose Reader tokens");
        require(first.get("swift/GeneratedDesignTokens.swift").contains("enum Reader"),
            "Generated Swift must expose Reader tokens");
        require(first.get("kotlin/com/ermao/library/design/GeneratedDesignTokens.kt").contains("object ReaderControls"),
            "Generated Kotlin must expose Reader control geometry");
        require(first.get("css/visual-tokens.css").contains("--visual-component-reader-controls-toc-panel-height: 672px"),
            "Generated CSS must expose Reader control geometry");

        expectInvalid(canonical, copy -> copy.remove("colors"));
        expectInvalid(canonical, copy -> copy.put("unknown", true));
        expectInvalid(canonical, copy -> object(copy, "colors", "app").put("canvas", "invalid"));
        expectInvalid(canonical, copy -> object(copy, "reader", "themes").remove("black"));
        expectInvalid(canonical, copy -> object(copy, "reader", "themes").put(
            "sepia",
            object(copy, "reader", "themes", "warm")
        ));
        expectInvalid(canonical, copy -> object(copy, "spacing").put("space1", -1));
        expectInvalid(canonical, copy -> object(copy, "typography", "readerBody").put("familyRole", "unknown"));
        expectInvalid(canonical, copy -> object(copy, "components", "readerControls").remove("navigationHeight"));
        expectInvalid(canonical, copy -> object(copy, "components", "readerControls").put("compactControlHeight", 32));
    }

    private void expectInvalid(Map<String, Object> source, java.util.function.Consumer<Map<String, Object>> mutate) {
        Map<String, Object> copy = VisualTokenGenerator.parseText(JsonOutput.toJson(source));
        mutate.accept(copy);
        try {
            VisualTokenGenerator.validate(copy);
            throw new IllegalStateException("Invalid visual contract was accepted");
        } catch (IllegalStateException expected) {
            if ("Invalid visual contract was accepted".equals(expected.getMessage())) {
                throw expected;
            }
        }
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> object(Map<String, Object> root, String... path) {
        Map<String, Object> current = root;
        for (String key : path) {
            current = (Map<String, Object>) current.get(key);
        }
        return current;
    }

    private void require(boolean condition, String message) {
        if (!condition) {
            throw new IllegalStateException(message);
        }
    }
}
