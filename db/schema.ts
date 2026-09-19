// Intentionally empty by default.
// Add Drizzle tables here when the site actually needs a database.
// See examples/d1/db/schema.ts for an opt-in example.
import { sqliteTable, text } from 'drizzle-orm/sqlite-core';
export const records = sqliteTable('records', { id:text('id').primaryKey(), kind:text('kind').notNull(), companyId:text('company_id').notNull(), payload:text('payload').notNull(), sourceUrl:text('source_url').notNull(), updatedAt:text('updated_at').notNull(), updatedBy:text('updated_by').notNull() });
