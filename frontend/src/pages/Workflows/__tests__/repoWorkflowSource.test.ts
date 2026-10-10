// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { buildRepoWorkflowMaterial, parseRepoWorkflowSource, repoWorkflowEditorPath } from '../repoWorkflowSource';
import { repoProjectFixture, repoSource } from './fixtures/repoWorkflow';

describe('repository workflow source', () => {
  it('round trips identifiers without source text and deduplicates feature selections', () => {
    const url = new URL(repoWorkflowEditorPath({ ...repoSource, featureIds: ['f1', 'f1', 'f3'] }), 'https://local.test');
    expect([...url.searchParams.keys()]).toEqual(['preset', 'repoOrganization', 'repoApplication', 'repoProject', 'repoAnalysis', 'repoFeature', 'repoFeature']);
    expect(parseRepoWorkflowSource(url.searchParams, repoSource.organizationId)).toEqual({ ...repoSource, featureIds: ['f1', 'f3'] });
    expect(parseRepoWorkflowSource(new URLSearchParams('preset=wechat-content-suite'), null)).toBeNull();
  });

  it('keeps only selected features and deduplicated evidence tied to the analyzed snapshot', () => {
    const result = buildRepoWorkflowMaterial(repoProjectFixture(), repoSource);
    expect(result.name).toContain('示例仓库');
    for (const value of ['文档描述', '找到实现依据', '尚待确认', '需要登录', '需要联网', '缺少运行验证',
      '源码工具简介', '需要数据库', 'analyzed-commit', 'analyzed-digest', '包含工作区修改：是', '尚有文件未读取',
      'src/tool.ts · L2–L3', '不代表实际运行验证', '不得虚构']) expect(result.topic).toContain(value);
    for (const value of ['功能4', 'unselectedEvidence', 'newest-commit', 'newest-digest']) expect(result.topic).not.toContain(value);
    expect(result.topic.match(/selectedEvidence\(\)/g)).toHaveLength(1);
  });

  it.each(['repoOrganization', 'repoApplication', 'repoProject', 'repoAnalysis', 'repoFeature', 'preset'])(
    'rejects missing %s instead of falling back', key => {
      const query = new URL(repoWorkflowEditorPath(repoSource), 'https://local.test').searchParams;
      query.delete(key);
      expect(() => parseRepoWorkflowSource(query, repoSource.organizationId)).toThrow('参数无效');
    },
  );
  it('rejects mismatched organizations and malformed or repeated identifiers', () => {
    const query = new URL(repoWorkflowEditorPath(repoSource), 'https://local.test').searchParams;
    expect(() => parseRepoWorkflowSource(query, 'another-org')).toThrow('组织');
    query.append('repoApplication', '8');
    expect(() => parseRepoWorkflowSource(query, repoSource.organizationId)).toThrow('参数无效');
    query.set('repoApplication', '../apps');
    expect(() => parseRepoWorkflowSource(query, repoSource.organizationId)).toThrow('参数无效');
  });

  it.each(['project', 'analysis', 'status', 'kind', 'snapshot', 'feature', 'evidence', 'report'])(
    'rejects unavailable %s data', problem => {
      const project = repoProjectFixture();
      if (problem === 'project') project.id = 'wrong-project';
      if (problem === 'analysis') project.tasks[0].id = 'other-analysis';
      if (problem === 'status') project.tasks[0].status = 'failed';
      if (problem === 'kind') project.tasks[0].kind = 'write';
      if (problem === 'snapshot') project.snapshots.pop();
      if (problem === 'feature') project.tasks[0].output.features!.shift();
      if (problem === 'evidence') delete project.tasks[0].output.evidence!.e1;
      if (problem === 'report') project.tasks[0].output = {};
      expect(() => buildRepoWorkflowMaterial(project, repoSource)).toThrow();
    },
  );
});
