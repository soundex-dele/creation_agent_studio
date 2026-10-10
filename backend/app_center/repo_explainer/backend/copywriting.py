"""Load the configured writing Skill; repository material never selects a path."""
import hashlib
from pathlib import Path
from django.conf import settings

SKILLS = {'video': 'write-short-video-copy', 'image_text': 'write-image-text-copy'}


def load_copy_skill(kind):
    slug = SKILLS[kind]
    root = Path(settings.CODEX_SKILLS_DIRECTORY).expanduser().resolve()
    # Installed packages may be directory symlinks/junctions. Trust only these
    # two administrator-configured packages, then bound the entrypoint to it.
    package = (root / slug).resolve()
    path = (package / 'SKILL.md').resolve()
    if not path.is_relative_to(package):
        raise ValueError(f'技能路径无效：{slug}。')
    try:
        with path.open('rb') as handle:
            raw = handle.read(100001)
        if len(raw) > 100000:
            raise ValueError(f'技能文件过大：{slug}。')
        content = raw.decode('utf-8-sig')
    except (OSError, UnicodeError) as exc:
        raise ValueError(f'无法读取写作技能 {slug}，请在 CODEX_SKILLS_DIRECTORY 中安装对应 SKILL.md。') from exc
    if not content.strip():
        raise ValueError(f'写作技能 {slug} 内容为空。')
    return content, {'slug': slug, 'sha256': hashlib.sha256(raw).hexdigest()}


def copy_instruction(kind, skill):
    return f'''使用以下已安装的 {SKILLS[kind]} Skill 完成文案创作：
<writing_skill>
{skill}
</writing_skill>
本次用户明确的交付范围优先于技能的默认交付：只生成{"短视频口播文案" if kind == "video" else "图文作品文案"}。
不要生成分镜、时间轴、画面描述、图片、HTML 或配图方案；不调用工具。
视频 paragraphs 是连贯口播的自然段，不是分镜，不按镜头拆段；图文 paragraphs 是逐页上图文字，heading 可标明页名。
按 Skill 设计标题、封面、正文、发布配文，保留限定和证据。不冒充亲测。缺失操作在 notes 标待补充。
只引用所选功能及其证据，每个正文段填写 feature_ids 和 evidence_ids。
整份 JSON 建议 6000 字符以内。返回且仅返回以下结构：
{{"schema_version":2,"kind":"{kind}","title":"推荐标题","cover":"封面短句","alternatives":["备选标题"],
"paragraphs":[{{"heading":"段落或页名，可为空","text":"可直接使用的正文","feature_ids":["f1"],"evidence_ids":["e1"]}}],
"publish_copy":"发布配文","notes":["必要的待核事实"]}}。
正文与发布配文均需有资料依据，不能编造功能、数据或经历。仅交付文案，不制作成品。'''
