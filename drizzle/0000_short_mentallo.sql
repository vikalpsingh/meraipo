CREATE TABLE `records` (
	`id` text PRIMARY KEY NOT NULL,
	`kind` text NOT NULL,
	`company_id` text NOT NULL,
	`payload` text NOT NULL,
	`source_url` text NOT NULL,
	`updated_at` text NOT NULL,
	`updated_by` text NOT NULL
);
