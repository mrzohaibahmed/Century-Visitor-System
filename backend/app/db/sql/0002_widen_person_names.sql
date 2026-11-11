/* =====================================================================================================
   Schema version 2: person names up to 100 characters.

   identity.normalize_name() accepts visitor, unlisted-host and watchlist names of 2-100 characters;
   0001 gave them NVARCHAR(60) (60 is the limit for directory names: gates, departments, hosts).
   ALTER COLUMN restates NULL / NOT NULL (it would otherwise make the column nullable), and the two
   indexes on widened columns are dropped and recreated around it (SQL Server requires that).
   ===================================================================================================== */
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

DROP INDEX ix_visitors_name_directory ON dbo.visitors;
ALTER TABLE dbo.visitors ALTER COLUMN full_name   NVARCHAR(100) NOT NULL;
ALTER TABLE dbo.visitors ALTER COLUMN name_search NVARCHAR(100) NOT NULL;
CREATE INDEX ix_visitors_name_directory ON dbo.visitors (name_search, id);   -- alphabetical directory + prefix
GO

ALTER TABLE dbo.visits ALTER COLUMN snap_visitor_name NVARCHAR(100) NOT NULL;
ALTER TABLE dbo.visits ALTER COLUMN snap_host_name    NVARCHAR(100) NULL;     -- an unlisted host's typed name
GO

DROP INDEX ix_watchlist_name_prefix ON dbo.watchlist;
ALTER TABLE dbo.watchlist ALTER COLUMN name        NVARCHAR(100) NULL;
ALTER TABLE dbo.watchlist ALTER COLUMN name_search NVARCHAR(100) NULL;
CREATE INDEX ix_watchlist_name_prefix ON dbo.watchlist (name_search) WHERE name_search IS NOT NULL;
GO

ALTER TABLE dbo.entry_denials ALTER COLUMN visitor_name NVARCHAR(100) NULL;
GO
