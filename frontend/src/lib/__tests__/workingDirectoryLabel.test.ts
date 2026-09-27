import { expect, it } from 'vitest';
import { workingDirectoryLabel } from '../workingDirectoryLabel';

it.each([
  ['', ''],
  ['/', '/'],
  ['C:\\', 'C:\\'],
  ['/home/user/project', '/home/user/project'],
  ['a'.repeat(40), 'a'.repeat(40)],
  ['/Users/owner/workspace/projects/creation_agent_studio', 'creation_agent_studio'],
  ['/Users/owner/workspace/projects/creation_agent_studio/', 'creation_agent_studio'],
  ['C:\\Users\\owner\\workspace\\projects\\creation_agent_studio\\', 'creation_agent_studio'],
  ['\\\\server\\shared-workspace\\projects\\creation_agent_studio', 'creation_agent_studio'],
  ['/工作目录/这是一个很长的中文文件夹名称/我的项目', '我的项目'],
  ['a'.repeat(60), 'a'.repeat(60)],
])('formats %s without changing short paths or roots', (path, expected) => {
  expect(workingDirectoryLabel(path)).toBe(expected);
});
