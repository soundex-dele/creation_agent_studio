export type StudyMethodCategory = 'prepare' | 'class' | 'practice' | 'review' | 'exam';
export type StudyMethodAction = 'mistakes' | 'review' | 'tutor';

export interface StudyMethodStep {
  id: string;
  title: string;
  description: string;
  check: string;
}

export interface StudyMethodGuide {
  id: string;
  category: StudyMethodCategory;
  title: string;
  subtitle: string;
  duration: string;
  outcome: string;
  principle: string;
  steps: StudyMethodStep[];
  pitfalls: string[];
  action: { target: StudyMethodAction; label: string };
}

export const studyMethodCategories: Array<{
  value: 'all' | StudyMethodCategory;
  label: string;
}> = [
  { value: 'all', label: '全部' },
  { value: 'prepare', label: '课前' },
  { value: 'class', label: '课堂' },
  { value: 'practice', label: '练习' },
  { value: 'review', label: '复习' },
  { value: 'exam', label: '考试' },
];

export const studyMethodGuides: StudyMethodGuide[] = [
  {
    id: 'mistake-book',
    category: 'practice',
    title: '如何做一本真正有用的错题集',
    subtitle: '不抄满答案，把每道错题变成下一次会做',
    duration: '每题 3–5 分钟',
    outcome: '减少重复犯错',
    principle: '错题集的价值不是“收藏”，而是让你在忘记之前再次独立做对。记录越轻，重做越多，效果越好。',
    steps: [
      {
        id: 'collect',
        title: '只收值得再做的题',
        description: '收录第一次暴露的知识漏洞、重复出错题和方法典型题。单纯看错数字但方法完全会的题，可以只标记粗心。',
        check: '我能说出为什么值得留下',
      },
      {
        id: 'cause',
        title: '只选一个主要错因',
        description: '从概念、公式、审题、计算、方法、表达中选最关键的一项，不写长篇反思。',
        check: '我已经找到最主要的失分点',
      },
      {
        id: 'redo',
        title: '遮住答案，完整重做',
        description: '先独立写到卡住的位置，再看提示。不要一边看解析一边抄，那只会制造“我好像会了”的错觉。',
        check: '我在不看答案时重新做过',
      },
      {
        id: 'turning-point',
        title: '记住关键转折，不抄整篇解析',
        description: '只保留一句真正改变解法的话，例如“看到恒成立，先分离参数”或“先检查定义域”。',
        check: '我能用一句话说出关键方法',
      },
      {
        id: 'spaced-review',
        title: '按 1、3、7、14 天再做',
        description: '每次都从空白开始。做对就拉长间隔，做错就回到第 1 天，而不是把题永远放在本子里。',
        check: '我已经安排下一次复习',
      },
      {
        id: 'variant',
        title: '用一道同类题验收',
        description: '原题会背不等于掌握。换数字、换问法或换情境仍能做对，才算真正归档。',
        check: '我能独立做对一道同类题',
      },
    ],
    pitfalls: ['把错题集做成抄写本', '所有错题都收，最后不再翻', '只看解析，不遮住答案重做', '原题记住答案就当作掌握'],
    action: { target: 'mistakes', label: '去整理一道错题' },
  },
  {
    id: 'preview-10',
    category: 'prepare',
    title: '10 分钟有效预习',
    subtitle: '预习不是提前学完，而是带着问题去听课',
    duration: '课前 10 分钟',
    outcome: '听课更有重点',
    principle: '预习的目标是建立地图并暴露疑问。提前把所有内容学会既耗时，也会降低课堂注意力。',
    steps: [
      { id: 'scan', title: '先扫标题和小结', description: '只看章节标题、黑体词、图表和本节小结，先知道这节课在解决什么。', check: '我能说出本节主题' },
      { id: 'example', title: '看懂一个例子', description: '找教材中最基础的例题，只判断每一步在做什么，不追求举一反三。', check: '我能复述例题的大致路径' },
      { id: 'mark', title: '标出两个卡点', description: '用问号标记看不懂的概念或步骤，最多两个，避免把整页都画满。', check: '我带着明确问题进课堂' },
      { id: 'predict', title: '猜一猜老师会讲什么', description: '根据标题预测重点、难点或易错点，课堂中验证自己的判断。', check: '我做过一次重点预测' },
    ],
    pitfalls: ['从第一页开始逐字读', '遇到不会立刻查到完全弄懂', '预习时间比正式学习还长'],
    action: { target: 'tutor', label: '问老师一个预习问题' },
  },
  {
    id: 'listen-class',
    category: 'class',
    title: '课堂上怎么听、怎么记',
    subtitle: '少抄板书，多跟住老师的思路变化',
    duration: '一节课',
    outcome: '课堂当场消化',
    principle: '听课最稀缺的是注意力。笔记只记录思路转折、自己没想到的地方和老师强调的边界条件。',
    steps: [
      { id: 'goal', title: '开头先抓学习目标', description: '弄清这节课结束后要会解释什么、会解决什么题。', check: '我知道本节课的目标' },
      { id: 'follow', title: '跟住“为什么下一步这样做”', description: '比起抄结果，更关注老师从条件走到结论的依据。', check: '我能说出关键步骤的理由' },
      { id: 'note', title: '只记三个信号', description: '记录思路转折、易错边界和自己没想到的方法，其余内容课后看教材。', check: '我的笔记有重点而不是全文' },
      { id: 'recall', title: '下课后闭眼回忆 1 分钟', description: '不翻笔记，说出本节三个关键词和一条方法。想不起来的地方就是复习入口。', check: '我完成了一次课后回忆' },
    ],
    pitfalls: ['追求板书一字不漏', '听懂了就不做课后回忆', '卡在一个细节后放弃后半节课'],
    action: { target: 'review', label: '开始一次课后复习' },
  },
  {
    id: 'spaced-review',
    category: 'review',
    title: '不靠反复看的复习法',
    subtitle: '先回忆，再核对；越费力的提取越能记住',
    duration: '每次 10–20 分钟',
    outcome: '记得更久',
    principle: '直接重读会产生熟悉感，但熟悉不等于会用。先从大脑里提取，再对照纠正，记忆才会变牢。',
    steps: [
      { id: 'close', title: '先合上资料', description: '用白纸、口述或脑中回放，写出能想起的结构和关键词。', check: '我先回忆而不是先看书' },
      { id: 'compare', title: '打开资料核对缺口', description: '只补漏掉或记错的部分，不从头重抄。', check: '我找到了具体缺口' },
      { id: 'question', title: '用一道题检验能否调用', description: '知识能做题、能解释、能辨析，才说明不只是眼熟。', check: '我完成了一次主动调用' },
      { id: 'space', title: '逐步拉长复习间隔', description: '建议当天、3 天、7 天、14 天复习；做错就缩短间隔。', check: '我知道下一次何时复习' },
    ],
    pitfalls: ['从头到尾重复阅读', '只划重点不做回忆', '一次背很久，之后不再复习'],
    action: { target: 'review', label: '查看今天到期复习' },
  },
  {
    id: 'targeted-practice',
    category: 'practice',
    title: '刷题不刷数量，刷反馈',
    subtitle: '每组题只训练一个目标，做完马上调整',
    duration: '每组 20–30 分钟',
    outcome: '练习更有针对性',
    principle: '连续做很多相似题容易形成机械反应。明确目标、限制时间、混合题型并及时反馈，才能迁移到考试。',
    steps: [
      { id: 'target', title: '一组题只定一个目标', description: '例如“判断函数单调性”或“英语阅读定位”，不要笼统写“刷一套卷”。', check: '本组训练目标足够具体' },
      { id: 'limit', title: '设题量和时间上限', description: '5–8 题或 25 分钟即可，结束后必须留时间复盘。', check: '我设好了停止条件' },
      { id: 'confidence', title: '做完先标信心', description: '答案揭晓前标记“确定、犹豫、蒙的”，蒙对的题也要复盘。', check: '我区分了会做和猜对' },
      { id: 'feedback', title: '用错因决定下一组', description: '概念错就回知识卡，方法错就看例题，计算错就做短时专项。', check: '下一组练习由反馈决定' },
    ],
    pitfalls: ['只记录正确率，不看猜对的题', '一口气刷很久不复盘', '每次都做最熟悉的题型'],
    action: { target: 'tutor', label: '让老师出一组针对题' },
  },
  {
    id: 'exam-review',
    category: 'exam',
    title: '考后复盘四步法',
    subtitle: '不纠结分数，把失分变成下一阶段行动',
    duration: '考后 30 分钟',
    outcome: '找到最值得提分的地方',
    principle: '复盘不是把所有错题再讲一遍，而是识别反复出现的失分模式，并只选一两个下阶段重点。',
    steps: [
      { id: 'recover', title: '先还原考场过程', description: '标记不会、会但做错、时间不够和表达丢分，不急着看答案。', check: '我分清了失分发生在哪一步' },
      { id: 'classify', title: '把失分归为三类', description: '知识漏洞、解题流程、考试状态。不同原因需要不同训练。', check: '每个主要失分都有归类' },
      { id: 'priority', title: '只选两个优先问题', description: '优先处理频繁出现、分值高且短期可改的问题。', check: '我选出了两个改进重点' },
      { id: 'verify', title: '一周后用题目验收', description: '安排同类题或小测，验证问题是否真的解决，而不是只写计划。', check: '我安排了具体的验收方式' },
    ],
    pitfalls: ['只盯总分和排名', '每个问题都想同时解决', '写很多反思但没有验收题'],
    action: { target: 'mistakes', label: '整理本次考试错题' },
  },
];

export function recommendStudyMethod(mistakeCount: number, dueReviewCount: number) {
  if (mistakeCount > 0) return 'mistake-book';
  if (dueReviewCount > 0) return 'spaced-review';
  return 'preview-10';
}

export function methodCompletion(completedStepIds: string[], guide: StudyMethodGuide) {
  if (!guide.steps.length) return 0;
  const completed = guide.steps.filter((step) => completedStepIds.includes(step.id)).length;
  return Math.round((completed / guide.steps.length) * 100);
}
