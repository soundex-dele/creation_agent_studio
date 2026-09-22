import { describe, expect, it } from 'vitest';
import type { ApplicationRuntime } from '@/types';
import { workflowGraphError } from '@/lib/workflowGraph';
import { workflowStepOutputOptions } from '@/lib/wechatParallelWorkflow';
import { validateWorkflowInput, workflowInputFields } from '@/lib/workflowInputSchema';
import { buildImageTextParallelWorkflow, IMAGE_TEXT_PARALLEL_APPS, IMAGE_TEXT_PARALLEL_PRESET } from '../imageTextParallel';
import { findWorkflowPreset } from '..';

const apps = IMAGE_TEXT_PARALLEL_APPS.map((slug, index) => ({
  id: index + 1, application_slug: slug, application_name: slug,
  kind: slug === 'html-to-png' ? 'task' : 'chat',
  default_config: { guided_entry_prompt_key: 'selected' },
  guided_prompts: [{ key: 'first', questions: [] }, { key: 'selected', questions: [] }],
}) as unknown as ApplicationRuntime);

describe('article to image-text parallel preset', () => {
  it('requires a topic and branches at copywriting into two independent PNG exports', () => {
    const preset = findWorkflowPreset(IMAGE_TEXT_PARALLEL_PRESET)!;
    const workflow = preset.build(apps);
    expect(workflow.execution_mode).toBe('automatic');
    expect(workflowGraphError(workflow.steps!)).toBeUndefined();
    expect(workflow.steps!.map((step) => [step.key, step.depends_on])).toEqual([
      ['writer', []], ['copy', ['writer']], ['illustrations', ['copy']],
      ['illustrations-png', ['illustrations']], ['cover', ['copy']], ['cover-png', ['cover']],
    ]);
    const fields = workflowInputFields(workflow.input_schema);
    expect(validateWorkflowInput(fields, {})).toHaveProperty('topic');
    expect(validateWorkflowInput(fields, { topic: '如何坚持阅读' })).toEqual({});
    const byKey = Object.fromEntries(workflow.steps!.map((step) => [step.key, step]));
    expect(byKey.copy.config.automation).toMatchObject({
      guided_prompt_key: 'selected',
      answers: { source: { from: 'steps.writer.output.artifacts.article_md' }, task: { value: 'article-to-pages' } },
    });
    expect(byKey.illustrations.config.automation).toMatchObject({
      answers: { article: { from: 'steps.copy.output.artifacts.copy_md' } },
    });
    expect(byKey.cover.config.automation).toMatchObject({
      answers: { source: { from: 'steps.copy.output.artifacts.copy_md' } },
    });
    expect(byKey['illustrations-png'].input_mapping).toMatchObject({
      manifest_file: { from: 'steps.illustrations.output.artifacts.manifest' }, strict: { value: true },
    });
    expect(byKey['illustrations-png'].input_mapping).not.toHaveProperty('article_source');
    expect(byKey['cover-png'].input_mapping).toMatchObject({
      html_file: { from: 'steps.cover.output.artifacts.html' }, strict: { value: true },
    });
    expect(workflow.output_mapping).toMatchObject({
      illustrations: { from: 'steps.illustrations-png.output.files' },
      cover: { from: 'steps.cover-png.output.files' },
    });
  });

  it('uses declared file outputs and dependency bindings for every handoff', () => {
    const workflow = buildImageTextParallelWorkflow(apps);
    const availableOutputs = workflow.steps!.flatMap((step) => workflowStepOutputOptions(step).map((option) => option.value));
    for (const step of workflow.steps!) {
      const answers = (step.config.automation as { answers?: Record<string, { from?: string }> })?.answers || {};
      for (const binding of Object.values({ ...answers, ...step.input_mapping })) {
        if (!('from' in binding) || !binding.from?.startsWith('steps.')) continue;
        expect(step.depends_on).toContain(binding.from.split('.')[1]);
        expect(availableOutputs).toContain(binding.from);
      }
    }
    for (const binding of Object.values(workflow.output_mapping!)) {
      expect(availableOutputs).toContain(typeof binding === 'string' ? binding : binding.from);
    }
  });

  it('rejects missing copywriting or unusable application configurations', () => {
    expect(() => buildImageTextParallelWorkflow(apps.filter((app) => app.application_slug !== 'write-image-text-copy')))
      .toThrow('write-image-text-copy');
    expect(() => buildImageTextParallelWorkflow(apps.map((app) => app.application_slug === 'write-image-text-copy'
      ? { ...app, guided_prompts: [] } : app))).toThrow('未配置引导提示词');
    expect(() => buildImageTextParallelWorkflow(apps.map((app) => app.application_slug === 'html-to-png'
      ? { ...app, kind: 'chat' } as ApplicationRuntime : app))).toThrow('必须是任务应用');
  });
});
