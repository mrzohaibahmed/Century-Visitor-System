/* =====================================================================================================
   Schema version 4: the name search keys compare exactly (binary collation).

   name_search (visitors, hosts, watchlist) is a machine-made key: the name in lower case with single
   spaces (identity.search_key). Searches are "starts with" (LIKE 'key%') and lists sort by it. MongoDB
   compared it byte for byte; with a binary collation SQL Server does the same AND can still use the
   index (a COLLATE in the query would force a scan). The columns' indexes are dropped and recreated.
   ===================================================================================================== */
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

DROP INDEX ix_visitors_name_directory ON dbo.visitors;
ALTER TABLE dbo.visitors ALTER COLUMN name_search NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL;
CREATE INDEX ix_visitors_name_directory ON dbo.visitors (name_search, id);   -- alphabetical directory + prefix
GO

DROP INDEX ix_hosts_active_by_name ON dbo.hosts;
ALTER TABLE dbo.hosts ALTER COLUMN name_search NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL;
CREATE INDEX ix_hosts_active_by_name ON dbo.hosts (is_active, name_search);   -- host picker
GO

DROP INDEX ix_watchlist_name_prefix ON dbo.watchlist;
ALTER TABLE dbo.watchlist ALTER COLUMN name_search NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NULL;
CREATE INDEX ix_watchlist_name_prefix ON dbo.watchlist (name_search) WHERE name_search IS NOT NULL;
GO
