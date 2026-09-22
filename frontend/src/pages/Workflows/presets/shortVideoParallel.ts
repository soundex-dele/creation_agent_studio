import type { ApplicationRuntime, Workflow, WorkflowStep } from '@/types';

export const SHORT_VIDEO_PARALLEL_PRESET = 'wechat-short-video-parallel';
export const SHORT_VIDEO_PARALLEL_APPS = [
  'wechat-viral-article', 'write-short-video-copy', 'copy-to-jianying', 'html-cover-generator', 'html-to-png',
] as const;

type Binding = { from: string } | { value: unknown };
type Artifact = string;
const fixed = (value: unknown): Binding => ({ value });
const output = (key: string, field: string) => ({ from: `steps.${key}.output.${field}` });

export function buildShortVideoParallelWorkflow(applications: ApplicationRuntime[]): Workflow {
  const bySlug = new Map(applications.map((app) => [app.application_slug, app]));
  const missing = SHORT_VIDEO_PARALLEL_APPS.filter((slug) => !bySlug.has(slug));
  if (missing.length) throw new Error(`缺少工作流应用：${missing.join('、')}`);
  const steps: WorkflowStep[] = [];
  const chat = (
    key: string, name: string, slug: string, dependencies: string[],
    answers: Record<string, Binding>, artifacts: Record<string, Artifact>, x: number, y: number,
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

  chat('writer', '写作 · 公众号爆款写作', 'wechat-viral-article', [], {
    source: { from: 'workflow.input.topic' }, task: fixed('full-article'),
    requirements: fixed('根据选题完成文章，将最终选定的标题和完整正文保存到 article/article.md。文件只包含可发布的 Markdown 文章，不含候选标题、创作说明或发布策略；其他说明另行交付。'),
  }, { article_md: 'article/article.md' }, 40, 200);

  chat('copy', '生成文案 · 短视频文案', 'write-short-video-copy', ['writer'], {
    source: output('writer', 'artifacts.article_md'), task: fixed('article-to-video'),
    platform: fixed('general'), format: fixed('voiceover'), duration: fixed('约 60 秒'),
    requirements: fixed('读取传入的文章文件，改编为适合 9:16 竖版视频的短视频文案。保存 copy/short-video.md，包含唯一推荐标题、选定的封面短句及可选副标题、连续可读的旁白正文、估算时长、分镜建议与发布配文，各部分明确分开。另存 copy/narration.txt，只包含最终实际朗读的旁白正文，与完整文案中的正文逐字一致，不包含标题、章节标签、分镜说明、时长或发布配文。封面短句与视频主题一致，沿用原稿事实，不生成配音、剪映草稿或 HTML，不修改文章原稿。'),
  }, { copy_md: 'copy/short-video.md', narration: 'copy/narration.txt' }, 360, 200);

  chat('jianying', '生成 builder 脚本 · 文案转剪映', 'copy-to-jianying', ['copy'], {
    source: output('copy', 'artifacts.narration'), task: fixed('script'),
    aspect: fixed('9:16'), voice: fixed('auto'), duration: fixed(''),
    output_directory: fixed('jianying/'),
    requirements: fixed('读取传入的纯旁白文件，完整保留朗读正文，仅编写可编辑、可重复运行的 builder.py，不执行构建、不生成剪映草稿、不实际合成配音或渲染素材。阅读技能中的 Builder API 和分镜指南，由 AI 直接设计分镜并编写脚本，脚本中配置后续运行时的自然普通话配音、字幕、画面和时间线，使用技能内置后端。当前工作流以固定文件路径交付：保存 jianying/builder.py，并将纯旁白保存到同目录的 jianying/narration.txt；脚本基于自身所在目录定位该旁白文件，其他资源使用稳定且可解析的路径。若目标文件已存在，先在 jianying/history/ 下建立唯一子目录备份旧脚本及旁白，再更新本次交付文件，保留旧工程和素材。只做不执行脚本的语法检查，不运行 builder.py 或 run_project.py 的构建/检查命令，不生成或要求 result.json、build.log、timeline.json 和草稿审计文件。交付说明列出脚本及旁白路径，明确仅脚本已生成、尚未构建草稿；不修改文章、文案或封面目录，不等待封面分支，不导出 MP4。'),
  }, { builder: 'jianying/builder.py', narration: 'jianying/narration.txt' }, 680, 40);
  chat('cover', '生成封面 · HTML 封面生成器', 'html-cover-generator', ['copy'], {
    source: output('copy', 'artifacts.copy_md'), aspect: fixed('9:16'),
    requirements: fixed('读取短视频文案文件，使用选定的封面短句与可选副标题生成一张竖版视频封面，逐字保留所选文字，不使用备选标题、分镜说明、旁白正文或发布配文作为封面标题。视觉与视频主题一致，保存为 cover/cover.html，使用 .cover 根元素，固定 1080×1920 CSS 像素，body 无外边距，输出自包含 HTML。不修改文章、文案或剪映目录，不等待剪映分支，不导出 PNG。'),
  }, { html: 'cover/cover.html' }, 680, 360);

  const pngApp = bySlug.get('html-to-png')!;
  if (pngApp.kind !== 'task') throw new Error('HTML 批量转 PNG 必须是任务应用');
  steps.push({
    id: 'draft-cover-png', key: 'cover-png', name: '封面导出 PNG · HTML 批量转 PNG',
    order: steps.length, application: pngApp, application_id: pngApp.id,
    depends_on: ['cover'], condition: {}, max_attempts: 1,
    config: { _editor: { position: { x: 1000, y: 360 } } },
    input_mapping: {
      html_file: output('cover', 'artifacts.html'), strict: fixed(true),
      width: fixed(1080), height: fixed(1920), selector: fixed('.cover'),
      full_page: fixed(false), device_scale_factor: fixed(3),
    },
  });

  return {
    id: '', name: '公众号写作转短视频 · builder 脚本与封面并行',
    description: '人工输入选题，完成公众号写作和短视频文案后，分叉生成 builder 脚本，以及 HTML 视频封面并导出 PNG。',
    icon: '🔀', execution_mode: 'automatic', is_public: false,
    input_schema: {
      type: 'object', properties: {
        topic: { type: 'string', title: '选题与素材', minLength: 1, 'x-control': 'textarea',
          'x-placeholder': '输入选题，可补充目标观众、素材与写作要求' },
      }, required: ['topic'], additionalProperties: false,
    },
    output_mapping: {
      article: output('writer', 'artifacts.article_md'),
      copy: output('copy', 'artifacts.copy_md'),
      narration: output('copy', 'artifacts.narration'),
      jianying: output('jianying', 'artifacts.builder'),
      cover: output('cover-png', 'files'),
    },
    steps,
  };
}
