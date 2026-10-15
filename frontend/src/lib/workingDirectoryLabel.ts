/** Compact display only: never use this label as a filesystem path. */
export function workingDirectoryLabel(path: string, { folderOnly = false } = {}): string {
  if (/^(?:[a-z]:)?[\\/]+$/i.test(path)) return path;
  // Count wide characters twice so Chinese folder names compact sooner as well.
  const displayLength = Array.from(path).reduce(
    (length, char) => length + (char.codePointAt(0)! > 0xff ? 2 : 1), 0,
  );
  if (!folderOnly && displayLength <= 40) return path;
  return path.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || path;
}
