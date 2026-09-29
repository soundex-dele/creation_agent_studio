import ts from 'typescript';

const imports = new Set(['react', 'remotion', './assets']);
const forbidden = new Set(['require', 'eval', 'Function', 'globalThis', 'window', 'document', 'parent', 'top', 'self', 'frames', 'location', 'navigator', 'fetch', 'XMLHttpRequest', 'WebSocket', 'Worker', 'SharedWorker', 'WebAssembly', 'process', 'global', 'localStorage', 'sessionStorage', 'indexedDB', 'setTimeout', 'setInterval', 'requestAnimationFrame', 'Date', 'performance', 'constructor', '__proto__', 'prototype', 'dangerouslySetInnerHTML', 'staticFile', 'useEffect', 'useLayoutEffect']);

// Restrict generated compositions, never the trusted Player/render entrypoints.
// This is a capability guard in addition to the isolated preview CSP, not an OS sandbox.
export function validateSource(source) {
  if (typeof source !== 'string' || source.length > 150000) throw new Error('动画源码为空或超过 150000 字符。');
  const tree = ts.createSourceFile('Animation.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  if (tree.parseDiagnostics.length) throw new Error(ts.flattenDiagnosticMessageText(tree.parseDiagnostics[0].messageText, '\n'));
  function visit(node) {
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier) {
      if (!ts.isStringLiteral(node.moduleSpecifier) || !imports.has(node.moduleSpecifier.text)) throw new Error('只允许导入 react、remotion 和 ./assets。');
    }
    if (ts.isImportEqualsDeclaration(node) || ts.isImportTypeNode(node) || node.kind === ts.SyntaxKind.ImportKeyword) throw new Error('不允许动态导入。');
    if (ts.isIdentifier(node) && forbidden.has(node.text)) throw new Error(`不允许在动画中使用 ${node.text}。`);
    if (ts.isPropertyAccessExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 'Math' && node.name.text === 'random') throw new Error('使用 remotion.random(seed)，不能使用 Math.random。');
    if ((ts.isStringLiteralLike(node) || ts.isNoSubstitutionTemplateLiteral(node)) && /(?:https?:|file:|javascript:|\/\/|@import|@font-face)/i.test(node.text)) throw new Error('动画只能引用归档素材，不能加载远程资源。');
    if (ts.isElementAccessExpression(node) && ts.isStringLiteralLike(node.argumentExpression) && forbidden.has(node.argumentExpression.text)) throw new Error('不允许访问全局执行能力。');
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const tag = node.tagName.getText(tree).toLowerCase();
      if (['script', 'iframe', 'object', 'embed', 'link', 'style', 'form', 'a', 'audio', 'video'].includes(tag)) throw new Error(`动画不能包含 ${tag} 标签。`);
    }
    if (ts.isPropertyAssignment(node) && /^(animation|transition)/.test(node.name.getText(tree))) throw new Error('动效必须由 useCurrentFrame 驱动，不能使用 CSS animation/transition。');
    ts.forEachChild(node, visit);
  }
  visit(tree);
  if (!/export\s+default\b/.test(source)) throw new Error('Animation.tsx 必须导出默认 React 组件。');
}
