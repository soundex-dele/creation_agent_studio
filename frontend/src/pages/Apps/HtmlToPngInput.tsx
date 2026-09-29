import { useState } from 'react';
import { Button, Checkbox, Input, InputNumber, Radio, Select, message } from 'antd';
import { FolderOpen, Image, Plus, SlidersHorizontal, Trash2 } from 'lucide-react';
import FolderPickerModal from './FolderPickerModal';

export default function HtmlToPngInput({ loading, onStart }: {
  loading: boolean;
  onStart: (input: Record<string, unknown>) => void;
}) {
  const [directories, setDirectories] = useState<string[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [orientation, setOrientation] = useState<'horizontal' | 'vertical'>('horizontal');
  const [width, setWidth] = useState<number | null>(null);
  const [height, setHeight] = useState<number | null>(null);
  const [scale, setScale] = useState(2);
  const [selector, setSelector] = useState('.cover');
  const [waitUntil, setWaitUntil] = useState('networkidle');
  const [fullPage, setFullPage] = useState(false);
  const [transparent, setTransparent] = useState(false);
  const [noWebFonts, setNoWebFonts] = useState(false);
  const addDirectory = (path = '') => setDirectories(current => path && current.includes(path) ? current : [...current, path]);
  const submit = () => {
    const cleaned = directories.map(item => item.trim()).filter(Boolean);
    if (!cleaned.length) { message.warning('请至少添加一个 HTML 目录'); return; }
    onStart({ directories: cleaned, orientation, ...(width ? { width } : {}), ...(height ? { height } : {}),
      device_scale_factor: scale, selector, wait_until: waitUntil, full_page: fullPage, transparent, no_web_fonts: noWebFonts });
  };
  return <div className="conversion-settings">
    <section className="conversion-section" aria-labelledby="conversion-source-title">
      <div className="conversion-section-title"><span>01</span><div><h2 id="conversion-source-title">选择 HTML 目录</h2><p>将目录中的 HTML 文件，批量保存为清晰的 PNG 图片。</p></div><FolderOpen size={22} aria-hidden="true" /></div>
      {!directories.length && <div className="conversion-source-empty"><FolderOpen size={32} aria-hidden="true" /><strong>从一份封面或一组图文开始</strong><p>选择服务器上的目录，或手动输入目录路径。</p></div>}
      <div className="conversion-directory-list">{directories.map((directory, index) => <div className="conversion-directory" key={index}>
        <label htmlFor={`conversion-directory-${index}`}>目录 {index + 1}</label>
        <div><Input id={`conversion-directory-${index}`} value={directory} placeholder="输入服务器上的 HTML 目录" onChange={event => setDirectories(current => current.map((item, i) => i === index ? event.target.value : item))} />
          <Button aria-label={`删除目录 ${index + 1}`} icon={<Trash2 size={16} aria-hidden="true" />} onClick={() => setDirectories(current => current.filter((_, i) => i !== index))} /></div>
      </div>)}</div>
      <div className="conversion-directory-actions"><Button icon={<FolderOpen size={16} aria-hidden="true" />} onClick={() => setPickerOpen(true)}>选择目录</Button><Button icon={<Plus size={16} aria-hidden="true" />} onClick={() => addDirectory()}>手动添加</Button></div>
      <p className="conversion-hint">仅转换目录直属的 HTML 文件，图片以同名 PNG 保存在原目录中。</p>
    </section>
    <section className="conversion-section" aria-labelledby="conversion-size-title">
      <div className="conversion-section-title"><span>02</span><div><h2 id="conversion-size-title">设置画面规格</h2><p>选择常用版式，也可以自定义宽高。</p></div><Image size={22} aria-hidden="true" /></div>
      <Radio.Group className="conversion-orientation" aria-label="画面方向" value={orientation} onChange={event => setOrientation(event.target.value)}>
        <Radio.Button value="horizontal"><span className="conversion-ratio conversion-ratio--wide" aria-hidden="true" /><span>横版<small>1283 × 383</small></span></Radio.Button>
        <Radio.Button value="vertical"><span className="conversion-ratio conversion-ratio--tall" aria-hidden="true" /><span>竖版<small>1080 × 1440</small></span></Radio.Button>
      </Radio.Group>
      <div className="conversion-dimensions">
        <label htmlFor="conversion-width">自定义宽度<InputNumber id="conversion-width" min={1} max={10000} placeholder="默认宽度" value={width} onChange={setWidth} /></label>
        <label htmlFor="conversion-height">自定义高度<InputNumber id="conversion-height" min={1} max={10000} placeholder="默认高度" value={height} onChange={setHeight} /></label>
        <label htmlFor="conversion-scale">像素倍率<InputNumber id="conversion-scale" min={1} max={4} step={0.5} value={scale} onChange={value => setScale(value ?? 2)} /></label>
      </div>
      <p className="conversion-hint">宽高单位为 CSS 像素；留空使用版式默认值。像素倍率决定输出图片的清晰度与大小。</p>
    </section>
    <details className="conversion-advanced">
      <summary><SlidersHorizontal size={18} aria-hidden="true" /><span>高级设置<small>截图范围、透明背景与页面加载</small></span></summary>
      <div className="conversion-advanced-body">
        <div className="conversion-advanced-fields"><label htmlFor="conversion-selector">截图元素<Input id="conversion-selector" value={selector} placeholder="例如 .cover" disabled={fullPage} onChange={event => setSelector(event.target.value)} /></label>
          <label htmlFor="conversion-wait">页面等待<Select id="conversion-wait" value={waitUntil} onChange={setWaitUntil} options={[{ value: 'networkidle', label: '网络空闲' }, { value: 'load', label: '页面加载完成' }, { value: 'domcontentloaded', label: 'DOM 加载完成' }]} /></label></div>
        <div className="conversion-options"><Checkbox checked={fullPage} onChange={event => setFullPage(event.target.checked)}>截取整页</Checkbox><Checkbox checked={transparent} onChange={event => setTransparent(event.target.checked)}>透明背景</Checkbox><Checkbox checked={noWebFonts} onChange={event => setNoWebFonts(event.target.checked)}>移除网络字体</Checkbox></div>
      </div>
    </details>
    <div className="conversion-submit"><span>{directories.filter(path => path.trim()).length ? `已添加 ${directories.filter(path => path.trim()).length} 个目录` : '添加目录后即可开始'}<small>PNG 格式 · {scale} 倍像素</small></span><Button type="primary" size="large" loading={loading} onClick={submit}>开始转换</Button></div>
    <FolderPickerModal open={pickerOpen} onClose={() => setPickerOpen(false)} onSelect={path => { addDirectory(path); setPickerOpen(false); }} />
  </div>;
}
