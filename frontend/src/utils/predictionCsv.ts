export interface CsvCheck { columns: string[]; featureCount: number; sampleId: string; error?: string }
// A small RFC4180 parser keeps quoted feature names intact; no expression data is stored.
export function checkPredictionCsv(text: string, expected?: readonly string[]): CsvCheck {
  const rows: string[][] = []; let row: string[] = [], cell = '', quoted = false, closed = false;
  const invalid = (error: string): CsvCheck => ({ columns: [], featureCount: 0, sampleId: '', error });
  text = text.replace(/^\uFEFF/, '');
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) { if (c === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else { quoted = false; closed = true; } } else cell += c; continue; }
    if (c === '"') { if (cell || closed) return invalid('CSV引号格式无效'); quoted = true; }
    else if (c === ',' || c === '\n' || c === '\r') {
      row.push(cell); cell = ''; closed = false;
      if (c !== ',') { if (row.some(v => v.trim())) rows.push(row); row = []; if (c === '\r' && text[i + 1] === '\n') i++; }
    } else { if (closed) return invalid('CSV引号后存在多余字符'); cell += c; }
  }
  if (quoted) return invalid('CSV引号未闭合');
  row.push(cell); if (row.some(v => v.trim())) rows.push(row);
  if (rows.length !== 2) return invalid(`要求表头和恰好1个样本行，实际样本行数：${Math.max(0, rows.length - 1)}`);
  const [columns, values] = rows;
  if (columns.length !== values.length) return invalid('样本行与表头的字段数不一致');
  if (columns.some(v => !v.trim())) return invalid('特征列名不能为空');
  if (new Set(columns).size !== columns.length) return invalid('CSV存在重复特征列');
  const features = columns.filter(v => v !== 'sample_id');
  if (!features.length) return invalid('CSV缺少表达特征');
  const bad = values.findIndex((v, i) => columns[i] !== 'sample_id' && (!v.trim() || !Number.isFinite(Number(v)) || !/^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/.test(v.trim())));
  if (bad !== -1) return invalid(`特征 ${columns[bad]} 不是有限数值或存在缺失值`);
  const result: CsvCheck = { columns, featureCount: features.length, sampleId: values[columns.indexOf('sample_id')] || 'uploaded_sample' };
  if (expected) { const actual = new Set(features), required = new Set(expected); const missing = expected.filter(f => !actual.has(f)).length, extra = features.filter(f => !required.has(f)).length; if (missing || extra) result.error = `特征清单不匹配：缺少${missing}列，多出${extra}列`; }
  return result;
}
