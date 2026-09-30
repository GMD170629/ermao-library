import { createRequire } from 'node:module';
import { writeFileSync } from 'node:fs';

const require = createRequire(new URL('../../apps/web/package.json', import.meta.url));
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const lucide = require('lucide-react');

const names = [
  'Activity', 'AlertCircle', 'ArrowLeft', 'Bold', 'BookOpen', 'BookKey', 'Check',
  'CheckCircle2', 'ChevronDown', 'ChevronRight', 'CircleHelp', 'Clock3', 'Database',
  'Download', 'Eye', 'ExternalLink', 'FileImage', 'FileText', 'HardDrive', 'ImagePlus',
  'Info', 'Layers3', 'List', 'Mail', 'MessageSquarePlus', 'Paperclip', 'Pencil',
  'RefreshCw', 'Scale', 'Search', 'Send', 'ShieldCheck', 'Sparkles', 'Trash2',
  'UploadCloud', 'UserRound', 'Users', 'X'
];

const output = Object.fromEntries(names.map((name) => {
  const component = lucide[name];
  if (!component) throw new Error(`Unknown Lucide icon: ${name}`);
  return [name, renderToStaticMarkup(React.createElement(component, {
    size: 20, strokeWidth: 1.8, 'aria-hidden': 'true'
  }))];
}));

writeFileSync(new URL('./icons.json', import.meta.url), JSON.stringify(output));
