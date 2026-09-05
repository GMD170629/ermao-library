package com.ermao.buildlogic;

import java.io.File;
import java.util.Map;
import org.gradle.api.DefaultTask;
import org.gradle.api.file.DirectoryProperty;
import org.gradle.api.tasks.InputDirectory;
import org.gradle.api.tasks.OutputDirectory;
import org.gradle.api.tasks.TaskAction;

public abstract class SyncWebDesignTokens extends DefaultTask {
    @InputDirectory
    public abstract DirectoryProperty getGeneratedDirectory();

    @OutputDirectory
    public abstract DirectoryProperty getWebOutputDirectory();

    @TaskAction
    public void sync() {
        File generated = getGeneratedDirectory().get().getAsFile();
        File webOutput = getWebOutputDirectory().get().getAsFile();
        Map.of(
            "css/visual-tokens.css", "visual-tokens.css",
            "typescript/visual-tokens.ts", "visual-tokens.ts"
        ).forEach((source, target) -> {
            File sourceFile = new File(generated, source);
            if (!sourceFile.isFile()) {
                throw new IllegalStateException("Missing generated token file: " + source);
            }
            VisualTokenGenerator.writeIfChanged(
                new File(webOutput, target),
                VisualTokenGenerator.readText(sourceFile)
            );
        });
    }
}
