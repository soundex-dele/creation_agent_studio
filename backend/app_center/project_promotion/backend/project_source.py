"""Read-only, model-directed project exploration using the repository reader."""
from copy import deepcopy
from pathlib import PurePosixPath
from shutil import which
from rest_framework import serializers as s
from rest_framework.exceptions import ValidationError
from app_center.repo_explainer.backend.sources import from_local, fingerprint
from app_center.repo_explainer.backend.exploration import explore
from .schemas import Strict, CaseData, text, validated

INSTRUCTION = '''将本次已读取的项目证据整理为1至6条不同场景的宣传案例草稿，不为凑数量编造功能。
目标读者是内容创作者和小团队，优先考虑公众号内容生产、多平台改编、重复工作自动化，按实际能力选。
只返回 {analysis:"探索结论与覆盖限制",cases:[{title:"案例标题",evidence_ids:["本次证据编号"],
data:{audience:"读者",problem:"问题",solution:"方案",steps:"可演示步骤",implemented:"有实际实现代码支持的能力",
conditions:"使用条件与静态分析限制",extensions:"尚未实现的扩展建议",category:"wechat|multichannel|automation"}}]}。
无足够证据时返回 {insufficient_reason:"具体原因"}。每条须引用1至12段已读证据，不得编造引用编号或来源路径。
implemented 只能由真实实现代码支持，文档、类型声明、接口、测试、TODO、示例占位不能单独证明实现。
仅有文档时 implemented 留空，在 conditions 中注明待核实。extensions 不得混入已实现能力。
所有 data 字段是字符串。每项控制在1500字内。不要返回客户名称、效果数字、收益、素材URL或原始凭据。
未运行项目，不得声称效果已验证。证据来源和演示案例类型由服务器附加，无需填写 evidence、assets 或 case_type。
'''


class ProjectCase(Strict):
    title = s.CharField(max_length=200)
    evidence_ids = s.ListField(child=s.CharField(max_length=40), min_length=1, max_length=12)
    data = CaseData()


class ProjectResult(Strict):
    analysis = text(10000)
    cases = ProjectCase(many=True, allow_empty=False, max_length=6)


def implementation_candidate(path):
    """Reject evidence which cannot by itself substantiate implemented behavior."""
    name = path.lower()
    parts = PurePosixPath(name).parts
    return (PurePosixPath(name).suffix in {'.py', '.js', '.jsx', '.ts', '.tsx', '.vue', '.svelte', '.go', '.rs',
            '.java', '.kt', '.swift', '.c', '.cpp', '.cc', '.cs', '.rb', '.php', '.html', '.css', '.scss', '.sql', '.sh', '.ps1'}
        and not any(p in {'tests', 'test', '__tests__', 'fixtures', '__mocks__', 'examples', 'docs'} for p in parts)
        and not PurePosixPath(name).name.startswith('test_')
        and not any(marker in PurePosixPath(name).name for marker in ('.test.', '.spec.'))
        and not name.endswith(('.d.ts', '.test.ts', '.test.tsx', '.spec.ts', '.spec.tsx', '_test.go', '_test.py')))


def validate_project_result(value, source):
    if isinstance(value, dict) and value.get('insufficient_reason'):
        reason = s.CharField(max_length=2000).run_validation(value['insufficient_reason'])
        raise ValueError('项目资料不足：' + reason)
    result = validated(ProjectResult, value)
    evidence = source['evidence']
    titles = set()
    for item in result['cases']:
        if item['title'] in titles:
            raise ValidationError('案例标题重复，请根据不同真实场景整理。')
        titles.add(item['title'])
        identifiers = list(dict.fromkeys(item.pop('evidence_ids')))
        if any(identifier not in evidence for identifier in identifiers):
            raise ValidationError('案例引用了未读取的项目证据。')
        chosen = {key: deepcopy(evidence[key]) for key in identifiers}
        data = item['data']
        if data['implemented'].strip() and not any(implementation_candidate(row['path']) for row in chosen.values()):
            raise ValidationError('已实现能力需要实际实现代码依据，不能仅引用文档或测试。')
        data['case_type'] = 'demo'
        data['assets'] = []
        # Paths/line numbers and immutable hashes are supplied by the reader, not the model.
        citations = '\n'.join(f"{row['path']}:{row['start']}-{row['end']}（SHA256 {row['sha256']}）" for row in chosen.values())
        data['evidence'] = '项目源码静态阅读，未运行验证。\n' + citations
        data['conditions'] = ('仅依据所列源码与文档片段；未运行项目，效果与部署状态待人工核实。\n' + data['conditions'])[:10000]
        item['data'] = validated(CaseData, data)
        item['source_snapshot'] = {**deepcopy(source), 'evidence': chosen}
    return result


def explore_project(task, model, progress, check):
    progress('读取项目工作区，创建只读文本快照')
    if not which('git'):
        raise ValueError('执行服务未找到 Git。请将 Git 安装目录加入后端和执行 worker 的 PATH 后重试。')
    files, ingestion, origin = from_local(task.snapshot['request']['project_path'], task.owner, check)
    check()
    direction = '寻找适合内容创作者和小团队的真实功能案例，追踪实际实现与使用条件。' + task.snapshot['request']['instruction']
    def exploration_model(instruction, content):
        instruction = instruction.replace('5个有源码依据的选题', '有源码依据的宣传案例').replace('5个选题', '宣传案例').replace('选题', '案例')
        try:
            return model(instruction, content)
        except (ValueError, KeyError, TypeError) as exc:
            # Model/configuration errors are task failures, not invalid read actions
            # for the explorer to retry indefinitely.
            raise RuntimeError('项目探索模型调用失败。') from exc
    evidence, coverage = explore(files, exploration_model, progress, direction, check)
    if not evidence:
        raise ValueError('项目资料不足：没有选出可引用的源码或文档片段。')
    evidence = {key: {**row, 'sha256': files[row['path']]['sha256']} for key, row in evidence.items()}
    source = dict(origin=origin, digest=fingerprint({path: row['sha256'] for path, row in files.items()}),
        coverage=coverage, ingestion={k: v for k, v in ingestion.items() if k != 'excluded'}, evidence=evidence)
    check()
    progress('根据项目证据整理案例草稿')
    value = model(INSTRUCTION, {'方向': task.snapshot['request']['instruction'], '品牌资料': task.snapshot.get('brand'),
                               '证据': list(evidence.values()), '覆盖范围': coverage})
    # One format repair preserves the same frozen evidence; never re-read changed files.
    try:
        result = validate_project_result(value, source)
    except ValidationError as exc:
        progress('核对案例引用并修正结果格式')
        value = model(INSTRUCTION, {'证据': list(evidence.values()), '覆盖范围': coverage,
            '方向': task.snapshot['request']['instruction'], '品牌资料': task.snapshot.get('brand'),
            '上次校验问题': str(exc)[:2000]})
        result = validate_project_result(value, source)
    check()
    task.snapshot['project_source'] = {key: val for key, val in source.items() if key != 'evidence'}
    return result
