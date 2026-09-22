import { describe, expect, it } from 'vitest';
import type { ApplicationRuntime } from '@/types';
import { workflowGraphError } from '@/lib/workflowGraph';
import { workflowStepOutputOptions } from '@/lib/wechatParallelWorkflow';
import { validateWorkflowInput, workflowInputFields } from '@/lib/workflowInputSchema';
import { buildShortVideoParallelWorkflow, SHORT_VIDEO_PARALLEL_APPS, SHORT_VIDEO_PARALLEL_PRESET } from '../shortVideoParallel';
import { findWorkflowPreset } from '..';

const apps = SHORT_VIDEO_PARALLEL_APPS.map((slug, index) => ({
  id: index + 1, application_slug: slug, application_name: slug, kind: slug === 'html-to-png' ? 'task' : 'chat',
  default_config: { guided_entry_prompt_key: 'selected' },
  guided_prompts: [{ key: 'first', questions: [] }, { key: 'selected', questions: [] }],
}) as unknown as ApplicationRuntime);

describe('article to short-video parallel preset', () => {
  it('branches at short-video copywriting and exports the HTML cover to PNG alongside a builder script without building a draft', () => {
    const workflow = findWorkflowPreset(SHORT_VIDEO_PARALLEL_PRESET)!.build(apps);
    expect(workflow.execution_mode).toBe('automatic');
    expect(workflowGraphError(workflow.steps!)).toBeUndefined();
    expect(workflow.steps!.map((step) => [step.key, step.depends_on])).toEqual([
      ['writer', []], ['copy', ['writer']], ['jianying', ['copy']], ['cover', ['copy']],
      ['cover-png', ['cover']],
    ]);
    const fields = workflowInputFields(workflow.input_schema);
    expect(validateWorkflowInput(fields, {})).toHaveProperty('topic');
    expect(validateWorkflowInput(fields, { topic: '如何坚持阅读' })).toEqual({});
    const byKey = Object.fromEntries(workflow.steps!.map((step) => [step.key, step]));
    expect(byKey.copy.config.automation).toMatchObject({
      guided_prompt_key: 'selected', answers: {
        task: { value: 'article-to-video' }, source: { from: 'steps.writer.output.artifacts.article_md' },
      },
    });
    expect(byKey.jianying.config.automation).toMatchObject({ answers: {
      source: { from: 'steps.copy.output.artifacts.narration' },
      task: { value: 'script' }, aspect: { value: '9:16' }, voice: { value: 'auto' },
    } });
    expect(byKey.jianying.config.workflow_artifacts).toEqual({
      builder: 'jianying/builder.py',
      narration: 'jianying/narration.txt',
    });
    const requirements = (byKey.jianying.config.automation as {
      answers: { requirements: { value: string } };
    }).answers.requirements.value;
    expect(requirements).toContain('不执行构建、不生成剪映草稿');
    expect(workflow.output_mapping).not.toHaveProperty('build_result');
    expect(byKey.cover.config.automation).toMatchObject({ answers: {
      source: { from: 'steps.copy.output.artifacts.copy_md' }, aspect: { value: '9:16' },
    } });
    expect(workflow.output_mapping).toMatchObject({
      jianying: { from: 'steps.jianying.output.artifacts.builder' },
      cover: { from: 'steps.cover-png.output.files' },
    });
    expect(byKey['cover-png'].application.application_slug).toBe('html-to-png');
    expect(byKey['cover-png'].input_mapping).toEqual({
      html_file: { from: 'steps.cover.output.artifacts.html' }, strict: { value: true },
      width: { value: 1080 }, height: { value: 1920 }, selector: { value: '.cover' },
      full_page: { value: false }, device_scale_factor: { value: 3 },
    });
  });

  it('passes only declared file outputs along direct dependencies', () => {
    const workflow = buildShortVideoParallelWorkflow(apps);
    const available = workflow.steps!.flatMap((step) => workflowStepOutputOptions(step).map((option) => option.value));
    for (const step of workflow.steps!) {
      const answers = (step.config.automation as { answers: Record<string, { from?: string }> })?.answers || {};
      for (const binding of Object.values({ ...answers, ...step.input_mapping })) {
        if (!('from' in binding) || !binding.from?.startsWith('steps.')) continue;
        expect(step.depends_on).toContain(binding.from.split('.')[1]);
        expect(available).toContain(binding.from);
      }
    }
    for (const binding of Object.values(workflow.output_mapping!)) {
      expect(available).toContain(typeof binding === 'string' ? binding : binding.from);
    }
  });

  it('rejects missing or unusable script applications', () => {
    expect(() => buildShortVideoParallelWorkflow(apps.filter((app) => app.application_slug !== 'copy-to-jianying')))
      .toThrow('copy-to-jianying');
    expect(() => buildShortVideoParallelWorkflow(apps.map((app) => app.application_slug === 'copy-to-jianying'
      ? { ...app, guided_prompts: [] } : app))).toThrow('未配置引导提示词');
    expect(() => buildShortVideoParallelWorkflow(apps.filter((app) => app.application_slug !== 'html-to-png')))
      .toThrow('html-to-png');
    expect(() => buildShortVideoParallelWorkflow(apps.map((app) => app.application_slug === 'html-to-png'
      ? { ...apps[0], application_slug: 'html-to-png' } : app))).toThrow('必须是任务应用');
  });
});
