import type { ReactNode } from 'react';
import { Button } from 'antd';
import {
  ArrowLeft,
  BookOpenText,
  CheckCircle2,
  Lightbulb,
  ListOrdered,
  Sparkles,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import rehypeKatex from 'rehype-katex';
import remarkMath from 'remark-math';

import ChatContainer from '@/components/Chat/ChatContainer';
import type { AssistantMessageRenderContext } from '@/components/Chat/MessageList';
import { normalizeMarkdownMath } from '@/lib/markdownMath';
import type { StudyProblem, StudyTutor } from '@/types/studyWithMethod';
import { looksLikeStudyTutorJson, parseStudyTutorAnswer } from './studyTutorAnswer';
import './StudyTutorChat.css';

interface StudyTutorChatProps {
  conversationId: string;
  tutor: StudyTutor | null;
  subjectLabel: string;
  activeProblem: StudyProblem | null;
  resultBusy: boolean;
  draftRequest: { id: number; text: string } | null;
  quickReplies: string[];
  onBack: () => void;
  onDraftRequest: (request: { id: number; text: string }) => void;
  onRecordResult: (correct: boolean) => void;
}

const validationLabels: Record<string, string> = {
  validated: '答案已校验',
  verified: '答案已校验',
  needs_ai_or_teacher_review: '建议再复核答案',
  needs_teacher_review: '建议请老师复核',
};

function TutorMarkdown({ children }: { children: string }) {
  return <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
    {normalizeMarkdownMath(children)}
  </ReactMarkdown>;
}

function AnswerSection({
  icon,
  title,
  children,
  tone = 'default',
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
  tone?: 'default' | 'highlight' | 'answer';
}) {
  return <section className={`study-tutor-answer__section study-tutor-answer__section--${tone}`}>
    <h4>{icon}<span>{title}</span></h4>
    <div>{children}</div>
  </section>;
}

function renderTutorAnswer({ content, isStreaming }: AssistantMessageRenderContext) {
  const answer = parseStudyTutorAnswer(content);
  if (!answer) {
    if (isStreaming && looksLikeStudyTutorJson(content)) {
      return <div className="study-tutor-answer__preparing" role="status" aria-live="polite">
        <Sparkles size={17} aria-hidden="true" />
        正在整理题目和解题思路…
      </div>;
    }
    return undefined;
  }

  const hasAnswer = Boolean(answer.finalAnswer || answer.steps.length);
  const title = hasAnswer ? '这道题可以这样解' : answer.hint ? '先沿着这个方向想一想' : '题目分析';
  const validationLabel = validationLabels[answer.validationStatus];

  return <article className="study-tutor-answer" aria-live="polite">
    <header className="study-tutor-answer__header">
      <span className="study-tutor-answer__mark"><Sparkles size={18} aria-hidden="true" /></span>
      <div>
        <strong>{title}</strong>
        <span>
          {answer.hintLevel ? `第 ${answer.hintLevel} 级提示` : '学之有道辅导'}
          {validationLabel ? ` · ${validationLabel}` : ''}
        </span>
      </div>
    </header>

    {answer.recognizedProblem && <details className="study-tutor-answer__problem">
      <summary>查看识别到的题目</summary>
      <TutorMarkdown>{answer.recognizedProblem}</TutorMarkdown>
    </details>}

    {answer.knowledgePoints.length > 0 && <div className="study-tutor-answer__tags" aria-label="涉及知识点">
      {answer.knowledgePoints.map((point, index) => <span key={`${point}-${index}`}>{point}</span>)}
    </div>}

    {answer.finalAnswer && <AnswerSection icon={<CheckCircle2 size={18} />} title="最终答案" tone="answer">
      <TutorMarkdown>{answer.finalAnswer}</TutorMarkdown>
    </AnswerSection>}

    {answer.hint && <AnswerSection icon={<Lightbulb size={18} />} title="关键提示" tone="highlight">
      <TutorMarkdown>{answer.hint}</TutorMarkdown>
    </AnswerSection>}

    {answer.steps.length > 0 && <AnswerSection icon={<ListOrdered size={18} />} title="解题步骤">
      <ol className="study-tutor-answer__steps">
        {answer.steps.map((step, index) => <li key={`${step}-${index}`}>
          <span>{index + 1}</span><div><TutorMarkdown>{step}</TutorMarkdown></div>
        </li>)}
      </ol>
    </AnswerSection>}

    {answer.variantProblem && <AnswerSection icon={<BookOpenText size={18} />} title="同类练习">
      <TutorMarkdown>{answer.variantProblem}</TutorMarkdown>
      {answer.variantAnswer && <details className="study-tutor-answer__variant-answer">
        <summary>查看练习答案</summary>
        <TutorMarkdown>{answer.variantAnswer}</TutorMarkdown>
      </details>}
    </AnswerSection>}

    {answer.extraSections.map((section) => <AnswerSection
      key={section.key}
      icon={<BookOpenText size={18} />}
      title={section.label}
    >
      {section.items.length === 1
        ? <TutorMarkdown>{section.items[0]}</TutorMarkdown>
        : <ul>{section.items.map((item, index) => <li key={`${item}-${index}`}><TutorMarkdown>{item}</TutorMarkdown></li>)}</ul>}
    </AnswerSection>)}
  </article>;
}

export default function StudyTutorChat({
  conversationId,
  tutor,
  subjectLabel,
  activeProblem,
  resultBusy,
  draftRequest,
  quickReplies,
  onBack,
  onDraftRequest,
  onRecordResult,
}: StudyTutorChatProps) {
  return <div className="swm-embedded-tutor">
    <div className="swm-tutor-chat-header">
      <Button type="text" icon={<ArrowLeft size={18} />} onClick={onBack}>辅导首页</Button>
      <div>
        <strong>{tutor?.name || subjectLabel}</strong>
        <span>{subjectLabel} · 本会话固定老师</span>
      </div>
    </div>
    <div className="swm-chat-frame">
      <ChatContainer
        conversationId={conversationId}
        composerMode="study"
        defaultAgent={tutor ? {
          id: tutor.id,
          name: tutor.name,
          description: tutor.description,
        } : null}
        draftRequest={draftRequest}
        inputPlaceholder="也可以补充你的问题…"
        suggestions={[]}
        renderAssistantContent={renderTutorAnswer}
        inputAccessory={<div className="swm-quick-replies" aria-label="快捷提问">
          {quickReplies.map((text) => <button
            type="button"
            key={text}
            onClick={() => onDraftRequest({ id: Date.now(), text })}
          >{text}</button>)}
        </div>}
      />
    </div>
    {activeProblem && <div className="swm-learning-result">
      <span>辅导结束后，选下一步</span>
      <Button disabled={resultBusy} onClick={() => onDraftRequest({ id: Date.now(), text: '出一道同类题让我练习' })}>做同类题</Button>
      <Button loading={resultBusy} onClick={() => onRecordResult(false)}>加入复习</Button>
      <Button type="primary" loading={resultBusy} onClick={() => onRecordResult(true)}>我会了</Button>
    </div>}
  </div>;
}
