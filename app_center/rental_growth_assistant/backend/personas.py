"""Editable starter audiences, never confirmed requirements of an actual lead."""
from uuid import NAMESPACE_URL, uuid5

from .models import Persona
from .schemas import Requirements, validated


# Stable keys preserve edits and archives when defaults are initialized again.
BUILTIN_PERSONAS = (
    ('budget-solo', '预算优先的独居租客', {
        'rental_type': 'whole',
        'needs': '希望独立居住，控制每月住房总支出，满足日常休息、做饭和收纳需要。',
        'concerns': '月租之外的物业、水电、网络和服务费用；押付方式；家具配置；为了预算需要接受的面积、楼层或噪声取舍。',
    }),
    ('commuter', '通勤优先的上班族', {
        'needs': '围绕工作地点选择住所，关注交通连接、日常采购和下班后的休息环境。',
        'concerns': '真实交通线路与距离、换乘情况、末班车、夜间回家路线和噪声。工作地点与可接受通勤范围需确认，不承诺通勤时长。',
    }),
    ('couple', '准备一起整租的情侣', {
        'rental_type': 'whole',
        'needs': '两人共同居住，兼顾双方通勤、做饭、衣物收纳与各自的休息空间。',
        'concerns': '两人共同预算、厨房与卫浴配置、收纳空间、居住人数限制、共同签约及退租约定。',
    }),
    ('pet', '需要养宠的租客', {
        'must_have': ['可养宠'],
        'needs': '带宠物一起入住，关心宠物活动空间、通风、清洁和门窗防护条件。',
        'concerns': '房东是否明确同意宠物种类及数量、额外押金或清洁费、家具损坏责任、邻里与公共区域管理要求。',
    }),
    ('housemates', '与朋友合租的租客', {
        'rental_type': 'shared',
        'needs': '与朋友合租分摊支出，希望各有休息空间，并明确公共区域的使用方式。',
        'concerns': '每人费用及分摊规则、卧室差异、门锁与隐私、作息、公共区域卫生、签约主体及室友提前退租的处理。',
    }),
    ('family', '重视日常生活的家庭租客', {
        'rental_type': 'whole',
        'needs': '多人长期共同居住，关注卧室安排、做饭洗衣、储物和附近生活配套。',
        'concerns': '居住人数、楼层与电梯、噪声、门窗防护、物业维护、租期稳定性及续租条款；具体家庭成员需求需确认。',
    }),
    ('remote-work', '需要居家办公的租客', {
        'needs': '在家处理日常工作，希望能安排办公桌、线上会议和休息空间。',
        'concerns': '白天及夜间噪声、采光、插座、网络接入和费用、桌面空间、夏冬季能耗；网络质量与隔音效果需核实。',
    }),
    ('short-stay', '短期过渡的租客', {
        'needs': '因工作调动、搬家或装修等原因临时居住，希望入住方便，减少搬运及置办家具。',
        'concerns': '是否接受实际所需租期、起租与退租日期、短租价格、押金退还、提前解约条款、家具家电及清洁交接。',
    }),
)


def ensure_builtin_personas(ownership):
    """Caller holds its preferences row lock; UUID uniqueness also guards retries."""
    scope = f"rental-growth-assistant:{ownership['organization_id']}:{ownership['application'].pk}:{ownership['owner'].pk}"
    entries = [(uuid5(NAMESPACE_URL, f'{scope}:persona:{key}'), title, data)
               for key, title, data in BUILTIN_PERSONAS]
    existing = set(Persona.objects.filter(**ownership, pk__in=[pk for pk, _, _ in entries])
                   .values_list('pk', flat=True))
    created = 0
    for pk, title, data in entries:
        if pk not in existing:
            _, added = Persona.objects.get_or_create(pk=pk, **ownership, defaults={
                'title': title, 'status': 'active', 'data': validated(Requirements, data),
            })
            created += int(added)
    return created
