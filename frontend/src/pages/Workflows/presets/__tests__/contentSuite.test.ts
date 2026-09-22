import { describe, expect, it } from 'vitest';
import type { ApplicationRuntime, WorkflowStep } from '@/types';
import { workflowGraphError } from '@/lib/workflowGraph';
import { workflowStepOutputOptions, buildWechatParallelWorkflow } from '@/lib/wechatParallelWorkflow';
import { workflowInputFields, validateWorkflowInput } from '@/lib/workflowInputSchema';
import { buildContentSuiteWorkflow, CONTENT_SUITE_APPS, CONTENT_SUITE_PRESET } from '../contentSuite';
import { buildImageTextParallelWorkflow } from '../imageTextParallel';
import { buildShortVideoParallelWorkflow } from '../shortVideoParallel';
import { findWorkflowPreset } from '..';

const apps = CONTENT_SUITE_APPS.map((slug, index) => ({
  id: index + 1, application_slug: slug, application_name: slug,
  kind: slug === 'html-to-png' ? 'task' : 'chat', default_config: {},
  guided_prompts: [{ key: 'main', questions: [] }],
}) as unknown as ApplicationRuntime);
const answers = (step: WorkflowStep) => (
  step.config.automation as { answers: Record<string, { from?: string; value?: unknown }> }
)?.answers || {};

