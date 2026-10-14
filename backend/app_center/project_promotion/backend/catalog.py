"""Editorial material taxonomy shared by validation and generation prompts."""
MATERIAL_CATALOG = {
    'overview': ('项目概览', '整个项目的定位、应用或模块构成、协作关系与整体能力；不能用单个应用的介绍代替'),
    'application_overview': ('应用概览', '项目内一个具体应用的用途、适用用户、主要功能及输入输出；标题明确应用名称，不代表整个项目'),
    'positioning': ('项目定位', '解决的核心问题、价值主张与定位；不编造竞品优劣'),
    'audience': ('适用人群', '适合的用户、角色及使用前提，不虚构已有客户'),
    'scenario': ('应用场景', '适用的业务情境与任务；设想场景要标注，不冒充真实案例'),
    'feature': ('功能资料', '单项功能做什么、输入输出及能力范围'),
    'workflow': ('工作流程', '多个步骤或功能怎样协作完成任务'),
    'case': ('使用案例', '具体问题、解决过程和结果；演示与真实客户案例分开'),
    'artifact': ('成果样本', '项目实际产出的内容或文件样本，不编造产物或效果'),
    'quickstart': ('快速上手', '首次使用的准备条件与最短操作路径，只整理操作事实'),
    'integration': ('集成对接', '与外部工具、接口和数据的连接方式及条件'),
    'customization': ('定制扩展', '现有配置、插件和二次开发能力；未实现扩展另列'),
    'architecture': ('技术实现', '模块职责、关键设计与技术协作方式'),
    'deployment': ('部署运维', '运行环境、部署方式、维护和故障处理条件'),
    'security': ('安全隐私', '权限、数据处理与隐私机制；不把机制等同安全认证或合规结论'),
    'performance': ('性能容量', '已有性能与容量资料；区分设计目标和实测，缺少数据时不编造指标'),
    'boundaries': ('使用边界', '已知限制、不支持的情况及适用前提'),
    'cost': ('成本资源', '所需软硬件、外部服务与资源消耗；未知费用留空，不臆测价格'),
    'release': ('版本变更', '有变更记录的新增、调整与修复'),
    'development': ('开发记录', '已有开发过程、决策和经验记录，不臆测作者动机'),
    'roadmap': ('未来规划', '已有计划、TODO 或规划声明，明确尚未实现，不承诺交付日期'),
}
MATERIAL_TYPES = list(MATERIAL_CATALOG)
MATERIAL_GUIDE = '\n'.join(f'{key} {label}：{description}。' for key, (label, description) in MATERIAL_CATALOG.items())
OVERVIEW_SCOPE_INSTRUCTION = '项目与应用是不同层级：overview 项目概览只介绍当前整个项目，按项目汇总为至多一份，不按应用拆成多份项目概览；application_overview 应用概览介绍项目内一个具体应用，每份写明应用名称。应用概览可包含该应用的多项功能，单项功能资料仍归 feature。不能把应用层面的描述扩大为整个项目的全部能力。选题方向 overview 项目介绍面向整个项目，application_overview 应用介绍面向一个具体应用。项目路径只决定读取范围，不决定素材介绍的对象层级。'
BROAD_FOCUSES = {
    'all': ('综合介绍', '全面梳理项目，根据实际资料选择有价值的素材类型'),
    'user': ('用户功能与流程', '侧重用户角色、功能、使用场景和完整流程'),
    'technical': ('技术实现与设计', '侧重架构、集成、扩展、运行条件及技术边界'),
    'business': ('业务定位与交付条件', '侧重定位、适用对象、交付方式和资源条件'),
}
EXPLORATION_FOCUSES = {**BROAD_FOCUSES, **MATERIAL_CATALOG}


def allowed_material_types(focus):
    return [focus] if focus in MATERIAL_CATALOG else list(MATERIAL_TYPES)


def focus_instruction(focus):
    label, description = EXPLORATION_FOCUSES.get(focus, BROAD_FOCUSES['all'])
    text = f'本次探索侧重：{label}。{description}。'
    if focus in MATERIAL_CATALOG:
        text += f'仅输出 material_type={focus} 的素材，所有 cases 必须属于该分类；不要附带其他分类，也不要把无关内容换标签充数。相关背景写入该素材的必要说明，模块覆盖概况写入 analysis。没有该类资料时提交 insufficient_reason，不用其他分类替代。'
    else:
        text += '本次为综合视角，可根据实际资料输出多种素材分类。'
    return text + '资料不足时在 analysis 说明缺口，不编造内容或为了覆盖分类增加阅读深度。全面概览仍覆盖主要模块，指定方向深挖仍以用户填写的方向限定范围。'
