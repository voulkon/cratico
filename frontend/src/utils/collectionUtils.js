/**
 * Deduplicate an array of objects by a key property.
 * Keeps the first occurrence when duplicates are found.
 *
 * @param {Array} items - Array of objects
 * @param {string} key - Property name to deduplicate by
 * @returns {Array} Deduplicated array
 */
export function dedupByKey(items, key) {
  if (!Array.isArray(items)) return [];
  const seen = new Map();
  for (const item of items) {
    const k = item?.[key];
    if (k != null && !seen.has(k)) {
      seen.set(k, item);
    }
  }
  return Array.from(seen.values());
}
