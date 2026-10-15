import type { ApplicationRuntime, Workflow } from '@/types';
import { buildContentSuiteWorkflow, CONTENT_SUITE_APPS } from './contentSuite';

export const ARTICLE_CONTENT_SUITE_PRESET = 'article-content-suite';
// Reuse the total preset's application set and branch definitions.
export const ARTICLE_CONTENT_SUITE_APPS = CONTENT_SUITE_APPS;

export function buildArticleContentSuiteWorkflow(applications: ApplicationRuntime[]): Workflow {
  const workflow = buildContentSuiteWorkflow(applications);
  const writerOutput = 'steps.writer.output.artifacts.article_md';
  const articleFile = 'steps.article-illustrations.output.artifacts.article_md';

  const steps = workflow.steps!.filter((step) => step.key !== 'writer').map((step, order) => {
    const automation = step.config.automation as {
      guided_prompt_key: string;
      answers: Record<string, { from?: string; value?: unknown }>;
    } | undefined;
    const consumesArticle = Object.values(automation?.answers || {})
      .some((binding) => binding.from === writerOutput);
    const answers = Object.fromEntries(Object.entries(automation?.answers || {}).map(([key, binding]) => [
      key, binding.from === writerOutput ? { from: 'workflow.input.article' } : binding,
    ]));
    if (consumesArticle) {
      const requirements = String(answers.requirements?.value || '')
        .replace('读取传入的 Markdown 原稿', '读取传入的 Markdown 文章正文')
        .replace('读取传入的文章文件', '读取传入的文章正文')
        .replace('读取原稿生成封面', '读取传入的文章正文生成封面');
      answers.requirements = { value: step.key === 'article-illustrations'
        ? `输入是用户提供的完整文章正文，不是选题或文件路径。先将输入原文原样保存到 article/article.md，保留标题、段落、措辞、数字、链接和 Markdown 标记，不改写、不扩写、不添加创作说明；然后基于这份原稿生成配图及插入锚点。${requirements}`
        : `输入是用户提供的完整文章正文，不是选题或文件路径，直接基于原文执行本节点任务。${requirements}` };
    }
    return {
      ...step, order,
      depends_on: step.depends_on.filter((key) => key !== 'writer'),
      config: {
        ...step.config,
        ...(automation ? { automation: { ...automation, answers } } : {}),
        ...(step.key === 'article-illustrations' ? {
          workflow_artifacts: { ...step.config.workflow_artifacts as object, article_md: 'article/article.md' },
        } : {}),
      },
      input_mapping: step.key === 'article-illustrations-png'
        ? { ...step.input_mapping, article_source: { from: articleFile } }
        : step.input_mapping,
    };
  });

  return {
    ...workflow,
    name: '已有文章 · 排版、图文与短视频',
    description: '输入完整文章，跳过选题与写作，复用总预设的公众号配图排版、图文作品和短视频分支，交付分页与封面 PNG、文案及剪映 builder 脚本。',
    input_schema: {
      type: 'object', properties: {
        article: { type: 'string', title: '文章正文', minLength: 1, 'x-control': 'textarea',
          'x-placeholder': '粘贴完整文章（含标题），支持 Markdown',
          description: '直接使用已有文章，不重新选题或撰写原稿。' },
      }, required: ['article'], additionalProperties: false,
    },
    steps,
    output_mapping: { ...workflow.output_mapping, source_article: { from: articleFile } },
  };
}
