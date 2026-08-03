export function renderTemplate(value, context) {
  if (typeof value !== 'string') return value;
  return value.replace(/\{\{\s*([\w.]+)\s*\}\}/g, (_, keyPath) => {
    const resolved = keyPath.split('.').reduce((current, key) => current?.[key], context);
    return resolved == null ? '' : String(resolved);
  });
}

export function renderObject(value, context) {
  if (Array.isArray(value)) return value.map((item) => renderObject(item, context));
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, renderObject(item, context)]));
  }
  return renderTemplate(value, context);
}

export function truthyTemplate(value, context) {
  const rendered = renderTemplate(value, context).trim().toLowerCase();
  if (!rendered) return false;
  if (['0', 'false', 'no', 'n', 'off', 'null', 'undefined'].includes(rendered)) return false;
  return true;
}
