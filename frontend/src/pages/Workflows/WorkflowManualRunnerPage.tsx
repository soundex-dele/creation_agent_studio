import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Empty, Spin, message } from 'antd';
import {
  ArrowLeftOutlined,
  CheckOutlined,
  ExportOutlined,
} from '@ant-design/icons';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import WorkflowBrandPicker, { emptyWorkflowBrand, workflowBrandRequest } from '@/components/WorkflowBrandPicker';
import type { BrandConfig } from '@/services/brandLibrary';
import { formErrorMessage } from '@/lib/formPresets';
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
  const [error, setError] = useState('');
  const [brand, setBrand] = useState(emptyWorkflowBrand);
  const [startRequested, setStartRequested] = useState(false);
  const [opening, setOpening] = useState(false);
  const [completing, setCompleting] = useState(false);
  const openingManualSession = useRef(false);

  useEffect(() => {
    if (!id) return;
    const controller = new AbortController();
    void api.get<Workflow>(`/workflows/${id}/`, undefined, { signal: controller.signal })
      .then((value) => { if (!controller.signal.aborted) { setWorkflow(value); setSelectedKey(value.steps?.[0]?.key || ''); } })
      .catch(() => { if (!controller.signal.aborted) setError('工作流加载失败'); });
    return () => controller.abort();
  }, [id]);

  const hasBrand = workflow?.steps?.some((step) => (step.application.default_config.brand_reference as BrandConfig | undefined)?.enabled);
  useEffect(() => {
    if (!id || !workflow || manualRun || openingManualSession.current || (hasBrand && !startRequested && !resumeRunId)) return;
    openingManualSession.current = true; setOpening(true); setError('');
    void api.post<RunResource>(`/workflows/${id}/manual-session/`, {
      action: 'open', ...(resumeRunId ? { run_id: resumeRunId } : { brand_context: workflowBrandRequest(brand) }),
    }).then((run) => {
      setManualRun(run);
      if (!resumeRunId) navigate(`/workflows/${id}/manual?runId=${run.id}`, { replace: true });
    }).catch((reason: any) => {
      openingManualSession.current = false; setStartRequested(false);
      setError(formErrorMessage(reason, '无法开始执行，请检查品牌选择后重试。'));
    }).finally(() => setOpening(false));
  }, [id, workflow, manualRun, hasBrand, startRequested, resumeRunId, brand, navigate]);

  const steps = workflow?.steps ?? [];
  const selectedStep = steps.find((step) => step.key === selectedKey) ?? steps[0];

  const selectStep = async (step: WorkflowStep) => {
    if (step.key === selectedKey) return;
    if (id && manualRun) {
      try {
        const refreshedRun = await api.post<RunResource>(`/workflows/${id}/manual-session/`, {
          action: 'open',
          run_id: manualRun.id,
        });
        setManualRun(refreshedRun);
      } catch (reason: any) {
        message.error(reason?.response?.data?.detail || '无法切换工作流应用');
        return;
      }
    }
    setSelectedKey(step.key);
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

  if (error && !workflow) {
    return <div className="workflow-run-loading"><Alert type="error" showIcon message={error} /></div>;
  }
  if (!workflow) {
    return <div className="workflow-run-loading"><Spin size="large" /></div>;
  }

  if (!manualRun) return <div className="workflow-manual-setup app-scroll-page">
    <h2>{workflow.name}</h2><p>选择本次品牌资料，然后进入各应用。可以不引用品牌资料。</p>
    {error && <Alert type="error" message={error} />}
    <WorkflowBrandPicker workflow={workflow} value={brand} onChange={setBrand} />
    <Button type="primary" loading={opening} onClick={() => { setError(''); setStartRequested(true); }}>开始手动执行</Button>
  </div>;

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
              onClick={() => void selectStep(step)}
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
              <iframe
                key={selectedStep.key}
                className="workflow-run-application-frame active"
                src={workflowApplicationPath(selectedStep, true, id, manualRun)}
                title={selectedStep.name || selectedStep.application.application_name}
              />
            </div>
          </>
        ) : (
          <Empty description="该工作流还没有应用" />
        )}
      </main>
    </div>
  );
}
