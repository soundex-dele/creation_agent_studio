import { structuredStreamText } from '@/lib/structuredStreamText';

/** Render incomplete structured model output as readable copy, without exposing
 * JSON punctuation, record identifiers or a transient parse error to the user. */
const labels: Record<string, string> = {
  titles: '候选标题', cover: '封面短句', body: '发布文案', tags: '话题建议', pages: '实拍图排版',
  caption: '上图文字', layout: '排版／户型', script: '口播稿', shots: '镜头建议', checks: '待核实信息',
  topics: '选题计划', title: '标题', angle: '表达角度', date: '日期', answer: '回复与建议',
  questions: '下一步待确认', requirements: '需求草稿', budget_min: '最低预算', budget_max: '最高预算',
  city: '城市', districts: '片区', rental_type: '出租方式', move_in: '入住日期', must_have: '必要条件',
  needs: '生活需求', concerns: '关注点',
};

export function rentalStreamText(raw: string): string {
  return structuredStreamText(raw, labels, { whole: '整租', shared: '合租' });
}
