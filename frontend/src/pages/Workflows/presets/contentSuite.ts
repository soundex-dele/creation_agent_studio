import type { ApplicationRuntime, Workflow, WorkflowStep } from '@/types';
import { workflowNodePosition } from '@/lib/workflowGraph';
import { buildWechatParallelWorkflow, WECHAT_PARALLEL_APPS } from '@/lib/wechatParallelWorkflow';
import { buildImageTextParallelWorkflow, IMAGE_TEXT_PARALLEL_APPS } from './imageTextParallel';
import { buildShortVideoParallelWorkflow, SHORT_VIDEO_PARALLEL_APPS } from './shortVideoParallel';

export const CONTENT_SUITE_PRESET = 'wechat-content-suite';
export const CONTENT_SUITE_APPS = [...new Set([
  ...WECHAT_PARALLEL_APPS, ...IMAGE_TEXT_PARALLEL_APPS, ...SHORT_VIDEO_PARALLEL_APPS,
])];

interface Branch {
  workflow: Workflow;
  prefix: string;
  label: string;
  folder?: string;
  offsetY: number;
  outputs: Record<string, string>;
}

function scopeBranch({ workflow, prefix, label, folder, offsetY, outputs }: Branch) {
  const keys = new Map(workflow.steps!.map((step) => [
    step.key, step.key === 'writer' ? 'writer' : `${prefix}-${step.key}`,
  ]));
  const rewriteString = (value: string) => {
    const references = value.replace(/steps\.([^.]+)\.output(?=\.|$)/g, (match, key: string) => (
      keys.has(key) ? `steps.${keys.get(key)}.output` : match
    ));
    // These builders declare workspace-relative paths in both artifact contracts
    // and prompt text. Rewrite both together, leaving shared article inputs alone.
    return folder ? references.replace(/\b(copy|illustrations|cover|jianying)\//g, `${folder}/$1/`) : references;
  };
  const rewrite = <T,>(value: T): T => {
    if (typeof value === 'string') return rewriteString(value) as T;
    if (Array.isArray(value)) return value.map((item) => rewrite(item)) as T;
    if (value && typeof value === 'object') {
      return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, rewrite(item)])) as T;
    }
    return value;
  };
  const steps = workflow.steps!.filter((step) => step.key !== 'writer').map((step): WorkflowStep => {
    const key = keys.get(step.key)!;
    const config = rewrite(step.config);
    const position = workflowNodePosition(step) || { x: 360, y: 40 };
    const condition = rewrite(step.condition);
    if (condition.source === 'dependency' && typeof condition.step === 'string') {
      condition.step = keys.get(condition.step) || condition.step;
    }
    return {
      ...step, id: `draft-${key}`, key, name: `${label} · ${step.name}`,
      depends_on: step.depends_on.map((dependency) => keys.get(dependency)!),
      config: { ...config, _editor: { position: { x: position.x, y: position.y + offsetY } } },
      input_mapping: rewrite(step.input_mapping), condition,
    };
  });
  const outputMapping = Object.fromEntries(Object.entries(outputs).map(([source, target]) => [
    target, rewrite(workflow.output_mapping![source]),
  ]));
  return { steps, outputMapping };
}

export function buildContentSuiteWorkflow(applications: ApplicationRuntime[]): Workflow {
  const article = buildWechatParallelWorkflow(applications);
  const imageText = buildImageTextParallelWorkflow(applications);
  const shortVideo = buildShortVideoParallelWorkflow(applications);
  const branches = [
    scopeBranch({ workflow: article, prefix: 'article', label: '公众号', offsetY: 0,
      outputs: { article: 'article', pages: 'article_pages', cover: 'article_cover' } }),
    scopeBranch({ workflow: imageText, prefix: 'image', label: '图文', folder: 'image-text', offsetY: 520,
      outputs: { copy: 'image_text_copy', illustrations: 'image_text_images', cover: 'image_text_cover' } }),
    scopeBranch({ workflow: shortVideo, prefix: 'video', label: '短视频', folder: 'short-video', offsetY: 1040,
      outputs: { copy: 'video_copy', narration: 'video_narration', jianying: 'video_jianying',
        cover: 'video_cover' } }),
  ];
  const writer = article.steps!.find((step) => step.key === 'writer')!;
  return {
    ...article,
    name: '一稿三用 · 公众号、图文与短视频',
    description: '输入一次选题，共用公众号原稿；并行完成公众号配图排版与分页 PNG、图文文案及配图封面 PNG、短视频文案及 builder 脚本和封面 PNG。',
    steps: [
      { ...writer, name: '写作 · 三条支线共用公众号原稿',
        config: { ...writer.config, _editor: { position: { x: 40, y: 720 } } } },
      ...branches.flatMap((branch) => branch.steps),
    ].map((step, order) => ({ ...step, order })),
    output_mapping: {
      source_article: { from: 'steps.writer.output.artifacts.article_md' },
      ...branches.reduce((mapping, branch) => ({ ...mapping, ...branch.outputMapping }), {}),
    },
  };
}
