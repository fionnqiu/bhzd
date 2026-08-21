-- Store the complete role assignment while retaining provider_configs.role as
-- a compatibility projection for older clients and historical SQL readers.
ALTER TABLE provider_configs ADD COLUMN roles_json TEXT NOT NULL DEFAULT '[]';

-- Existing rows had one scalar role.  Convert that value into the new set and
-- leave the unassigned sentinel as an empty set so it cannot become a runtime role.
UPDATE provider_configs
SET roles_json = CASE
  WHEN role = 'none' THEN '[]'
  ELSE json_array(role)
END;
