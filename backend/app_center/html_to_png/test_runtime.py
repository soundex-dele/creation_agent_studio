from io import StringIO

import pytest

from app_center.html_to_png import runtime


class _Sink:
    def __init__(self):
        self.events = []
        self.cancelled = False

    def emit(self, event_type, payload):
        self.events.append((event_type, payload))


class _Input:
    def __init__(self):
        self.value = ""

    def write(self, value):
        self.value += value

    def close(self):
        pass


class _Process:
    def __init__(self, lines, return_code=0, stderr=""):
        self.stdin = _Input()
        self.stdout = iter(lines)
        self.stderr = StringIO(stderr)
        self.return_code = return_code
        self.terminated = False

    def wait(self, timeout=None):
        return self.return_code

    def terminate(self):
        self.terminated = True


def test_directories_are_deduplicated_and_html_files_are_sorted(tmp_path):
    selected = tmp_path / "selected"
    selected.mkdir()
    (selected / "B.HTML").write_text("", encoding="utf-8")
    (selected / "a.html").write_text("", encoding="utf-8")
    (selected / "ignore.txt").write_text("", encoding="utf-8")

    directories = runtime._directories(
        {"directories": [str(selected), str(selected)]},
        [tmp_path.resolve()],
    )

    assert directories == [selected.resolve()]
    assert [item.name for item in runtime._html_files(directories)] == [
        "a.html",
        "B.HTML",
    ]


def test_rejects_directory_outside_runtime_roots(tmp_path):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()

    with pytest.raises(PermissionError, match="不在允许的运行范围内"):
        runtime._directories(
            {"directories": [str(outside)]},
            [allowed.resolve()],
        )


def test_accepts_any_existing_directory_when_access_is_unrestricted(tmp_path):
    selected = tmp_path / "selected"
    selected.mkdir()

    assert runtime._directories(
        {"directories": [str(selected)]},
        [],
        allow_all_paths=True,
    ) == [selected.resolve()]


def test_executor_reports_success_and_partial_failure(monkeypatch, tmp_path):
    selected = tmp_path / "selected"
    modules = tmp_path / "node_modules"
    (modules / "playwright").mkdir(parents=True)
    selected.mkdir()
    first = selected / "a.html"
    second = selected / "b.html"
    first.write_text("", encoding="utf-8")
    second.write_text("", encoding="utf-8")
    process = _Process([
        '{"type":"started","index":1,"input":"a.html"}\n',
        f'{{"type":"completed","index":1,"input":"a.html",'
        f'"output":{runtime.json.dumps(str(first.with_suffix(".png")))}}}\n',
        '{"type":"started","index":2,"input":"b.html"}\n',
        '{"type":"failed","index":2,"input":"b.html","error":"bad page"}\n',
        '{"type":"summary","succeeded":1,"total":2}\n',
    ])
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "node")
    monkeypatch.setattr(runtime, "_playwright_module_path", lambda _config: modules)
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *_args, **_kwargs: process)
    sink = _Sink()

    result = runtime.execute_html_to_png(
        {
            "allowed_roots": [str(tmp_path)],
            "input": {"directories": [str(selected)]},
        },
        sink,
    )

    assert result["total"] == 2
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["files"] == [str(first.with_suffix(".png"))]
    assert [event for event, _payload in sink.events].count("progress.updated") == 2
    submitted = runtime.json.loads(process.stdin.value)
    assert [item["input"] for item in submitted["files"]] == [str(first), str(second)]
    assert submitted["width"] == 1283
    assert submitted["height"] == 383


def test_executor_returns_empty_result_without_starting_node(tmp_path):
    selected = tmp_path / "selected"
    selected.mkdir()

    result = runtime.execute_html_to_png(
        {
            "allowed_roots": [str(tmp_path)],
            "input": {"directories": [str(selected)]},
        },
        _Sink(),
    )

    assert result["total"] == 0
    assert result["message"] == "所选目录中没有 HTML 文件。"


def workflow_fixture(tmp_path):
    folder = tmp_path / "illustrations"
    folder.mkdir()
    (folder / "01.html").write_text("<div>配图</div>", encoding="utf-8")
    (folder / "index.html").write_text("不应导出预览索引", encoding="utf-8")
    source = tmp_path / "article.md"
    source.write_text("# 标题\n\n第一段正文。\n\n第二段正文。", encoding="utf-8")
    manifest = folder / "manifest.json"
    manifest.write_text(runtime.json.dumps({
        "files": ["01.html"],
        "insertions": [{"file": "01.html", "after": "第一段正文。", "alt": "说明"}],
    }), encoding="utf-8")
    return {
        "working_directory": str(tmp_path), "manifest_file": str(manifest),
        "article_source": str(source), "strict": True,
    }, folder


def test_manifest_exports_only_listed_files_and_inserts_png_without_changing_copy(monkeypatch, tmp_path):
    config, folder = workflow_fixture(tmp_path)
    png = folder / "01.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"fixture")
    process = _Process([runtime.json.dumps({"type": "completed", "index": 1, "output": str(png)})])
    monkeypatch.setattr(runtime.shutil, "which", lambda _: "node")
    monkeypatch.setattr(runtime, "_playwright_module_path", lambda _: tmp_path)
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *a, **kw: process)
    sink = _Sink()
    result = runtime.execute_html_to_png({"input": config, "allowed_roots": [str(tmp_path)]}, sink)
    assert result["files"] == [str(png)]
    assert runtime.json.loads(process.stdin.value)["files"] == [{
        "input": str(folder / "01.html"), "output": str(png),
    }]
    assert (tmp_path / "article-with-images.md").read_text(encoding="utf-8") == (
        "# 标题\n\n第一段正文。\n\n![说明](illustrations/01.png)\n\n第二段正文。"
    )
    assert (tmp_path / "article.md").read_text(encoding="utf-8") == "# 标题\n\n第一段正文。\n\n第二段正文。"
    assert result["article_md"] == str(tmp_path / "article-with-images.md")


@pytest.mark.parametrize("anchor", ["不存在的段落", "第一段", ""])
def test_invalid_insertion_anchors_stop_without_writing_a_partial_article(tmp_path, anchor):
    config, folder = workflow_fixture(tmp_path)
    manifest_path, manifest, files = runtime.load_manifest(config)
    manifest["insertions"][0]["after"] = anchor
    with pytest.raises(ValueError, match="锚点"):
        runtime.insert_illustrations(config, manifest_path, manifest, files, [str(folder / "01.png")])
    assert not (tmp_path / "article-with-images.md").exists()


def test_manifest_cannot_escape_workspace_even_with_unrestricted_executor(tmp_path):
    config, folder = workflow_fixture(tmp_path)
    (folder / "manifest.json").write_text(runtime.json.dumps({"files": ["../../escape.html"]}))
    with pytest.raises(ValueError, match="工作目录内"):
        runtime.load_manifest(config)


def test_strict_export_stops_on_partial_failure(monkeypatch, tmp_path):
    config, folder = workflow_fixture(tmp_path)
    process = _Process([runtime.json.dumps({"type": "failed", "index": 1, "error": "missing image"})])
    monkeypatch.setattr(runtime.shutil, "which", lambda _: "node")
    monkeypatch.setattr(runtime, "_playwright_module_path", lambda _: tmp_path)
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *a, **kw: process)
    with pytest.raises(RuntimeError, match="未全部成功"):
        runtime.execute_html_to_png({"input": config, "allowed_roots": [str(tmp_path)]}, _Sink())
    assert not (tmp_path / "article-with-images.md").exists()
