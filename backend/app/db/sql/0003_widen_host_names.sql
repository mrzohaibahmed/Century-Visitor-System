/* =====================================================================================================
   Schema version 3: host names up to 100 characters.

   Hosts are people: their names go through identity.normalize_name() (2-100 characters), like visitor
   and watchlist names (0002). 0001 gave hosts.name / name_search NVARCHAR(60), the limit for gate and
   department names. The index on name_search is dropped and recreated around the change.
   ===================================================================================================== */
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

DROP INDEX ix_hosts_active_by_name ON dbo.hosts;
ALTER TABLE dbo.hosts ALTER COLUMN name        NVARCHAR(100) NOT NULL;
ALTER TABLE dbo.hosts ALTER COLUMN name_search NVARCHAR(100) NOT NULL;
CREATE INDEX ix_hosts_active_by_name ON dbo.hosts (is_active, name_search);   -- host picker
GO
