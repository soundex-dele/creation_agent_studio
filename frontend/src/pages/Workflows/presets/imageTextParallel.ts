import type { ApplicationRuntime, Workflow, WorkflowStep } from '@/types';

export const IMAGE_TEXT_PARALLEL_PRESET = 'wechat-image-text-parallel';
export const IMAGE_TEXT_PARALLEL_APPS = [
  'wechat-viral-article', 'write-image-text-copy', 'article-html-illustrator',
  'html-cover-generator', 'html-to-png',
] as const;

type Binding = { from: string } | { value: unknown };
const fixed = (value: unknown): Binding => ({ value });
const output = (key: string, field: string) => ({ from: `steps.${key}.output.${field}` });

export function buildImageTextParallelWorkflow(applications: ApplicationRuntime[]): Workflow {
  const bySlug = new Map(applications.map((app) => [app.application_slug, app]));
  const missing = IMAGE_TEXT_PARALLEL_APPS.filter((slug) => !bySlug.has(slug));
  if (missing.length) throw new Error(`缺少工作流应用：${missing.join('、')}`);
  const steps: WorkflowStep[] = [];
  const chat = (
    key: string, name: string, slug: string, dependencies: string[],
    answers: Record<string, Binding>, artifacts: Record<string, string>, x: number, y: number,
  ) => {
    const app = bySlug.get(slug)!;
    if (app.kind !== 'chat' || !app.guided_prompts.length) {
      throw new Error(`${app.application_name}未配置引导提示词`);
    }
    const preferred = app.default_config.guided_entry_prompt_key;
    const prompt = app.guided_prompts.find((item) => item.key === preferred || String(item.id) === preferred)
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
    key: string, name: string, dependency: string, bindings: Record<string, Binding>,
    width: number, height: number, selector: string, x: number, y: number,
  ) => {
    const app = bySlug.get('html-to-png')!;
    if (app.kind !== 'task') throw new Error('HTML 批量转 PNG 必须是任务应用');
    steps.push({
      id: `draft-${key}`, key, name, order: steps.length, application: app, application_id: app.id,
      depends_on: [dependency], condition: {}, max_attempts: 1,
      config: { _editor: { position: { x, y } } },
      input_mapping: {
        ...bindings, strict: fixed(true), width: fixed(width), height: fixed(height),
        selector: fixed(selector), full_page: fixed(false), device_scale_factor: fixed(3),
      },
    });
  };

  chat('writer', '写作 · 公众号爆款写作', 'wechat-viral-article', [], {
    source: { from: 'workflow.input.topic' }, task: fixed('full-article'),
    requirements: fixed('根据选题完成文章，将最终选定的标题和完整正文保存到 article/article.md。文件只包含可发布的 Markdown 文章，不含候选标题、创作说明或发布策略；其他说明另行交付。'),
  }, { article_md: 'article/article.md' }, 40, 200);

  chat('copy', '生成文案 · 图文文案', 'write-image-text-copy', ['writer'], {
    source: output('writer', 'artifacts.article_md'), task: fixed('article-to-pages'), platform: fixed('wechat'),
    pages: fixed('按文章内容组织约 6 页，P1 为封面，P2 起为正文图文页；内容优先，不为凑页重复。'),
    requirements: fixed('读取传入的文章文件，改编为完整图文文案，保存到 copy/image-text.md。包含唯一的推荐作品标题、P1 封面标题与可选副标题、从 P2 开始按顺序编号的每页标题及上图正文、发布配文。上图文字保留实际换行，画面建议与文案分开标注。供两个后续应用分别生成正文配图和封面；统一主题、语气与视觉建议，不生成 HTML 或 PNG，不修改文章原稿。'),
  }, { copy_md: 'copy/image-text.md' }, 360, 200);

  chat('illustrations', '生成配图 · 文章 HTML 配图', 'article-html-illustrator', ['copy'], {
    article: output('copy', 'artifacts.copy_md'), aspect: fixed('16:9'), density: fixed('per-section'),
    requirements: fixed('读取图文文案文件，按 P2 起的正文图文页逐页生成 HTML 配图，每个正文页对应一张图，保留页序及上图文字，不遗漏、不合并页面；不要生成 P1 封面，不把发布配文或画面建议当作上图正文。遵循文案中的统一视觉建议。全部配图保存到 illustrations/，每张使用 .illustration 根元素，固定 960×540 CSS 像素，body 无外边距；调整排版确保文字完整可见。另存 illustrations/manifest.json，格式 {"files":["02.html","03.html"]}，相对于清单按正文页序列出本次全部 HTML，不包含索引或旧文件。至少生成一张配图，不导出 PNG，不改动文案或封面目录。'),
  }, { manifest: 'illustrations/manifest.json' }, 680, 40);
  png('illustrations-png', '配图导出 PNG · HTML 批量转 PNG', 'illustrations', {
    manifest_file: output('illustrations', 'artifacts.manifest'),
  }, 960, 540, '.illustration', 1000, 40);

  chat('cover', '生成封面 · HTML 封面生成器', 'html-cover-generator', ['copy'], {
    source: output('copy', 'artifacts.copy_md'), aspect: fixed('2.35:1'),
    requirements: fixed('读取图文文案文件，使用其中 P1 的封面标题和可选副标题生成一张封面，逐字保留选定标题，不使用备选标题、发布配文或画面建议作为封面文字。遵循文案中的统一视觉建议，保存为 cover/cover.html，使用 .cover 根元素，固定 1080×460 CSS 像素，body 无外边距。不生成正文配图，不修改文章、文案或配图目录，不导出 PNG。'),
  }, { html: 'cover/cover.html' }, 680, 360);
  png('cover-png', '封面导出 PNG · HTML 批量转 PNG', 'cover', {
    html_file: output('cover', 'artifacts.html'),
  }, 1080, 460, '.cover', 1000, 360);

  return {
    id: '', name: '公众号写作转图文 · 配图与封面并行',
    description: '人工输入选题，完成公众号写作和图文文案后，分叉生成正文配图与封面，并分别导出 PNG。',
    icon: '🔀', execution_mode: 'automatic', is_public: false,
    input_schema: {
      type: 'object', properties: {
        topic: { type: 'string', title: '选题与素材', minLength: 1, 'x-control': 'textarea',
          'x-placeholder': '输入选题，可补充目标读者、素材与写作要求' },
      }, required: ['topic'], additionalProperties: false,
    },
    output_mapping: {
      article: output('writer', 'artifacts.article_md'),
      copy: output('copy', 'artifacts.copy_md'),
      illustrations: output('illustrations-png', 'files'),
      cover: output('cover-png', 'files'),
    },
    steps,
  };
}
