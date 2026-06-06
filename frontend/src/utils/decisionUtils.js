/**
 * Utility functions for processing decision data and entity relationships
 */

/**
 * Get the main recipient/sponsor entity from decision data
 * @param {Object} decision - The decision object
 * @param {Object|null} entityRelationships - The entity relationships data
 * @param {boolean} hasPreloadedEntityData - Whether entity data is preloaded
 * @returns {Object|null} The main recipient object or null
 */
export const getMainRecipient = (decision, entityRelationships, hasPreloadedEntityData) => {
  // If we have preloaded data from optimized API, use it
  if (hasPreloadedEntityData && decision.main_recipient) {
    return {
      entity: {
        afm: decision.main_recipient.afm,
        name: decision.main_recipient.name,
      },
      total_amount: decision.main_recipient.amount,
    };
  }

  // Otherwise use loaded entity relationships
  if (!entityRelationships?.relationships) return null;

  // First try to find sponsor or creditor with amount
  let recipient = entityRelationships.relationships.find(rel =>
    (rel.role?.toLowerCase().includes('sponsor') || rel.role?.toLowerCase().includes('creditor'))
    && rel.total_amount
  );

  // If no sponsor/creditor found, try to find ANY entity with an amount (excluding org which is usually 0)
  if (!recipient) {
    recipient = entityRelationships.relationships.find(rel =>
      rel.total_amount && rel.role?.toLowerCase() !== 'org'
    );
  }

  return recipient;
};

/**
 * Calculate the total amount to display for a decision
 * @param {Object} decision - The decision object
 * @param {Object|null} entityRelationships - The entity relationships data
 * @param {boolean} hasPreloadedEntityData - Whether entity data is preloaded
 * @param {Object|null} mainRecipient - The main recipient object (optional, will be calculated if not provided)
 * @returns {number|null} The display amount or null
 */
export const getTotalAmount = (decision, entityRelationships, hasPreloadedEntityData, mainRecipient = null) => {
  // If we have preloaded entity amount, use it
  if (hasPreloadedEntityData && decision.entity_amount) {
    return decision.entity_amount;
  }

  // If main recipient provided and has amount, use it
  if (mainRecipient?.total_amount) {
    return mainRecipient.total_amount;
  }

  // Calculate main recipient if not provided
  if (!mainRecipient) {
    mainRecipient = getMainRecipient(decision, entityRelationships, hasPreloadedEntityData);
    if (mainRecipient?.total_amount) {
      return mainRecipient.total_amount;
    }
  }

  // Calculate total from all entities
  if (entityRelationships?.relationships) {
    const total = entityRelationships.relationships
      .filter(rel => rel.role?.toLowerCase() !== 'org') // Exclude org amounts
      .reduce((sum, rel) => {
        return sum + (rel.total_amount || 0);
      }, 0);
    if (total > 0) return total;
  }

  // Fall back to decision amount
  return decision.amount || null;
};

/**
 * Group entity relationships by role and AFM to eliminate duplicates
 * @param {Array} relationships - Array of relationship objects
 * @returns {Array} Processed relationships with occurrence counts
 */
export const groupEntityRelationships = (relationships) => {
  const groupedRelationships = {};

  relationships.forEach(rel => {
    const key = `${rel.role}-${rel.entity.afm}`;

    if (!groupedRelationships[key]) {
      groupedRelationships[key] = {
        ...rel,
        occurrences: 1,
        parent_key_paths: [rel.parent_key_path]
      };
    } else {
      groupedRelationships[key].occurrences += 1;
      groupedRelationships[key].parent_key_paths.push(rel.parent_key_path);
    }
  });

  return Object.values(groupedRelationships);
};

/**
 * Extract counterpart entities from preloaded decision data.
 * Returns entities excluding "org" role, sorted by amount descending.
 * @param {Object} decision - The decision object with preloaded entities array
 * @returns {Array|null} Counterpart entities or null
 */
export const getCounterpartEntities = (decision) => {
  if (!decision?.entities || !Array.isArray(decision.entities)) return null;

  return decision.entities
    .filter(e => e.role?.toLowerCase() !== 'org')
    .sort((a, b) => (b.total_amount || 0) - (a.total_amount || 0));
};
