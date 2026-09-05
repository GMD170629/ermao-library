package com.ermao.buildlogic;

import java.io.File;
import java.util.List;
import java.util.Map;
import org.gradle.api.DefaultTask;
import org.gradle.api.file.DirectoryProperty;
import org.gradle.api.tasks.InputDirectory;
import org.gradle.api.tasks.TaskAction;

public abstract class VerifyGeneratedDesignTokens extends DefaultTask {
    @InputDirectory
    public abstract DirectoryProperty getGeneratedDirectory();

    @InputDirectory
    public abstract DirectoryProperty getWebOutputDirectory();

    @TaskAction
    public void verify() {
        File generated = getGeneratedDirectory().get().getAsFile();
        List<String> required = List.of(
            "kotlin/com/ermao/library/design/GeneratedDesignTokens.kt",
            "swift/GeneratedDesignTokens.swift",
            "android/values/generated_design_tokens.xml",
            "android/values-night/generated_design_tokens.xml",
            "css/visual-tokens.css",
            "typescript/visual-tokens.ts"
        );
        for (String relative : required) {
            File file = new File(generated, relative);
            if (!file.isFile() || !VisualTokenGenerator.readText(file).endsWith("\n")) {
                throw new IllegalStateException("Invalid generated token file: " + relative);
            }
        }

        File webOutput = getWebOutputDirectory().get().getAsFile();
        Map.of(
            "css/visual-tokens.css", "visual-tokens.css",
            "typescript/visual-tokens.ts", "visual-tokens.ts"
        ).forEach((source, target) -> {
            File expected = new File(generated, source);
            File actual = new File(webOutput, target);
            if (!actual.isFile() || !java.util.Arrays.equals(
                VisualTokenGenerator.readBytes(expected),
                VisualTokenGenerator.readBytes(actual)
            )) {
                throw new IllegalStateException(
                    "Generated Web token drift: " + target + ". Run :syncWebDesignTokens."
                );
            }
        });
    }
}
