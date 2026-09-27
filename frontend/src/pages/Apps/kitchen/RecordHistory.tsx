import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Empty,
  Input,
  Modal,
  Pagination,
  Popconfirm,
  Spin,
} from "antd";
import type {
  CookingRecord,
  kitchenApi,
  RecordPage,
} from "@/services/kitchenAssistant";
import { entryError } from "@/services/ideasTodos";
import { amountText } from "./domain";
import { RecordEditor } from "./Editors";

export function RecordHistory({
  service,
  revision,
  onChanged,
  onRepeat,
}: {
  onRepeat?: (record: CookingRecord) => void;
  service: ReturnType<typeof kitchenApi>;
  revision: number;
  onChanged: () => void;
}) {
  const [filters, setFilters] = useState({ search: "", start: "", end: "" });
  const [detail, setDetail] = useState<CookingRecord>();
  const [page, setPage] = useState(1);
  const [reload, setReload] = useState(0);
  const [result, setResult] = useState<RecordPage>({ count: 0, results: [] });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [editor, setEditor] = useState<CookingRecord>();
  useEffect(() => {
    const controller = new AbortController();
    setBusy(true);
    setError("");
    service
      .history(page, controller.signal, filters)
      .then((result) => {
        if (!controller.signal.aborted) setResult(result);
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          if (
            (err as { response?: { status: number } }).response?.status ===
              404 &&
            page > 1
          )
            setPage(page - 1);
          else setError(entryError(err));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false);
      });
    return () => controller.abort();
  }, [service, page, reload, revision, filters]);
  async function edit(item: CookingRecord) {
    setBusy(true);
    setError("");
    try {
      await service.editRecord(item);
      setReload((v) => v + 1);
      onChanged();
      return true;
    } catch (err) {
      setError(entryError(err));
      return false;
    } finally {
      setBusy(false);
    }
  }
  return (
    <section>
      <div className="kitchen-section-heading">
        <h2>下厨记录 · {result.count}</h2>
      </div>
      <div className="kitchen-toolbar">
        <Input.Search
          aria-label="搜索下厨记录"
          placeholder="菜名"
          allowClear
          onSearch={(value) => {
            setPage(1);
            setFilters({ ...filters, search: value });
          }}
        />
        <label>
          从
          <Input
            type="date"
            value={filters.start}
            onChange={(e) => {
              setPage(1);
              setFilters({ ...filters, start: e.target.value });
            }}
          />
        </label>
        <label>
          至
          <Input
            type="date"
            value={filters.end}
            onChange={(e) => {
              setPage(1);
              setFilters({ ...filters, end: e.target.value });
            }}
          />
        </label>
      </div>
      {error && (
        <Alert
          type="error"
          message={error}
          action={
            <Button onClick={() => setReload((v) => v + 1)}>
              重新加载记录
            </Button>
          }
        />
      )}
      {busy && <Spin />}
      {result.results.map((item) => (
        <article className="kitchen-card kitchen-record" key={item.id}>
          <div>
            <h3>{item.recipeNames.join("、")}</h3>
            <p>
              {new Date(item.finishedAt).toLocaleString("zh-CN")} ·{" "}
              {item.servings} 人 ·{" "}
              {item.rating ? `${item.rating} 分` : "未评分"}
            </p>
            {item.tasteNotes && <p>{item.tasteNotes}</p>}
          </div>
          <div className="kitchen-actions">
            <Button onClick={() => setDetail(item)}>查看当时菜谱</Button>
            {onRepeat && (
              <Button disabled={busy} onClick={() => onRepeat(item)}>
                再做一次
              </Button>
            )}
            <Button disabled={busy} onClick={() => setEditor(item)}>
              记录心得
            </Button>
            <Popconfirm
              title="删除这条下厨记录？"
              onConfirm={async () => {
                setBusy(true);
                setError("");
                try {
                  await service.deleteRecord(item);
                  if (result.results.length === 1 && page > 1)
                    setPage(page - 1);
                  else setReload((v) => v + 1);
                  onChanged();
                } catch (err) {
                  setError(entryError(err));
                } finally {
                  setBusy(false);
                }
              }}
            >
              <Button disabled={busy} danger>
                删除
              </Button>
            </Popconfirm>
          </div>
        </article>
      ))}
      {!busy && !result.count && (
        <Empty description="还没有下厨记录，开始做第一顿饭吧。" />
      )}
      {result.count > 20 && (
        <Pagination
          current={page}
          total={result.count}
          pageSize={20}
          showSizeChanger={false}
          disabled={busy}
          onChange={setPage}
        />
      )}
      {detail && (
        <Modal
          open
          title="当时的菜谱"
          footer={null}
          onCancel={() => setDetail(undefined)}
        >
          <p>
            {detail.servings} 人 ·{" "}
            {new Date(detail.finishedAt).toLocaleString("zh-CN")}
          </p>
          {detail.recipeSnapshots?.length ? (
            detail.recipeSnapshots.map((r) => (
              <section key={r.id}>
                <h3>{r.name}</h3>
                {r.ingredients.map((i) => (
                  <p key={i.id}>
                    {i.name}{" "}
                    {amountText((i.amount * detail.servings) / r.servings)}{" "}
                    {i.unit}
                  </p>
                ))}
                {r.steps.map((step, index) => (
                  <p key={step.id}>
                    {index + 1}. {step.description}
                  </p>
                ))}
              </section>
            ))
          ) : (
            <p>这是旧版记录，未保存菜谱快照。</p>
          )}
        </Modal>
      )}
      {editor && (
        <RecordEditor
          item={editor}
          onClose={() => setEditor(undefined)}
          onSave={edit}
        />
      )}
    </section>
  );
}
