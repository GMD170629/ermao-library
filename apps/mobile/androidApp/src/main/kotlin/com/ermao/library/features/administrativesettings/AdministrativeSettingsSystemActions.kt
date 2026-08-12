package com.ermao.library.features.administrativesettings

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContract
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext

private class CreateAdministrativeDocument : ActivityResultContract<AdministrativeExportFile, Uri?>() {
    override fun createIntent(context: Context, input: AdministrativeExportFile): Intent =
        Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = input.mimeType
            putExtra(Intent.EXTRA_TITLE, input.suggestedFileName)
        }

    override fun parseResult(resultCode: Int, intent: Intent?): Uri? =
        if (resultCode == Activity.RESULT_OK) intent?.data else null
}

@Composable
fun rememberAdministrativeSettingsSystemActions(): AdministrativeSettingsSystemActions {
    val context = LocalContext.current
    var pendingExport by remember { mutableStateOf<AdministrativeExportFile?>(null) }
    val createDocument = rememberLauncherForActivityResult(CreateAdministrativeDocument()) { uri ->
        val export = pendingExport
        pendingExport = null
        if (uri != null && export != null) {
            context.contentResolver.openOutputStream(uri, "w")?.use { output -> output.write(export.bytes) }
        }
    }
    return remember(context, createDocument) {
        object : AdministrativeSettingsSystemActions {
            override fun saveExport(file: AdministrativeExportFile) {
                pendingExport = file
                createDocument.launch(file)
            }

            override fun copyText(text: String) {
                context.getSystemService(ClipboardManager::class.java)
                    .setPrimaryClip(ClipData.newPlainText("Ermao Library", text))
            }

            override fun shareText(text: String) {
                val send = Intent(Intent.ACTION_SEND).apply {
                    type = "text/plain"
                    putExtra(Intent.EXTRA_TEXT, text)
                }
                context.startActivity(Intent.createChooser(send, null))
            }
        }
    }
}
