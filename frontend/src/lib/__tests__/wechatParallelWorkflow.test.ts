import { describe, expect, it } from 'vitest';
import type { ApplicationRuntime } from '@/types';
import { buildWechatParallelWorkflow, WECHAT_PARALLEL_APPS, workflowStepOutputOptions } from '../wechatParallelWorkflow';
import { workflowGraphError } from '../workflowGraph';

const apps = WECHAT_PARALLEL_APPS.map((slug, index) => ({
  id: index + 1, application_slug: slug, application_name: slug,
  kind: slug === 'html-to-png' ? 'task' : 'chat', default_config: {},
  guided_prompts: [{ key: 'main', questions: [] }],
}) as unknown as ApplicationRuntime);

describe('WeChat article and cover parallel preset', () => {
  it('branches only after writing and never makes either branch depend on the other', () => {
    const workflow = buildWechatParallelWorkflow(apps);
    const steps = workflow.steps!;
    const byKey = Object.fromEntries(steps.map((step) => [step.key, step]));
    expect(steps).toHaveLength(8);
    expect(workflow.execution_mode).toBe('automatic');
    expect(workflowGraphError(steps)).toBeUndefined();
    expect(byKey.illustrations.depends_on).toEqual(['writer']);
    expect(byKey.cover.depends_on).toEqual(['writer']);
    expect(byKey['cover-png'].depends_on).toEqual(['cover']);
    expect(byKey.layout.depends_on).toEqual(['illustrations-png']);
    expect(byKey['pages-png'].depends_on).toEqual(['paginate']);
    expect(byKey.layout.config.automation).toMatchObject({ answers: {
      source: { from: 'steps.illustrations-png.output.article_md' },
    } });
    expect(byKey['illustrations-png'].input_mapping).toMatchObject({
      article_source: { from: 'steps.writer.output.artifacts.article_md' },
      strict: { value: true }, device_scale_factor: { value: 3 },
    });
    expect(workflow.output_mapping).toMatchObject({
      pages: { from: 'steps.pages-png.output.files' },
      cover: { from: 'steps.cover-png.output.files' },
    });
  });

  it('makes every mapped node output available in the editor and declares dependencies', () => {
    const workflow = buildWechatParallelWorkflow(apps);
    for (const step of workflow.steps!) {
      const answers = (step.config.automation as { answers?: Record<string, { from?: string }> })?.answers || {};
      for (const binding of Object.values({ ...answers, ...step.input_mapping })) {
        if (!('from' in binding) || !binding.from?.startsWith('steps.')) continue;
        const dependencyKey = binding.from.split('.')[1];
        expect(step.depends_on).toContain(dependencyKey);
        const dependency = workflow.steps!.find((item) => item.key === dependencyKey)!;
        expect(workflowStepOutputOptions(dependency).map((option) => option.value)).toContain(binding.from);
      }
    }
  });

  it('rejects incomplete application sets rather than making a partial workflow', () => {
    expect(() => buildWechatParallelWorkflow(apps.slice(1))).toThrow('wechat-viral-article');
  });
});
