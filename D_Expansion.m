// Power Query query D_Expansion - loads grid_expansion.csv
let
    Source = Csv.Document(Web.Contents(GitHubBaseUrl, [RelativePath = "grid_expansion.csv"]),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Header = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Empty = Table.ReplaceValue(Header, "", null, Replacer.ReplaceValue, Table.ColumnNames(Header)),
    Typed = Table.TransformColumnTypes(Empty, {{"from_lat", type number}, {"from_lon", type number}, {"to_lat", type number}, {"to_lon", type number}, {"capacity_mw", type number}, {"voltage_kv", type number}, {"length_km", type number}, {"built_km", type number}, {"planned_year", Int64.Type}}, "en-US")
in
    Typed
