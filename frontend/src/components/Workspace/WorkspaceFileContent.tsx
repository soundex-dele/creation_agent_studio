import { useMemo, useState } from 'react';
import { Segmented } from 'antd';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { WorkspaceFilePreview } from '@/types/workspaceFiles';

function textFormat(file: WorkspaceFilePreview) {
  const mime = file.mime_type?.split(';')[0].trim().toLowerCase();
  if (/\.(md|markdown)$/i.test(file.name) || mime === 'text/markdown' || mime === 'text/x-markdown') return 'markdown';
  if (/\.html?$/i.test(file.name) || mime === 'text/html') return 'html';
  return 'text';
}

export default function WorkspaceFileContent({ file }: { file: WorkspaceFilePreview }) {
  const [mode, setMode] = useState('preview');
  const format = textFormat(file);
  const richText = file.preview_kind === 'text' && format !== 'text';
  const html = useMemo(() => {
    if (format !== 'html' || file.preview_kind !== 'text') return '';
    // The opaque-origin sandbox blocks scripts, forms, popups and access to the
    // host app. CSP also blocks nested frames, network calls and relative URLs
    // resolving against the host; absolute HTTPS images/styles remain usable.
    return '<!doctype html><html><head><meta charset="utf-8">'
      + '<base href="about:blank"><meta name="referrer" content="no-referrer">'
      + '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
      + 'img-src https: data: blob:; style-src \'unsafe-inline\' https:; font-src https: data:; '
      + 'base-uri \'none\'; form-action \'none\'">'
      + '<meta name="viewport" content="width=device-width, initial-scale=1">'
      + '</head><body>' + (file.content ?? '') + '</body></html>';
  }, [file.content, file.preview_kind, format]);

  return <>
    {richText && <div className="workspace-file-preview-toolbar">
      <Segmented
        aria-label="文件查看方式"
        value={mode}
        onChange={value => setMode(String(value))}
        options={[{ label: '预览', value: 'preview' }, { label: '源码', value: 'source' }]}
      />
      {format === 'html' && mode === 'preview' && <small>静态预览，不执行脚本</small>}
    </div>}
    <div className={`workspace-file-preview-body${richText && mode === 'preview' && format === 'html' ? ' workspace-file-preview-body--html' : ''}`}>
      {file.preview_kind === 'text' && (
        !richText || mode === 'source' ? <pre>{file.content}</pre>
          : format === 'markdown' ? <article className="workspace-file-markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
              a: ({ href, children }) => /^https?:\/\/|^mailto:/i.test(href ?? '')
                ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
                : <span title="暂不支持打开相对路径链接">{children}</span>,
              img: ({ src, alt }) => /^https?:\/\//i.test(src ?? '')
                ? <img src={src} alt={alt ?? ''} loading="lazy" referrerPolicy="no-referrer" />
                : <span>{alt || '图片'}（相对路径图片暂不支持预览）</span>,
            }}>{file.content ?? ''}</ReactMarkdown>
          </article>
            : <iframe title={`${file.name} HTML 预览`} className="workspace-file-html"
              sandbox="" referrerPolicy="no-referrer" srcDoc={html} />
      )}
      {file.preview_kind === 'image' && (file.data_url
        ? <img src={file.data_url} alt={file.name} />
        : <div className="workspace-file-preview-state">图片较大，暂不支持在线预览</div>)}
      {file.preview_kind === 'binary' && <div className="workspace-file-preview-state">该文件暂不支持在线预览</div>}
    </div>
  </>;
}
