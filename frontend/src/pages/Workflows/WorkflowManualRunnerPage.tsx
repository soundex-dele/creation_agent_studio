import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Empty, Spin, message } from 'antd';
import {
  ArrowLeftOutlined,
  CheckOutlined,
  ExportOutlined,
} from '@ant-design/icons';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { api } from '@/services/api';
import type { RunResource } from '@/services/applicationRuntime';
import type { Workflow, WorkflowStep } from '@/types';
import { workflowApplicationPath } from '@/lib/workflowApplicationPath';
import './Workflows.css';


export default function WorkflowManualRunnerPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const resumeRunId = searchParams.get('runId');
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [manualRun, setManualRun] = useState<RunResource | null>(null);
  const [selectedKey, setSelectedKey] = useState('');
  const [openedKeys, setOpenedKeys] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [completing, setCompleting] = useState(false);
  const openingManualSession = useRef(false);

  useEffect(() => {
    if (!id || manualRun || openingManualSession.current) return;
    openingManualSession.current = true;
    setError('');
    Promise.all([
      api.get<Workflow>(`/workflows/${id}/`),
      api.post<RunResource>(`/workflows/${id}/manual-session/`, {
        action: 'open',
        ...(resumeRunId ? { run_id: resumeRunId } : {}),
      }),
    ])
      .then(([workflowResult, runResult]) => {
        const firstKey = workflowResult.steps?.[0]?.key ?? '';
        setWorkflow(workflowResult);
        setManualRun(runResult);
        setSelectedKey(firstKey);
        setOpenedKeys(firstKey ? [firstKey] : []);
        if (!resumeRunId) {
          navigate(`/workflows/${id}/manual?runId=${runResult.id}`, { replace: true });
        }
      })
      .catch((reason: any) => {
        openingManualSession.current = false;
        setError(reason?.response?.data?.detail || '工作流加载失败');
      });
  }, [id, manualRun, navigate, resumeRunId]);

  const steps = workflow?.steps ?? [];
  const selectedStep = steps.find((step) => step.key === selectedKey) ?? steps[0];

  const selectStep = (step: WorkflowStep) => {
    setSelectedKey(step.key);
    setOpenedKeys((current) => current.includes(step.key)
      ? current : [...current, step.key]);
  };

  const completeRun = async () => {
    if (!id || !manualRun) return;
    setCompleting(true);
    try {
      const completed = await api.post<RunResource>(`/workflows/${id}/manual-session/`, {
        action: 'complete',
        run_id: manualRun.id,
      });
      setManualRun(completed);
      message.success('本次手动执行已完成');
      navigate('/workflows');
    } catch (reason: any) {
      message.error(reason?.response?.data?.detail || '无法完成本次执行');
    } finally {
      setCompleting(false);
    }
  };

  if (error) {
    return <div className="workflow-run-loading"><Alert type="error" showIcon message={error} /></div>;
  }
  if (!workflow) {
    return <div className="workflow-run-loading"><Spin size="large" /></div>;
  }

  return (
    <div className="workflow-runner">
      <aside className="workflow-run-sidebar">
        <div className="workflow-run-brand">
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            aria-label="返回工作流列表"
            onClick={() => navigate('/workflows')}
          />
          <div>
            <strong>{workflow.name}</strong>
            <span>手动执行 · {steps.length} 个应用</span>
          </div>
        </div>
        <nav className="workflow-run-steps" aria-label="工作流应用列表">
          {steps.map((step, index) => (
            <button
              key={step.key}
              type="button"
              className={`workflow-run-step ${selectedStep?.key === step.key ? 'active' : ''}`}
              onClick={() => selectStep(step)}
            >
              <span className="workflow-run-step-number">{index + 1}</span>
              <span className="workflow-run-step-icon">
                {step.application.application_icon || '◈'}
              </span>
              <span className="workflow-run-step-text">
                <strong>{step.name || step.application.application_name}</strong>
                <small>{step.application.application_description || '打开应用并手动操作'}</small>
              </span>
            </button>
          ))}
        </nav>
      </aside>

      <main className="workflow-run-content">
        {selectedStep ? (
          <>
            <header className="workflow-run-header">
              <div>
                <span className="workflow-run-step-icon">
                  {selectedStep.application.application_icon || '◈'}
                </span>
                <strong>{selectedStep.name || selectedStep.application.application_name}</strong>
              </div>
              <div className="workflow-run-header-actions">
                <Button
                  icon={<ExportOutlined />}
                  onClick={() => window.open(
                    workflowApplicationPath(selectedStep, false, id, manualRun),
                    '_blank',
                    'noopener,noreferrer',
                  )}
                >
                  新窗口打开
                </Button>
                <Button
                  type="primary"
                  icon={<CheckOutlined />}
                  loading={completing}
                  disabled={manualRun?.status !== 'running'}
                  onClick={completeRun}
                >
                  {manualRun?.status === 'succeeded' ? '已完成' : '完成本次执行'}
                </Button>
              </div>
            </header>
            <div className="workflow-run-application">
              {steps.filter((step) => openedKeys.includes(step.key)).map((step) => (
                <iframe
                  key={step.key}
                  className={`workflow-run-application-frame ${
                    selectedStep.key === step.key ? 'active' : ''
                  }`}
                  src={workflowApplicationPath(step, true, id, manualRun)}
                  title={step.name || step.application.application_name}
                  aria-hidden={selectedStep.key !== step.key}
                />
              ))}
            </div>
          </>
        ) : (
          <Empty description="该工作流还没有应用" />
        )}
      </main>
    </div>
  );
}
