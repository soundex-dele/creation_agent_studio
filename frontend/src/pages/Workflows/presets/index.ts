import type { ApplicationRuntime, Workflow } from '@/types';
import {
  buildWechatParallelWorkflow, WECHAT_PARALLEL_APPS, WECHAT_PARALLEL_PRESET,
} from '@/lib/wechatParallelWorkflow';
import {
  buildImageTextParallelWorkflow, IMAGE_TEXT_PARALLEL_APPS, IMAGE_TEXT_PARALLEL_PRESET,
} from './imageTextParallel';
import {
  buildShortVideoParallelWorkflow, SHORT_VIDEO_PARALLEL_APPS, SHORT_VIDEO_PARALLEL_PRESET,
} from './shortVideoParallel';
import { buildContentSuiteWorkflow, CONTENT_SUITE_APPS, CONTENT_SUITE_PRESET } from './contentSuite';

interface WorkflowPreset {
  id: string;
  name: string;
  description: string;
  applicationSlugs: readonly string[];
  build: (applications: ApplicationRuntime[]) => Workflow;
  loadError: string;
}

// The preset folder and editor share this registry. Register new presets here.
export const workflowPresets: readonly WorkflowPreset[] = [
  {
    id: WECHAT_PARALLEL_PRESET,
    name: '公众号图文并行预设',
    description: '串联文章写作、正文配图、封面、排版和分页，并行生成配图与封面，最终导出 PNG。',
    applicationSlugs: WECHAT_PARALLEL_APPS,
    build: buildWechatParallelWorkflow,
    loadError: '并行预设加载失败，请确认写作、HTML 配图、封面、排版、分页和 PNG 导出应用均已安装并可访问。',
  },
  {
    id: IMAGE_TEXT_PARALLEL_PRESET,
    name: '公众号写作转图文预设',
    description: '人工输入选题 → 公众号写作 → 图文文案，再分叉生成正文配图与封面，两条分支分别导出 PNG。',
    applicationSlugs: IMAGE_TEXT_PARALLEL_APPS,
    build: buildImageTextParallelWorkflow,
    loadError: '图文预设加载失败，请确认公众号爆款写作、图文文案、文章 HTML 配图、HTML 封面生成器和 HTML 批量转 PNG 均已安装并可访问。',
  },
  {
    id: SHORT_VIDEO_PARALLEL_PRESET,
    name: '公众号写作转短视频预设',
    description: '人工输入选题 → 公众号写作 → 短视频文案，再分叉生成 builder 脚本，以及 HTML 视频封面并导出 PNG。',
    applicationSlugs: SHORT_VIDEO_PARALLEL_APPS,
    build: buildShortVideoParallelWorkflow,
    loadError: '短视频预设加载失败，请确认公众号爆款写作、短视频文案、文案转剪映、HTML 封面生成器和 HTML 批量转 PNG 均已安装并可访问。',
  },
  {
    id: CONTENT_SUITE_PRESET,
    name: '公众号图文与短视频总预设',
    description: '输入一次选题，共用公众号原稿，并行完成公众号排版图文、图文作品和短视频 builder 脚本，汇总三条支线的封面与输出。',
    applicationSlugs: CONTENT_SUITE_APPS,
    build: buildContentSuiteWorkflow,
    loadError: '总预设加载失败，请确认公众号写作、图文文案、短视频文案、文章 HTML 配图、HTML 封面、Markdown 转 HTML、HTML 分页图文、HTML 批量转 PNG 和文案转剪映应用均已安装并可访问。',
  },
];

export const findWorkflowPreset = (id: string) => workflowPresets.find((preset) => preset.id === id);
