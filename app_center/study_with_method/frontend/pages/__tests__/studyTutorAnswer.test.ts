import { describe, expect, it } from 'vitest';

import { looksLikeStudyTutorJson, parseStudyTutorAnswer } from '../studyTutorAnswer';

describe('parseStudyTutorAnswer', () => {
  it('parses the structured tutor schema', () => {
    const answer = parseStudyTutorAnswer(JSON.stringify({
      subject: 'math',
      recognized_problem: '求函数 $f(x)$ 的最大值',
      knowledge_points: ['函数单调性', '导数'],
      hint_level: 3,
      hint: '先求导并判断单调区间。',
      steps: ['求出 $f\'(x)$', '令导数等于 0'],
      final_answer: '最大值为 4。',
      validation_status: 'validated',
    }));

    expect(answer).toMatchObject({
      subject: 'math',
      recognizedProblem: '求函数 $f(x)$ 的最大值',
      knowledgePoints: ['函数单调性', '导数'],
      hintLevel: 3,
      steps: ['求出 $f\'(x)$', '令导数等于 0'],
      finalAnswer: '最大值为 4。',
    });
  });

  it('accepts fenced and nested JSON strings', () => {
    const nested = JSON.stringify(JSON.stringify({ hint: '观察已知条件。', steps: [] }));
    expect(parseStudyTutorAnswer(`\`\`\`json\n${nested}\n\`\`\``)?.hint).toBe('观察已知条件。');
  });

  it('turns object steps and unknown fields into readable sections', () => {
    const answer = parseStudyTutorAnswer(JSON.stringify({
      steps: [{ title: '列式', content: '写出方程' }],
      common_mistakes: ['漏写定义域'],
    }));

    expect(answer?.steps).toEqual(['title：列式；content：写出方程']);
    expect(answer?.extraSections).toEqual([{
      key: 'common_mistakes',
      label: '易错点',
      items: ['漏写定义域'],
    }]);
  });

  it('does not treat ordinary markdown or invalid JSON as structured output', () => {
    expect(parseStudyTutorAnswer('先想一想：可以使用哪个公式？')).toBeNull();
    expect(parseStudyTutorAnswer('{"hint":')).toBeNull();
    expect(looksLikeStudyTutorJson('{"hint":')).toBe(true);
    expect(looksLikeStudyTutorJson('普通回答')).toBe(false);
  });
});
