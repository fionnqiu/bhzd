/**
 * 结果摘要卡的客户端兜底压缩。
 *
 * 新事件由后端直接发送紧凑摘要；这里仍做一次边界收敛，保证旧事件回放或
 * 其他兼容服务返回长文本时，不会重新把完整回答复制到摘要卡中。
 */
export function compactRunSummary(value: string, maxLines = 2, maxChars = 140): string {
  const lines = value
    .split(/\r?\n/)
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter(Boolean);
  if (lines.length === 0) return "";

  const detailLines = lines.filter((line) => !"✓✗×·".includes(line[0] ?? ""));
  const candidates = detailLines.length > 0 ? detailLines : lines;
  const selected =
    candidates.length > maxLines
      ? [...candidates.slice(0, maxLines - 1), candidates[candidates.length - 1]]
      : candidates;
  const joined = selected.join("\n");
  if (joined.length <= maxChars) return joined;

  // Prefer a complete sentence so the compact card does not end mid-word or mid-clause.
  const punctuation = /[。！？!?；;]/g;
  let boundary = -1;
  for (const match of joined.matchAll(punctuation)) {
    if ((match.index ?? 0) >= maxChars) break;
    boundary = match.index ?? boundary;
  }
  const cutoff = boundary >= Math.max(24, Math.floor(maxChars / 3)) ? boundary + 1 : maxChars;
  return `${joined.slice(0, cutoff).replace(/[，,、:：\s]+$/u, "")}...`;
}
