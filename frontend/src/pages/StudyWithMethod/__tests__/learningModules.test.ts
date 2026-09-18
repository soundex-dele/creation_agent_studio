import { describe, expect, it } from 'vitest';

import type {
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
});
