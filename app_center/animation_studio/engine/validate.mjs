import ts from 'typescript';

const imports = new Set(['react', 'remotion', './assets']);
const forbidden = new Set(['require', 'eval', 'Function', 'globalThis', 'window', 'document', 'parent', 'top', 'self', 'frames', 'location', 'navigator', 'fetch', 'XMLHttpRequest', 'WebSocket', 'Worker', 'SharedWorker', 'WebAssembly', 'process', 'global', 'localStorage', 'sessionStorage', 'indexedDB', 'setTimeout', 'setInterval', 'requestAnimationFrame', 'Date', 'performance', 'constructor', '__proto__', 'prototype', 'dangerouslySetInnerHTML', 'staticFile', 'useEffect', 'useLayoutEffect']);
// These browser globals also occur in scene data and layout styles. Permit data
// properties and lexical bindings, but never unresolved references to the globals.
const dataNames = new Set(['frames', 'top', 'parent', 'self', 'location']);

function isDataPropertyName(node) {
  const parent = node.parent;
  return ((ts.isPropertyAccessExpression(parent) || ts.isPropertySignature(parent) ||
    ts.isPropertyAssignment(parent) || ts.isJsxAttribute(parent)) && parent.name === node) ||
    (ts.isBindingElement(parent) && parent.propertyName === node);
}

function hasRuntimeBinding(symbol, tree) {
  return symbol?.declarations?.some(declaration => {
    if (declaration.getSourceFile() !== tree) return false;
    // `declare const frames` is erased and must not authorize the real global.
    for (let node = declaration; node; node = node.parent) {
      if (node.modifiers?.some(modifier => modifier.kind === ts.SyntaxKind.DeclareKeyword)) return false;
      if (node.isTypeOnly) return false;
    }
    return ts.isVariableDeclaration(declaration) || ts.isBindingElement(declaration) ||
      ts.isParameter(declaration) || ts.isImportSpecifier(declaration) ||
      ts.isImportClause(declaration) || ts.isNamespaceImport(declaration) ||
      ts.isFunctionExpression(declaration) ||
      (ts.isFunctionDeclaration(declaration) && Boolean(declaration.body));
  });
}

// Restrict generated compositions, never the trusted Player/render entrypoints.
// This is a capability guard in addition to the isolated preview CSP, not an OS sandbox.
export function validateSource(source) {
  if (typeof source !== 'string' || source.length > 150000) throw new Error('动画源码为空或超过 150000 字符。');
  const tree = ts.createSourceFile('Animation.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  if (tree.parseDiagnostics.length) throw new Error(ts.flattenDiagnosticMessageText(tree.parseDiagnostics[0].messageText, '\n'));
  let checker;
  function getChecker() {
    if (!checker) {
      const options = {noLib:true, noResolve:true, target:ts.ScriptTarget.Latest, jsx:ts.JsxEmit.React};
      const host = ts.createCompilerHost(options);
      // Binding is entirely in-memory; no module resolution or filesystem reads.
      host.getSourceFile = name => name === tree.fileName ? tree : undefined;
      host.readFile = name => name === tree.fileName ? source : undefined;
      host.fileExists = name => name === tree.fileName;
      checker = ts.createProgram([tree.fileName], options, host).getTypeChecker();
    }
    return checker;
  }
  function isLocalDataName(node) {
    if (isDataPropertyName(node)) return true;
    const checker = getChecker();
    const symbol = ts.isShorthandPropertyAssignment(node.parent)
      ? checker.getShorthandAssignmentValueSymbol(node.parent)
      : checker.getSymbolAtLocation(node);
    return hasRuntimeBinding(symbol, tree);
  }
  function isOwnPropertyCheck(node) {
    // Permit only the complete read-only idiom, never a prototype value, alias,
    // mutation, arbitrary method or .call argument that escapes normal traversal.
    const prototype = node.parent;
    if (!ts.isPropertyAccessExpression(prototype) || prototype.name !== node || prototype.questionDotToken ||
        !ts.isIdentifier(prototype.expression) || prototype.expression.text !== 'Object' ||
        getChecker().getSymbolAtLocation(prototype.expression)) return false;
    const method = prototype.parent;
    const call = method.parent;
    const invocation = call.parent;
    return ts.isPropertyAccessExpression(method) && method.expression === prototype &&
      !method.questionDotToken && method.name.text === 'hasOwnProperty' &&
      ts.isPropertyAccessExpression(call) && call.expression === method &&
      !call.questionDotToken && call.name.text === 'call' &&
      ts.isCallExpression(invocation) && invocation.expression === call &&
      !invocation.questionDotToken && invocation.arguments.length === 2 &&
      invocation.arguments.every(argument => !ts.isSpreadElement(argument));
  }
  function rejectCapability(node, name) {
    const {line, character} = tree.getLineAndCharacterOfPosition(node.getStart(tree));
    const hint = ['prototype', '__proto__', 'constructor'].includes(name)
      ? ' 不要读取、修改或遍历原型链；检查自有属性请使用 Object.hasOwn(data, key)，数组转换请使用 Array.from(value)，不要添加原型兼容补丁。'
      : '';
    throw new Error(`Animation.tsx:${line + 1}:${character + 1} 不允许在动画中使用 ${name}。${hint}`);
  }
  function visit(node) {
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier) {
      if (!ts.isStringLiteral(node.moduleSpecifier) || !imports.has(node.moduleSpecifier.text)) throw new Error('只允许导入 react、remotion 和 ./assets。');
    }
    if (ts.isImportEqualsDeclaration(node) || ts.isImportTypeNode(node) || node.kind === ts.SyntaxKind.ImportKeyword) throw new Error('不允许动态导入。');
    // A bare/aliased `this` can expose the window object in generated functions.
    if (node.kind === ts.SyntaxKind.ThisKeyword) throw new Error('动画组件不能通过 this 访问全局执行能力。');
    if (ts.isIdentifier(node) && forbidden.has(node.text) &&
        !(dataNames.has(node.text) && isLocalDataName(node)) &&
        !(node.text === 'prototype' && isOwnPropertyCheck(node))) rejectCapability(node, node.text);
    if (ts.isPropertyAccessExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 'Math' && node.name.text === 'random') throw new Error('使用 remotion.random(seed)，不能使用 Math.random。');
    if ((ts.isStringLiteralLike(node) || ts.isNoSubstitutionTemplateLiteral(node)) && /(?:https?:|file:|javascript:|\/\/|@import|@font-face)/i.test(node.text)) throw new Error('动画只能引用归档素材，不能加载远程资源。');
    if (ts.isElementAccessExpression(node) && ts.isStringLiteralLike(node.argumentExpression) && forbidden.has(node.argumentExpression.text) && !dataNames.has(node.argumentExpression.text)) rejectCapability(node.argumentExpression, node.argumentExpression.text);
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
