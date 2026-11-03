# NAS 导入压测 / NAS import benchmark

`benchmark_nas_import.py` 测量现有书库及指定扫描任务，不造数、不创建账号、不修复数据。
Set `NAS_PERF_EMAIL` and `NAS_PERF_PASSWORD` in the process environment for an existing test account.
Do not put credentials in command arguments or committed files.

```sh
python scripts/benchmark_nas_import.py \
  --base-url http://192.168.50.4:3002 \
  --library-id LIBRARY_ID --scan-id EXISTING_SCAN_ID \
  --target-books 100000 --generated-books 100000 \
  --output /path/to/evidence/new-run \
  --container ermao-perf-20261031
```

生成数是调用者提供的已核实数量；脚本通过正式 API 分页检查目标书库的发现数、成功导入数。
成功导入要求存在 READY 资源、没有 pending/failed/failedFiles，且 metadataState 为 COMPLETED。
Generated count is supplied by the caller; discovered and successful counts are independently checked through library-scoped public APIs. Historical successful task totals are never substituted for successful books.

初始扫描失败或取消立即结束验收，不等待排队任务排空，不提交新扫描。
正常流程依次测量导入期四客户端、等待导入完成并验证数量、稳态一/四/八客户端，再通过正式 API 提交一次重扫并测量四客户端，等待重扫完成后再次验收。
The script writes reader progress during load and submits one rescan only after the initial import passes acceptance. It does not stop the application worker when the benchmark fails.

默认每阶段 120 秒、状态检查间隔 15 秒，可用 `--seconds` / `--poll-seconds` 调整。
失败状态在下一次检查时发现；已发出的 HTTP 请求仍受 90 秒请求超时约束，随后退出。
`--container` 可选，要求运行机器能以 `sudo -n docker stats` 读取该容器；不提供时仍采集可用的 `/proc` 资源信息。
An existing nonempty output directory gets a new timestamped child directory, preserving earlier evidence.

退出码 0 表示所有阶段、数量与 HTTP 检查通过；失败退出码为 1。
`summary.json` 和 `report.md` 在成功、失败和用户中断时均生成；`failure.json` / `errors.jsonl` 保存完整原因及 HTTP 错误响应，`requests.jsonl` 保存原始延迟，`timeline.jsonl` / `resources.jsonl` 保存应用及资源快照。
Historical and newly failed tasks are reported separately. Existing failed tasks do not by themselves invalidate a newly successful target scan.

当前 NAS 语料的 12,000 份 PDF 复用错误 xref 模板。Range 请求成功不能证明 PDF 解析或阅读通过；本工具不验收 UI、解码、播放或冷缓存性能。
The existing corpus has malformed PDF fixtures. HTTP results are not rendering, decoding, playback or cold-cache acceptance.

部署验收必须核对所测应用源码版本；本脚本不会构建、部署或临时修改 NAS 服务。
Verify deployed source parity before interpreting results. This script does not build, deploy or patch the NAS application.
