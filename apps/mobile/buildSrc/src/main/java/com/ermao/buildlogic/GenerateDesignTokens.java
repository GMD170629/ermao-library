package com.ermao.buildlogic;

import java.io.File;
import java.util.Map;
import org.gradle.api.DefaultTask;
import org.gradle.api.file.DirectoryProperty;
import org.gradle.api.file.RegularFileProperty;
import org.gradle.api.tasks.InputFile;
import org.gradle.api.tasks.OutputDirectory;
import org.gradle.api.tasks.TaskAction;

public abstract class GenerateDesignTokens extends DefaultTask {
    @InputFile
    public abstract RegularFileProperty getTokenFile();

    @InputFile
    public abstract RegularFileProperty getSchemaFile();

    @OutputDirectory
    public abstract DirectoryProperty getOutputDirectory();

    @TaskAction
    public void generate() {
        File source = getTokenFile().get().getAsFile();
        Map<String, Object> contract = VisualTokenGenerator.parse(source);
        VisualTokenGenerator.validate(contract);
        if (!getSchemaFile().get().getAsFile().isFile()) {
            throw new IllegalStateException("Missing visual token schema");
        }
        String digest = VisualTokenGenerator.sha256(VisualTokenGenerator.readBytes(source));
        File root = getOutputDirectory().get().getAsFile();
        VisualTokenGenerator.outputs(contract, digest).forEach(
            (relative, content) -> VisualTokenGenerator.writeIfChanged(new File(root, relative), content)
        );
    }
}
