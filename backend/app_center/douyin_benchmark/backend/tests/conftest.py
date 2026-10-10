import pytest


@pytest.fixture
def skill(settings, tmp_path):
    settings.CODEX_SKILLS_DIRECTORY = str(tmp_path)
    root = tmp_path / 'wechat-viral-article'
    (root / 'references').mkdir(parents=True)
    (root / 'templates').mkdir()
    (root / 'SKILL.md').write_text('写作技能正文 @references/writing.md', encoding='utf-8')
    (root / 'references/writing.md').write_text('写作资料 templates/outline.md', encoding='utf-8')
    (root / 'templates/outline.md').write_text('大纲模板 references/writing.md', encoding='utf-8')
    return root