describe('combined content suite preset', () => {
  it('writes once then runs all three original branches without cross-branch dependencies', () => {
    const workflow = findWorkflowPreset(CONTENT_SUITE_PRESET)!.build(apps);
    const steps = workflow.steps!;
    expect(steps).toHaveLength(17);
    expect(workflowGraphError(steps)).toBeUndefined();
    expect(steps.filter((step) => !step.depends_on.length).map((step) => step.key)).toEqual(['writer']);
    expect(steps.filter((step) => step.application.application_slug === 'wechat-viral-article')).toHaveLength(1);
    expect(new Set(steps.map((step) => step.id)).size).toBe(17);
    expect(steps.map((step) => step.order)).toEqual(Array.from({ length: 17 }, (_, index) => index));
    for (const [prefix, count] of [['article', 7], ['image', 5], ['video', 4]] as const) {
      const branch = steps.filter((step) => step.key.startsWith(`${prefix}-`));
      expect(branch).toHaveLength(count);
      for (const step of branch) {
        expect(step.depends_on.every((key) => key === 'writer' || key.startsWith(`${prefix}-`))).toBe(true);
      }
    }
    const byKey = Object.fromEntries(steps.map((step) => [step.key, step]));
    expect(byKey['image-copy'].depends_on).toEqual(['writer']);
    expect(byKey['video-copy'].depends_on).toEqual(['writer']);
    expect(byKey['image-cover'].depends_on).toEqual(['image-copy']);
    expect(byKey['video-jianying'].depends_on).toEqual(['video-copy']);
    expect(byKey['video-cover'].depends_on).toEqual(['video-copy']);
    expect(byKey['video-cover-png'].depends_on).toEqual(['video-cover']);
    expect(byKey['video-cover-png'].input_mapping?.html_file)
      .toEqual({ from: 'steps.video-cover.output.artifacts.html' });
    const fields = workflowInputFields(workflow.input_schema);
    expect(fields.map((field) => field.key)).toEqual(['topic']);
    expect(validateWorkflowInput(fields, {})).toHaveProperty('topic');
    expect(validateWorkflowInput(fields, { topic: '时间管理' })).toEqual({});
  });

  it('remaps every file handoff and delivers outputs from all three branches', () => {
    const workflow = buildContentSuiteWorkflow(apps);
    const available = workflow.steps!.flatMap((step) => workflowStepOutputOptions(step).map((option) => option.value));
    for (const step of workflow.steps!) {
      for (const binding of Object.values({ ...answers(step), ...step.input_mapping })) {
        if (!('from' in binding) || !binding.from?.startsWith('steps.')) continue;
        expect(step.depends_on).toContain(binding.from.split('.')[1]);
        expect(available).toContain(binding.from);
      }
    }
    const mappings = Object.values(workflow.output_mapping!);
    expect(mappings).toHaveLength(11);
    for (const binding of mappings) {
      expect(available).toContain(typeof binding === 'string' ? binding : binding.from);
    }
    expect(workflow.output_mapping).toMatchObject({
      source_article: { from: 'steps.writer.output.artifacts.article_md' },
      article: { from: 'steps.article-illustrations-png.output.article_md' },
      article_pages: { from: 'steps.article-pages-png.output.files' },
      image_text_images: { from: 'steps.image-illustrations-png.output.files' },
      video_jianying: { from: 'steps.video-jianying.output.artifacts.builder' },
      video_cover: { from: 'steps.video-cover-png.output.files' },
    });
    const byKey = Object.fromEntries(workflow.steps!.map((step) => [step.key, step]));
    expect(byKey['article-illustrations-png'].input_mapping?.article_source)
      .toEqual({ from: 'steps.writer.output.artifacts.article_md' });
    expect(answers(byKey['video-jianying']).source)
      .toEqual({ from: 'steps.video-copy.output.artifacts.narration' });
  });

  it('isolates parallel output paths and keeps prompts consistent with file contracts', () => {
    const workflow = buildContentSuiteWorkflow(apps);
    const paths: string[] = [];
    for (const step of workflow.steps!) {
      const artifacts = (step.config.workflow_artifacts || {}) as Record<string, string | { path: string }>;
      const expectedFolder = step.key.startsWith('image-') ? 'image-text/'
        : step.key.startsWith('video-') ? 'short-video/' : '';
      const requirements = String(answers(step).requirements?.value || '');
      for (const artifact of Object.values(artifacts)) {
        const path = typeof artifact === 'string' ? artifact : artifact.path;
        paths.push(path);
        expect(path.startsWith(expectedFolder)).toBe(true);
        expect(requirements).toContain(path);
      }
      if (expectedFolder) {
        expect(requirements).not.toMatch(/(^|[^a-z0-9_/-])(copy|cover|illustrations|jianying)\//);
      }
    }
    expect(new Set(paths).size).toBe(paths.length);
    expect(paths).toContain('article/article.md');
    expect(paths).toContain('article/article-with-images.html');
    expect(paths).toEqual(expect.arrayContaining([
      'cover/cover.html', 'image-text/cover/cover.html', 'short-video/cover/cover.html',
      'image-text/copy/image-text.md', 'short-video/copy/short-video.md',
      'short-video/jianying/builder.py',
    ]));
    const jianying = workflow.steps!.find((step) => step.key === 'video-jianying')!;
    expect(answers(jianying).task).toEqual({ value: 'script' });
    expect(workflow.output_mapping).not.toHaveProperty('video_build_result');
    expect(answers(jianying).output_directory).toEqual({ value: 'short-video/jianying/' });
    expect(jianying.config.workflow_artifacts).toMatchObject({
      builder: 'short-video/jianying/builder.py',
    });
  });

  it('preserves standalone presets and rejects an incomplete application set', () => {
    const builders = [buildWechatParallelWorkflow, buildImageTextParallelWorkflow, buildShortVideoParallelWorkflow];
    const original = builders.map((build) => build(apps));
    const applicationSnapshot = JSON.stringify(apps);
    buildContentSuiteWorkflow(apps);
    expect(builders.map((build) => build(apps))).toEqual(original);
    expect(JSON.stringify(apps)).toBe(applicationSnapshot);
    expect(new Set(CONTENT_SUITE_APPS).size).toBe(CONTENT_SUITE_APPS.length);
    expect(() => buildContentSuiteWorkflow(apps.filter((app) => app.application_slug !== 'copy-to-jianying')))
      .toThrow('copy-to-jianying');
  });
});
