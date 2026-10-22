# 实验特性验证（2026-10-20 15:14–15:18）

- 目的：验证“导入入口缺失是不是因为实验特性开关没开”。
- 方法：在 `bin/msosa.properties` 的 `JAVA_ARGS` 追加
  `-Duser.language=en -Duser.country=US -Dmd.sysml2.experimental.features=true`（备份 `/tmp/msosa.properties.bak-151429`），重启 MSOSA；
  用 AX（辅助功能 API）逐项读取菜单，不依赖截图。
- 结果：
  1. 实验中开关**确实生效**：`File > Export To` 出现 3 个 `[Experimental]` 项；`Tools` 出现 `[Experimental] KerML/SysML File Tools`；右键菜单出现 `[Experimental]` 子菜单。
  2. **File 菜单仍然没有 `Import From`**（两个 perspective：`System Engineer SysML v2`、`System Engineer` 都确认过）。
  3. 右键 `package Model > Textual Editor`（`enabled=True`）执行后：**无窗口、无日志记录、JxBrowser CDP `127.0.0.1:9231/json/list` 仍为空**。
  4. 启动日志仍报 `UIKIT_zh.js not found`，说明语言问题不是 Textual Editor 失败的唯一原因。
- 结论：本机 CE 构建没有可用的文本导入路径；不是“开关没开”，也不是“没找到菜单”。
- 回滚：2026-10-20 16:22 已恢复 `bin/msosa.properties` 备份、删除每应用 `AppleLanguages` 设置并重启；启动日志 `user.language=zh`，无实验参数。
