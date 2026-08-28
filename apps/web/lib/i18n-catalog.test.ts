import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import { collectPythonMessages } from '../scripts/generate-i18n-catalog.mjs';

test('Python i18n extraction follows user-visible call boundaries', () => {
  const fixtureRoot = mkdtempSync(join(tmpdir(), 'shuku-i18n-catalog-'));
  try {
    writeFileSync(
      join(fixtureRoot, 'fixture.py'),
      `import re

from app.contracts.http import MessageError
from app.modules.auth.application.user_management import UserAdministrationError
from app.schemas.responses import fail

fail("用户可见错误")
MessageError(message=f"参数值：{value}")
prepare_system_event(message="系统事件")
_prepared_event(message="管理员审计事件")
UserAdministrationError("ADMIN_REQUIRED", "管理员操作失败")
UserAdministrationError(message=f"管理员操作失败：{action}", code="ADMIN_ACTION_FAILED")
UserAdministrationError("DYNAMIC_FAILURE", "动态错误：" + str(error))
_catalog_text(locale, "显式中文", "Explicit English")
health_check_item("database", "error", f"数据库不可用：{error}")
ExampleErrorBody(message="HTTP 错误正文")
LibraryFilterFieldDefinition("title", "书名", "图书元数据", "text", ())
LibraryFilterOption("value", "筛选选项")
ProviderConfigField("key", "配置字段", help="配置帮助")
ProviderManifest(name="提供者名称", description="提供者描述")
suggestion_from_external("title", "value", 0.9, "建议原因")
_finish_without_match(db, task, "FAILED", [], "任务结果消息")

re.compile(r"内部正则 [\\u3400-\\u9fff]")
prompt = "内部提示词，不是 Web 文案"
raise ValueError("普通内部异常")
raise InternalError("INTERNAL", "内部异常说明")
`,
      'utf8'
    );

    const messages = collectPythonMessages(fixtureRoot);
    assert.equal(messages.has('用户可见错误'), true);
    assert.equal(messages.has('参数值：{value0}'), true);
    assert.equal(messages.has('系统事件'), true);
    assert.equal(messages.has('管理员审计事件'), true);
    assert.equal(messages.has('管理员操作失败'), true);
    assert.equal(messages.has('管理员操作失败：{value0}'), true);
    assert.equal(messages.has('显式中文'), true);
    assert.equal(messages.has('数据库不可用：{value0}'), true);
    assert.equal(messages.has('HTTP 错误正文'), true);
    assert.equal(messages.has('书名'), true);
    assert.equal(messages.has('图书元数据'), true);
    assert.equal(messages.has('筛选选项'), true);
    assert.equal(messages.has('配置字段'), true);
    assert.equal(messages.has('配置帮助'), true);
    assert.equal(messages.has('提供者名称'), true);
    assert.equal(messages.has('提供者描述'), true);
    assert.equal(messages.has('建议原因'), true);
    assert.equal(messages.has('任务结果消息'), true);
    assert.equal(messages.has('内部正则 [\\u3400-\\u9fff]'), false);
    assert.equal(messages.has('内部提示词，不是 Web 文案'), false);
    assert.equal(messages.has('普通内部异常'), false);
    assert.equal(messages.has('内部异常说明'), false);
    assert.equal(messages.has('动态错误：'), false);
  } finally {
    rmSync(fixtureRoot, { recursive: true, force: true });
  }
});
