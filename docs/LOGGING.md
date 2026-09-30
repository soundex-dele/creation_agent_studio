# 后端处理日志

runserver、执行 coordinator 和其子进程共用控制台日志，默认 `LOG_LEVEL=INFO`，生产环境也保留正常处理日志。输出到 stdout，由终端或部署平台收集；文件轮转由部署平台负责。在 `backend/.env` 修改级别后，重启 runserver 和 worker；`LOG_LEVEL=DEBUG` 可查看被限频的详细进度。

日志包含时间、完整模块名、行号、进程号、线程，以及 `request_id`、`run_id`、`attempt_id`、`organization_id`、`worker_id`。未处于该上下文的字段显示 `-`。HTTP 请求沿用 `X-Request-ID`；同一请求内的业务服务自动携带该 ID，创建任务时的提交日志同时包含 run_id，随后可按 run_id 查找 worker 和重试记录。

业务服务使用 `operation=<函数或阶段> state=started/completed/failed duration_ms=...`。覆盖各应用运行入口、模型调用、知识库检索/索引、工作流、自动化、目录发布、媒体处理、转写、文件管理、账号导入及应用安装等处理边界。HTTP 视图另外输出模块与视图名，因此只包含 CRUD 的模块也能定位到入口。`completed` 表示该服务函数返回；任务是否真正成功，以 `execution.event state=committed type=run.succeeded` 为准。

执行状态事件仅在事务提交后输出，包括入队、运行、重试、输入等待/恢复、取消、失败和成功。进度输出阶段和数值计数，同阶段最多每 5 秒一条 INFO，阶段变化立即输出。模型 token、完整输出、轮询空转和上传分块不会逐条打印 INFO。创建大师等外部应用也经过公共子进程入口和事件接收器。

新加日志不序列化函数参数、返回正文、请求头或查询串。异常保留类型和全部调用栈位置，格式化器省略异常原文、源码行和局部变量，避免供应商异常带出凭据、签名链接、转写正文或模型响应。预期的执行挂起和取消使用 INFO，而非失败日志。

新增服务函数时显式使用 `core.observability.log_operation`（同步函数或协程）；复杂阶段使用 `operation("stage", logger=logger)`。不要装饰生成器，生成器的实际处理发生在迭代阶段；应在其调用方或内部耗时操作上记录。不要给空轮询、心跳、字符/数据块循环添加 INFO 装饰器。额外关联信息使用 `log_context(...)`，作用域退出时会恢复原上下文。

验证：在 backend 目录使用项目虚拟环境运行 `venv\Scripts\python.exe -X utf8 -m pytest core/tests/test_observability.py modules/execution/tests`。Windows 的应用中心测试也应使用 `-X utf8`，避免无显式编码的测试文件读取按 GBK 解码。测试覆盖同步/异步上下文隔离、流式响应、异常调用栈、挂起/取消、子进程终态协议、进度限频、事务回滚以及开发/生产/桌面日志配置。
