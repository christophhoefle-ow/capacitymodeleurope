# Power Query: alternative for a private repository

`Capacity_Model_Core_refreshable.xlsx` contains data connections that only work with a **publicly readable** repository. For a private repository (or if Excel does not accept the built-in
connections) set up Power Query in `Capacity_Model_Core.xlsx`. The M code is in `excel/power_query/*.m`.

1. Create the parameter `GitHubBaseUrl` (text): `https://raw.githubusercontent.com/<ORG>/<REPO>/main/data/processed/`
2. For each file create a blank query, open the advanced editor, paste the M code and name the query like the sheet:
   `D_Lines`, `D_Transformers`, `D_Substations`, `D_Utilization`, `D_Connection`, `D_Occupancy`, `D_Coordinates`, `D_Meta`.
3. Delete the example data of the D_ sheet from row 4 (unhide the sheet first), then Load to, Table, existing worksheet, cell A4.
4. From then on Data > Refresh all is enough. Sheet *Checks*: all statuses should be OK.

Numbers are read with the culture `en-US` (decimal point); empty fields become `null` before the type conversion.
Private repository: add `Headers = [Authorization = "token " & GitHubToken]` after `RelativePath` (never store the token in a shared file).
**Not tested in Excel.**
