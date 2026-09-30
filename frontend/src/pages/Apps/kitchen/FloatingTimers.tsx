import { useState } from "react";
import { Modal } from "antd";
import { Timer } from "@phosphor-icons/react";
import type { KitchenState } from "@/services/kitchenAssistant";
import { TimerPanel } from "./TimerPanel";
import { formatCountdown, kitchenTimers } from "./timers";

export function FloatingTimers(props: {
  state: KitchenState;
  now: number;
  busy: boolean;
  commit: (change: (state: KitchenState) => KitchenState) => Promise<boolean>;
}) {
  const [open, setOpen] = useState(false);
  const timers = kitchenTimers(props.state, props.now);
  const finished = timers.filter((timer) => timer.remaining === 0).length;
  const running = timers.filter((timer) => !timer.paused && timer.remaining > 0);
  const next = running.length ? Math.min(...running.map((timer) => timer.remaining)) : null;
  return (
    <div className="kitchen-timer-dock">
      <button
        className={`kitchen-timer-fab${finished ? " is-finished" : ""}`}
        aria-label={`查看全部计时（${timers.length}个）`}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(true)}
      >
        <span className="kitchen-timer-fab-icon"><Timer size={26} aria-hidden="true" /><small>{timers.length}</small></span>
        <span><strong>{finished ? `${finished} 个计时已到` : "厨房计时"}</strong>
          <span aria-hidden="true">{finished ? "点击查看火候" : next !== null ? `最近 ${formatCountdown(next)}` : "计时已暂停"}</span>
        </span>
      </button>
      <Modal
        title="各道菜的倒计时"
        open={open}
        onCancel={() => setOpen(false)}
        footer={null}
        width={620}
        centered
        rootClassName="kitchen-modal kitchen-timer-modal"
        destroyOnHidden
      >
        <p className="kitchen-muted">{new Set(timers.map((timer) => timer.recipeId)).size} 道菜 · {timers.length} 个计时。关闭面板后，计时仍会继续。</p>
        <TimerPanel {...props} />
        <p className="kitchen-muted">请保持页面打开；关闭页面或系统休眠时，提醒可能无法送达。</p>
      </Modal>
    </div>
  );
}
