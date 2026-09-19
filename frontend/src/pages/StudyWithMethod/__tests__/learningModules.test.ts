import { describe, expect, it } from 'vitest';

import type {
  CurriculumTree,
  StudyDashboard,
  StudyMastery,
  StudyMistake,
  StudyReview,
  SubjectEnrollment,
} from '@/types/studyWithMethod';
import {
  buildFlashcards,
  buildKnowledgeMapNodes,
  buildLearningActions,
  formatKnowledgeCondition,
} from '../learningModules';

describe('study learning modules', () => {
  it('turns the current learning state into three one-tap actions', () => {
    const dashboard = {
      mode: 'student',
      profile: {
        focus_subjects: ['math'],
        enrollments: [{ subject: 'math' }],
      },
      due_reviews: [{ subject: 'physics' }],
      masteries: [{ subject: 'physics', score: 35, knowledge_point_name: '受力分析' }],
      stats_by_subject: [{ subject: 'math', mistake_count: 2 }],
      mistake_count: 2,
    } as Extract<StudyDashboard, { mode: 'student' }>;

    expect(buildLearningActions(dashboard)).toMatchObject([
      { id: 'quiz', subject: 'math', mode: 'quiz' },
      { id: 'cards', subject: 'physics', mode: 'cards' },
      { id: 'map', subject: 'physics', mode: 'map' },
    ]);
  });

  it('builds answer cards from mistakes and links due reviews', () => {
    const mistake = {
      id: 'mistake-1',
      subject: 'math',
      cause_label: '方法选择',
      knowledge_summary: '先确定事件是否互斥',
      correct_answer: '使用分类计数',
      mastery: 20,
      problem: {
        confirmed_text: '求事件发生的概率',
        original_text: '',
        source_image_url: '',
        knowledge_point_name: '古典概型',
      },
    } as StudyMistake;
    const review = { id: 'review-1', mistake } as StudyReview;

    expect(buildFlashcards('math', [mistake], [review])).toEqual([
      expect.objectContaining({
        id: 'mistake-1',
        question: '求事件发生的概率',
        answer: '使用分类计数',
        reviewId: 'review-1',
      }),
    ]);
  });

  it('combines mastery, weak topics and the current chapter without duplicates', () => {
    const enrollment = {
      current_chapter: '函数',
      weak_topics: ['单调性', '函数'],
    } as SubjectEnrollment;
    const masteries = [{
      id: 'mastery-1',
      subject: 'math',
      knowledge_point_name: '单调性',
      score: 45,
      attempts_count: 3,
      correct_count: 1,
    }] as StudyMastery[];

    const nodes = buildKnowledgeMapNodes(enrollment, 'math', masteries);
    expect(nodes.map((node) => node.label)).toEqual(['函数', '单调性']);
    expect(nodes[1]).toMatchObject({ status: 'needs-work', score: 45 });
  });

  it('shows every curriculum knowledge point and marks untouched points unstarted', () => {
    const curriculum = {
      id: 'xj-math-current',
      subject: 'math',
      label: '湘教版（现行）',
      publisher: '湖南教育出版社',
      volumes: [{
        id: 'required-1',
        name: '必修第一册',
        chapters: [{
          id: 'chapter-1',
          name: '集合与逻辑',
          sections: [{
            id: 'section-1',
            name: '集合',
            knowledge_points: [
              {
                id: 'math.xj.required-1.sets',
                name: '集合的概念',
                summary: '理解集合、元素与表示方法。',
                objectives: ['判断元素与集合的关系'],
                prerequisites: ['初中代数基础'],
                common_mistakes: ['混淆元素与集合'],
                keywords: ['集合', '元素'],
                competency_tags: ['数学抽象'],
                knowledge_items: [{
                  id: 'membership',
                  type: 'definition',
                  name: '元素与集合的关系',
                  content: '用属于和不属于描述对象与集合之间的关系。',
                  formulas: ['a\\in A', 'a\\notin A'],
                  review_status: 'self_checked',
                }],
              },
              {
                id: 'math.xj.required-1.operations',
                name: '集合的运算',
                summary: '掌握交集、并集与补集。',
                objectives: ['完成集合运算'],
                prerequisites: ['集合的概念'],
                common_mistakes: ['忽略全集范围'],
                keywords: ['交集', '并集', '补集'],
                competency_tags: ['逻辑推理'],
                knowledge_items: [{
                  id: 'set-operations',
                  type: 'formula',
                  name: '集合的交、并、补运算',
                  content: '交集取公共元素，并集汇总元素，补集依赖给定全集。',
                  formulas: ['A\\cap B'],
                  review_status: 'self_checked',
                }],
              },
            ],
          }],
        }],
      }],
    } as CurriculumTree;
    const mastery = [{
      id: 'mastery-1',
      subject: 'math',
      knowledge_point_code: 'math.xj.required-1.sets',
      knowledge_point_name: '集合的概念',
      score: 80,
      attempts_count: 5,
      correct_count: 4,
    }] as StudyMastery[];

    const nodes = buildKnowledgeMapNodes(undefined, 'math', mastery, curriculum);

    expect(nodes).toHaveLength(2);
    expect(nodes[0]).toMatchObject({
      id: 'math.xj.required-1.sets',
      status: 'mastered',
      score: 80,
      group: '必修第一册 · 集合与逻辑',
      summary: '理解集合、元素与表示方法。',
      objectives: ['判断元素与集合的关系'],
      commonMistakes: ['混淆元素与集合'],
      knowledgeItems: [expect.objectContaining({
        name: '元素与集合的关系',
        formulas: ['a\\in A', 'a\\notin A'],
      })],
    });
    expect(nodes[1]).toMatchObject({
      id: 'math.xj.required-1.operations',
      status: 'unstarted',
      score: null,
    });
  });

  it('marks formula-like applicability conditions as inline math', () => {
    expect(formatKnowledgeCondition('a\\ne0')).toBe('$a\\ne0$');
    expect(formatKnowledgeCondition('P(B)>0')).toBe('$P(B)>0$');
    expect(formatKnowledgeCondition('{B_i}\\text{ 构成样本空间的一个划分}'))
      .toBe('${B_i}\\text{ 构成样本空间的一个划分}$');
    expect(formatKnowledgeCondition('全集 U 已确定')).toBe('全集 U 已确定');
    expect(formatKnowledgeCondition('$a>0$')).toBe('$a>0$');
  });
});
