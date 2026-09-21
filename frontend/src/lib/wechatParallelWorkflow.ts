import type { ApplicationRuntime, Workflow, WorkflowStep } from '@/types';

export const WECHAT_PARALLEL_PRESET = 'wechat-parallel';
export const WECHAT_PARALLEL_APPS = [
  'wechat-viral-article', 'article-html-illustrator', 'html-to-png',
  'markdown-to-html', 'html-to-paged-cards', 'html-cover-generator',
] as const;

type Binding = { from: string } | { value: unknown };
const fixed = (value: unknown): Binding => ({ value });
const output = (key: string, field: string): Binding => ({ from: `steps.${key}.output.${field}` });

export function buildWechatParallelWorkflow(applications: ApplicationRuntime[]): Workflow {
  const bySlug = new Map(applications.map((app) => [app.application_slug, app]));
  const missing = WECHAT_PARALLEL_APPS.filter((slug) => !bySlug.has(slug));
  if (missing.length) throw new Error(`缺少工作流应用：${missing.join('、')}`);
  const steps: WorkflowStep[] = [];
  const chat = (
    key: string, name: string, slug: string, dependencies: string[],
    answers: Record<string, Binding>, artifacts: Record<string, unknown>, x: number, y: number,
  ) => {
    const app = bySlug.get(slug)!;
    if (app.kind !== 'chat' || !app.guided_prompts.length) throw new Error(`${app.application_name}未配置引导提示词`);
    const prompt = app.guided_prompts.find((item) => item.key === app.default_config.guided_entry_prompt_key)
      || app.guided_prompts[0];
    steps.push({
      id: `draft-${key}`, key, name, order: steps.length, application: app, application_id: app.id,
      depends_on: dependencies, input_mapping: {}, condition: {}, max_attempts: 1,
      config: {
        automation: { guided_prompt_key: String(prompt.id || prompt.key), answers },
        workflow_artifacts: artifacts, _editor: { position: { x, y } },
      },
    });
  };
  const png = (
    key: string, name: string, dependencies: string[], bindings: Record<string, Binding>,
    width: number, height: number, selector: string, x: number, y: number,
  ) => {
    const app = bySlug.get('html-to-png')!;
    steps.push({
      id: `draft-${key}`, key, name, order: steps.length, application: app, application_id: app.id,
      depends_on: dependencies, condition: {}, max_attempts: 1,
      config: { _editor: { position: { x, y } } },
      input_mapping: {
        ...bindings, strict: fixed(true), width: fixed(width), height: fixed(height),
        selector: fixed(selector), full_page: fixed(!selector), device_scale_factor: fixed(3),
      },
    });
  };

  chat('writer', '写作 · 公众号爆款写作', 'wechat-viral-article', [], {
    source: { from: 'workflow.input.topic' }, task: fixed('full-article'),
    requirements: fixed('将最终选定的标题和完整正文保存到 article/article.md。该文件只包含可发布的 Markdown 文章，不含候选标题、创作说明或发布策略；其他说明另行交付。'),
  }, { article_md: 'article/article.md' }, 40, 180);

  chat('illustrations', '生成配图 · 文章 HTML 配图', 'article-html-illustrator', ['writer'], {
    article: output('writer', 'artifacts.article_md'), aspect: fixed('16:9'),
    requirements: fixed('读取传入的 Markdown 原稿，生成配图但不修改原稿。全部配图保存到 illustrations/，每张使用 .illustration 根元素，固定 960×540 CSS 像素，body 无外边距。另存 illustrations/manifest.json：{"files":["01.html"],"insertions":[{"file":"01.html","after":"逐字复制原稿中唯一的完整段落或独立标题块","alt":"配图说明"}]}。路径相对于清单，每张图恰好一个插入位置，after 必须是原稿中用空行分隔的完整且唯一的块，不得改写、截取或虚构锚点。至少生成一张与文章相关的配图，不导出 PNG。'),
  }, { manifest: 'illustrations/manifest.json' }, 360, 40);
  png('illustrations-png', '配图导出 PNG · 插入正文', ['writer', 'illustrations'], {
    manifest_file: output('illustrations', 'artifacts.manifest'),
    article_source: output('writer', 'artifacts.article_md'),
  }, 960, 540, '.illustration', 680, 40);

  chat('layout', '生成排版 · Markdown 转 HTML', 'markdown-to-html', ['illustrations-png'], {
    source: output('illustrations-png', 'article_md'),
    requirements: fixed('输入文件已经按位置插入 PNG 引用，保留正文和全部图片，不重复插图。按技能执行转换，输出 article/article-with-images.html，与输入 Markdown 同目录；确保图片相对路径仍有效。'),
  }, { html: 'article/article-with-images.html' }, 1000, 40);

  chat('paginate', '排版切片 · HTML 分页图文', 'html-to-paged-cards', ['layout'], {
    source: output('layout', 'artifacts.html'), aspect: fixed('3:4'),
    size_policy: fixed('extend'), export_format: fixed('html'),
    requirements: fixed('仅生成分页 HTML，不导出 PNG。沿用技能新建唯一输出目录的规则，保留所有原始图片路径。运行成功后创建 pages/manifest.json，格式 {"files":["相对于清单的第1页HTML路径","第2页HTML路径"]}，严格按阅读顺序列出全部正文页，排除 index.html 和原文。将本次实际 report.json 复制到 pages/report.json。只有报告 status=complete 且图片均正常加载后交付。不要将页面复制到新位置造成相对图片路径失效。'),
  }, { manifest: 'pages/manifest.json', report: { path: 'pages/report.json', status: 'complete' } }, 1320, 40);
  png('pages-png', '正文页面导出 PNG', ['paginate'], {
    manifest_file: output('paginate', 'artifacts.manifest'),
  }, 360, 480, '', 1640, 40);

  chat('cover', '生成封面 · HTML 封面生成器', 'html-cover-generator', ['writer'], {
    source: output('writer', 'artifacts.article_md'), aspect: fixed('2.35:1'),
    requirements: fixed('读取原稿生成封面，保存为 cover/cover.html。使用 .cover 根元素，1080×460 CSS 像素，body 无外边距。不改动正文或配图目录，不导出 PNG。'),
  }, { html: 'cover/cover.html' }, 360, 360);
  png('cover-png', '封面导出 PNG', ['cover'], {
    html_file: output('cover', 'artifacts.html'),
  }, 1080, 460, '.cover', 680, 360);

  return {
    id: '', name: '公众号图文与封面并行制作',
    description: '输入选题后写作；正文支线完成配图、PNG 插图、排版、分页和导出，封面支线同时生成封面并导出 PNG。',
    icon: '🔀', execution_mode: 'automatic', is_public: false,
    input_schema: {
      type: 'object', properties: {
        topic: { type: 'string', title: '选题与素材', minLength: 1, 'x-control': 'textarea',
          'x-placeholder': '输入选题、目标读者、素材与写作要求' },
      }, required: ['topic'], additionalProperties: false,
    },
    output_mapping: {
      article: output('illustrations-png', 'article_md') as { from: string },
      pages: output('pages-png', 'files') as { from: string },
      cover: output('cover-png', 'files') as { from: string },
    },
    steps,
  };
}

export function workflowStepOutputOptions(step: WorkflowStep) {
  const prefix = `steps.${step.key}.output.`;
  const fields = [{ value: `${prefix}result`, label: '文本结果' }];
  if (step.application.application_slug === 'html-to-png') {
    fields.push({ value: `${prefix}files`, label: 'PNG 文件列表' });
    if (step.input_mapping?.article_source) fields.push({ value: `${prefix}article_md`, label: '已插图 Markdown 文件' });
  }
  Object.keys(step.config?.workflow_artifacts || {}).forEach((key) => {
    fields.push({ value: `${prefix}artifacts.${key}`, label: `文件 · ${key}` });
  });
  return fields;
}
