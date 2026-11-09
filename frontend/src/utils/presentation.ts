// Keep the experiment metadata intact and use its short method label in the UI.
export function displaySplitProtocol(protocol?: string) {
  return protocol?.split('；')[0].replace('，患者不跨折', '') || '—';
}
