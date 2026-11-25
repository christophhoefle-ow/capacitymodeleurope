// Power Query query D_Connection - loads grid_connection_tso.csv
let
    Source = Csv.Document(Web.Contents(GitHubBaseUrl, [RelativePath = "grid_connection_tso.csv"]),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Header = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Empty = Table.ReplaceValue(Header, "", null, Replacer.ReplaceValue, Table.ColumnNames(Header)),
    Typed = Table.TransformColumnTypes(Empty, {{"feed_in_free_from_mw", type number}, {"feed_in_free_to_mw", type number}, {"load_free_from_mw", type number}, {"load_free_to_mw", type number}, {"available_from_year", Int64.Type}}, "en-US")
in
    Typed
