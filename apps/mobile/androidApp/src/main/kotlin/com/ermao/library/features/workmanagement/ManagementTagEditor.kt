package com.ermao.library.features.workmanagement

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.relocation.BringIntoViewRequester
import androidx.compose.foundation.relocation.bringIntoViewRequester
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.ExpandMore
import androidx.compose.material.icons.outlined.ExpandLess
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.InputChip
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.TextFieldValue
import com.ermao.library.R
import com.ermao.library.shared.modules.library.ContentResult
import com.ermao.library.shared.modules.library.LibraryTagOptionPage
import com.ermao.library.shared.modules.library.TagInput
import com.ermao.library.ui.theme.WarmPageThemeValues
import kotlinx.coroutines.delay
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import java.text.NumberFormat

@Composable
internal fun ManagementTagEditor(
    value: String,
    query: TextFieldValue,
    onQueryChange: (TextFieldValue) -> Unit,
    onChange: (String) -> Unit,
    commitInput: (String) -> Unit,
    enabled: Boolean,
    loadOptions: suspend (String) -> ContentResult<LibraryTagOptionPage>,
) {
    val theme = WarmPageThemeValues
    val tags = TagInput.stored(value)
    val keys = tags.map(TagInput::key).toSet()
    var expanded by remember { mutableStateOf(false) }
    var focused by remember { mutableStateOf(false) }
    var result by remember { mutableStateOf<ContentResult<LibraryTagOptionPage>?>(null) }
    var loading by remember { mutableStateOf(false) }
    val inputVisibility = remember { BringIntoViewRequester() }
    val inputFocus = remember { FocusRequester() }
    LaunchedEffect(tags.size, focused, expanded, loading, result) {
        if (focused) {
            // Keep the input and its inline choices visible when chips wrap or the IME resizes the form.
            withFrameNanos { }
            inputVisibility.bringIntoView()
        }
    }
    LaunchedEffect(expanded, query.text, enabled, loadOptions) {
        result = null
        loading = expanded && enabled
        if (loading) {
            delay(180)
            val loaded = loadOptions(query.text)
            currentCoroutineContext().ensureActive()
            result = loaded
            loading = false
        }
    }
    val page = (result as? ContentResult.Content)?.value
    val options = page?.options.orEmpty().filter { TagInput.key(it.value) !in keys }
    val canAdd = TagInput.parse(query.text).any { TagInput.key(it) !in keys } &&
        options.none { TagInput.key(it.value) == TagInput.key(query.text) }
    Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.one)) {
        if (tags.isNotEmpty()) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(theme.spacing.one)) {
                tags.forEach { tag ->
                    val removeLabel = stringResource(R.string.management_tags_remove, tag)
                    InputChip(
                        selected = true,
                        enabled = enabled,
                        onClick = { onChange(tags.filterNot { it == tag }.joinToString("\n")) },
                        label = { Text(tag) },
                        trailingIcon = { Icon(Icons.Outlined.Close, contentDescription = null) },
                        modifier = Modifier.semantics { contentDescription = removeLabel },
                    )
                }
            }
        }
        Column(Modifier.bringIntoViewRequester(inputVisibility), verticalArrangement = Arrangement.spacedBy(theme.spacing.one)) {
            OutlinedTextField(
                value = query,
                onValueChange = {
                    onQueryChange(it)
                    expanded = true
                    if (it.composition == null && TagInput.hasSeparator(it.text)) commitInput(it.text)
                },
                label = { Text(stringResource(R.string.management_tags)) },
                placeholder = { Text(stringResource(R.string.management_tags_placeholder)) },
                enabled = enabled,
                singleLine = true,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { commitInput(query.text) }),
                trailingIcon = {
                    IconButton(enabled = enabled, onClick = {
                        val show = !expanded
                        inputFocus.requestFocus()
                        expanded = show
                    }) {
                        Icon(if (expanded) Icons.Outlined.ExpandLess else Icons.Outlined.ExpandMore,
                            contentDescription = stringResource(if (expanded) R.string.work_collapse else R.string.work_expand))
                    }
                },
                modifier = Modifier.fillMaxWidth().testTag("management-tags-input")
                    .focusRequester(inputFocus)
                    .onFocusChanged {
                        if (focused && !it.isFocused) { commitInput(query.text); expanded = false }
                        focused = it.isFocused
                        if (focused) expanded = true
                    },
            )
            if (expanded && enabled) Surface(shape = RoundedCornerShape(theme.radii.task), color = theme.colors.surface) {
                val status = when {
                    loading -> R.string.management_tags_loading
                    result is ContentResult.Failure -> R.string.management_tags_suggestions_failed
                    page?.indexReady == false -> R.string.management_tags_indexing
                    page?.hasMore == true -> R.string.management_tags_more
                    options.isEmpty() && !canAdd -> R.string.management_tags_empty
                    else -> null
                }
                LazyColumn(Modifier.fillMaxWidth().heightIn(max = theme.components.controls.minimumTouchTarget * 4)
                    .testTag("management-tags-options")) {
                if (status != null) item { Text(stringResource(status), style = theme.typography.caption,
                    color = theme.colors.textSecondary, modifier = Modifier.padding(theme.spacing.two)) }
                if (canAdd) item { DropdownMenuItem(
                    text = { Text(stringResource(R.string.management_tags_add, query.text.trim())) },
                    leadingIcon = { Icon(Icons.Outlined.Add, contentDescription = null) },
                    onClick = { commitInput(query.text) },
                ) }
                items(options, key = { it.value }) { option ->
                    DropdownMenuItem(
                        text = { Text(option.label) },
                        leadingIcon = { Icon(Icons.Outlined.Add, contentDescription = null) },
                        trailingIcon = { Text(NumberFormat.getIntegerInstance().format(option.count)) },
                        onClick = {
                            // A selected stored option is one tag, even if its name contains punctuation.
                            onChange((tags + option.value).joinToString("\n"))
                            onQueryChange(TextFieldValue())
                        },
                    )
                }
                }
            }
        }
    }
}
