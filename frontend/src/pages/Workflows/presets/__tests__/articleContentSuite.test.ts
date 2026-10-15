import { describe, expect, it } from 'vitest';
import type { ApplicationRuntime, WorkflowStep } from '@/types';
import { workflowGraphError } from '@/lib/workflowGraph';
import { workflowStepOutputOptions } from '@/lib/wechatParallelWorkflow';
import { validateWorkflowInput, workflowInputFields } from '@/lib/workflowInputSchema';
import { buildContentSuiteWorkflow } from '../contentSuite';
import {
  ARTICLE_CONTENT_SUITE_APPS, ARTICLE_CONTENT_SUITE_PRESET, buildArticleContentSuiteWorkflow,
} from '../articleContentSuite';
import { findWorkflowPreset } from '..';

const apps = ARTICLE_CONTENT_SUITE_APPS.map((slug, index) => ({
  id: index + 1, application_slug: slug, application_name: slug,
  kind: slug === 'html-to-png' ? 'task' : 'chat', default_config: {},
  guided_prompts: [{ key: 'main', questions: [] }],
}) as unknown as ApplicationRuntime);
const answers = (step: WorkflowStep) => (
  step.config.automation as { answers: Record<string, { from?: string; value?: unknown }> }
)?.answers || {};

describe('existing article content suite preset', () => {
  it('replaces topic input with article text and removes the writing node', () => {
    const workflow = findWorkflowPreset(ARTICLE_CONTENT_SUITE_PRESET)!.build(apps);
    expect(workflow.execution_mode).toBe('automatic');
    expect(workflow.steps).toHaveLength(16);
    expect(workflowGraphError(workflow.steps!)).toBeUndefined();
    expect(workflow.steps!.some((step) => step.application.application_slug === 'wechat-viral-article')).toBe(false);
    expect(JSON.stringify(workflow)).not.toMatch(/steps\.writer|workflow\.input\.topic/);
    expect(workflow.steps!.map((step) => step.order)).toEqual(Array.from({ length: 16 }, (_, index) => index));
    expect(workflow.steps!.filter((step) => !step.depends_on.length).map((step) => step.key)).toEqual([
      'article-illustrations', 'article-cover', 'image-copy', 'video-copy',
    ]);
    const fields = workflowInputFields(workflow.input_schema);
    expect(fields.map((field) => field.key)).toEqual(['article']);
    expect(fields[0].multiline).toBe(true);
    expect(validateWorkflowInput(fields, {})).toHaveProperty('article');
    expect(validateWorkflowInput(fields, { article: '' })).toHaveProperty('article');
    expect(validateWorkflowInput(fields, { article: '# 标题\n\n完整正文。' })).toEqual({});
    for (const step of workflow.steps!.filter((item) => !item.depends_on.length)) {
      expect(Object.values(answers(step))).toContainEqual({ from: 'workflow.input.article' });
      expect(answers(step).requirements.value).toContain('不是选题或文件路径');
    }
  });

  it('saves the input article before PNG insertion and keeps every handoff resolvable', () => {
    const workflow = buildArticleContentSuiteWorkflow(apps);
    const byKey = Object.fromEntries(workflow.steps!.map((step) => [step.key, step]));
    expect(byKey['article-illustrations'].config.workflow_artifacts).toMatchObject({
      article_md: 'article/article.md', manifest: 'illustrations/manifest.json',
    });
    expect(answers(byKey['article-illustrations']).requirements.value).toContain('原文原样保存');
    expect(byKey['article-illustrations-png'].depends_on).toEqual(['article-illustrations']);
    expect(byKey['article-illustrations-png'].input_mapping?.article_source).toEqual({
      from: 'steps.article-illustrations.output.artifacts.article_md',
    });
    const available = workflow.steps!.flatMap((step) => workflowStepOutputOptions(step).map((option) => option.value));
    for (const step of workflow.steps!) {
      for (const binding of Object.values({ ...answers(step), ...step.input_mapping })) {
        if (!('from' in binding) || !binding.from?.startsWith('steps.')) continue;
        expect(step.depends_on).toContain(binding.from.split('.')[1]);
        expect(available).toContain(binding.from);
      }
    }
    for (const binding of Object.values(workflow.output_mapping!)) {
      expect(available).toContain(typeof binding === 'string' ? binding : binding.from);
    }
  });

  it('retains all other branches, outputs and the original total preset', () => {
    const original = buildContentSuiteWorkflow(apps);
    const snapshot = JSON.stringify(apps);
    const workflow = buildArticleContentSuiteWorkflow(apps);
    const adapted = new Set(['article-illustrations', 'article-illustrations-png', 'article-cover', 'image-copy', 'video-copy']);
    for (const step of workflow.steps!) {
      const source = original.steps!.find((item) => item.key === step.key)!;
      if (!adapted.has(step.key)) expect(step).toEqual({ ...source, order: source.order - 1 });
    }
    expect(workflow.output_mapping).toEqual({
      ...original.output_mapping,
      source_article: { from: 'steps.article-illustrations.output.artifacts.article_md' },
    });
    expect(answers(workflow.steps!.find((step) => step.key === 'video-jianying')!).task).toEqual({ value: 'script' });
    expect(buildContentSuiteWorkflow(apps)).toEqual(original);
    expect(JSON.stringify(apps)).toBe(snapshot);
    expect(() => buildArticleContentSuiteWorkflow(apps.filter((app) => app.application_slug !== 'copy-to-jianying')))
      .toThrow('copy-to-jianying');
  });
});
